"""Backend der Linux Admin GUI (ohne Tk, daher testbar).

Alle Eingaben werden hier validiert. Alle privilegierten Aktionen laufen
gebündelt über genau einen pkexec-Aufruf pro Benutzeraktion.
"""
import grp
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import time
import datetime

from i18n import t

# --------------------------------------------------------------------------
# Konstanten
# --------------------------------------------------------------------------
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
OCTAL_RE = re.compile(r"^[0-7]{3,4}$")
SEARCH_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
SRV_ROOT = "/srv"
SYSTEM_GID_LIMIT = 1000  # Gruppen mit kleinerer GID gelten als Systemgruppen

ALLOWED_COMMANDS = (
    "useradd", "userdel", "usermod", "groupadd", "groupdel", "chpasswd",
    "chmod", "chown", "mkdir", "setfacl", "getfacl", "gpasswd", "passwd",
    "groupmod", "chage",
)

# Wie werden Administratorrechte beschafft?
#   None  = automatisch (siehe privilege_method)  – Tests setzen [] für "direkt"
#   Umgebungsvariable LAG_PRIVILEGE = auto | pkexec | sudo  (oder in der GUI wählbar)
ADMIN_PREFIX = None
PRIVILEGE_METHOD = os.environ.get("LAG_PRIVILEGE", "auto").strip().lower()

LOG_FILE = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "linux-admin-gui", "actions.log",
)

# Kleines Skript, das mit pkexec als root läuft. Es führt nur Befehle aus der
# übergebenen Whitelist aus, nacheinander, und bricht beim ersten Fehler ab.
# Die Aufträge kommen per stdin (JSON), Passwörter stehen also nie in der
# Prozessliste.
_HELPER = r"""
import json, subprocess, sys
sys.stdout.write("\x1eLAG\n")      # Marker: das Hilfsprogramm läuft (Rechte wurden erteilt)
sys.stdout.flush()
allowed = json.loads(sys.argv[1])
jobs = json.load(sys.stdin)
out = []
for job in jobs:
    prog = allowed.get(job["cmd"])
    if not prog:
        sys.stderr.write("command not allowed: %s" % job["cmd"])
        sys.exit(1)
    r = subprocess.run([prog] + job["args"], input=job.get("input"),
                       text=True, capture_output=True)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "operation failed").strip()
        sys.stderr.write("%s: %s" % (job["cmd"], msg))
        sys.exit(1)
    out.append(r.stdout)
sys.stdout.write("".join(out))
"""


_MARKER = "\x1eLAG\n"


class AdminError(RuntimeError):
    """Fehler bei einer (privilegierten) Aktion, Text ist für den Benutzer."""


class PasswordRequired(AdminError):
    """sudo braucht ein Passwort, die GUI soll danach fragen und es erneut versuchen."""


class WrongPassword(AdminError):
    """sudo hat das übergebene Passwort abgelehnt."""


_sudo_password = None


def set_sudo_password(password):
    """Passwort nur für die Dauer einer Aktion im Speicher halten."""
    global _sudo_password
    _sudo_password = password


def clear_sudo_password():
    set_sudo_password(None)


def privilege_method():
    """'direct' (root), 'pkexec' oder 'sudo'.

    Automatik: In SSH-Sitzungen gibt es meist keinen grafischen Polkit-Agenten,
    daher wird dort sudo bevorzugt; lokal pkexec.
    """
    if os.geteuid() == 0:
        return "direct"
    if PRIVILEGE_METHOD in ("pkexec", "sudo"):
        return PRIVILEGE_METHOD
    has_sudo, has_pkexec = shutil.which("sudo"), shutil.which("pkexec")
    over_ssh = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"))
    if over_ssh and has_sudo:
        return "sudo"
    if has_pkexec:
        return "pkexec"
    return "sudo" if has_sudo else "pkexec"


# --------------------------------------------------------------------------
# Validierung
# --------------------------------------------------------------------------
def validate_name(name, label="lab_name"):
    """Gibt den Namen zurück oder wirft ValueError (Meldung in der aktuellen Sprache).

    label ist ein i18n-Schlüssel (lab_user, lab_group, lab_newuser, lab_owner, lab_name).
    """
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise ValueError(t("bad_name", label=t(label)))
    return name


def ensure_plain_identifier(name, label="lab_name"):
    """Für bereits existierende Namen: nur Optionen-Injektion verhindern."""
    if not name or name.startswith("-") or "\n" in name or ":" in name:
        raise ValueError(t("bad_ident", label=t(label), value=repr(name)))
    return name


def validate_uid(uid):
    """UID als int; muss im UID-Bereich des Systems liegen und frei sein."""
    low, high = uid_range()
    try:
        value = int(str(uid).strip())
    except ValueError:
        raise ValueError(t("uid_nan"))
    if not low <= value <= high:
        raise ValueError(t("uid_range", low=low, high=high))
    if value in {u.pw_uid for u in pwd.getpwall()}:
        raise ValueError(t("uid_taken", uid=value))
    return value


def validate_comment(text):
    """Kommentar/Vollname für das GECOS-Feld."""
    text = (text or "").strip()
    if len(text) > 100:
        raise ValueError(t("comment_long"))
    if ":" in text or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(t("comment_chars"))
    return text


def _int_in_range(value, label, low, high):
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValueError(t("int_nan", label=t(label)))
    if not low <= number <= high:
        raise ValueError(t("int_range", label=t(label), low=low, high=high))
    return number


def aging_args(max_days=None, min_days=None, warn_days=None, expire=None, force_change=False):
    """Baut die chage-Optionen. Leere/None-Werte bleiben unverändert."""
    args = []
    for flag, value, label, low in (
        ("-M", max_days, "lab_maxdays", -1),
        ("-m", min_days, "lab_mindays", 0),
        ("-W", warn_days, "lab_warndays", 0),
    ):
        if value not in (None, ""):
            args += [flag, str(_int_in_range(value, label, low, 99999))]
    expire = (expire or "").strip()
    if expire:
        if expire.lower() in ("never", "nie", "-1"):
            args += ["-E", "-1"]
        else:
            try:
                datetime.date.fromisoformat(expire)
            except ValueError:
                raise ValueError(t("date_bad"))
            args += ["-E", expire]
    if force_change:
        args += ["-d", "0"]
    if not args:
        raise ValueError(t("aging_none"))
    return args


def parse_mode(text):
    """'770' / '2770' -> int. Wirft ValueError bei ungültiger Eingabe."""
    text = (text or "").strip()
    if not OCTAL_RE.match(text):
        raise ValueError(t("bad_mode"))
    return int(text, 8)


def chmod_arg(mode):
    """5-stellig, damit auch SUID/SGID/Sticky sicher gesetzt *und* gelöscht werden.

    GNU chmod behält SGID/SUID bei Ordnern bei 3-/4-stelligen Zahlen, löscht
    sie aber bei 5 Stellen (00770). So entspricht das Ergebnis immer dem,
    was in der GUI angezeigt wird.
    """
    return f"{mode & 0o7777:05o}"


def format_octal(mode):
    mode &= 0o7777
    return f"{mode:04o}" if mode & 0o7000 else f"{mode:03o}"


def perms_string(read, write, execute):
    perms = ("r" if read else "") + ("w" if write else "") + ("x" if execute else "")
    if not perms:
        raise ValueError(t("perms_none"))
    return perms


def safe_srv_path(path):
    """Gibt den aufgelösten Pfad zurück, wenn er *unterhalb* von /srv liegt.

    Verhindert '/srv/../etc', Symlink-Tricks und '/srv' selbst.
    """
    path = (path or "").strip()
    if not path.startswith("/") or "\n" in path or "\x00" in path:
        raise ValueError(t("path_abs"))
    srv = os.path.realpath(SRV_ROOT)
    real = os.path.realpath(path)
    if real == srv or os.path.commonpath([real, srv]) != srv:
        raise ValueError(t("path_srv"))
    return real


# --------------------------------------------------------------------------
# Benutzer / Gruppen lesen
# --------------------------------------------------------------------------
def _login_defs(key, default):
    try:
        with open("/etc/login.defs", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == key and parts[1].isdigit():
                    return int(parts[1])
    except OSError:
        pass
    return default


def uid_range():
    return _login_defs("UID_MIN", 1000), _login_defs("UID_MAX", 60000)


def list_users():
    low, high = uid_range()
    return sorted(u.pw_name for u in pwd.getpwall() if low <= u.pw_uid <= high)


def gid_range():
    """GID-Bereich normaler Gruppen (GID_MIN..GID_MAX aus /etc/login.defs)."""
    return _login_defs("GID_MIN", SYSTEM_GID_LIMIT), _login_defs("GID_MAX", 60000)


def list_groups(include_system=True):
    low, high = gid_range()
    return sorted(
        g.gr_name for g in grp.getgrall()
        if include_system or low <= g.gr_gid <= high
    )


def is_system_group(name):
    """True für Gruppen außerhalb des normalen GID-Bereichs (z. B. root, sudo, nogroup)."""
    try:
        gid = grp.getgrnam(name).gr_gid
    except KeyError:
        return False
    low, high = gid_range()
    return not (low <= gid <= high)


def primary_group(user):
    return grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name


def supplementary_groups(user):
    """Zusätzliche Gruppen (ohne Primärgruppe) – nur diese lassen sich entfernen."""
    primary_gid = pwd.getpwnam(user).pw_gid
    return sorted(
        g.gr_name for g in grp.getgrall()
        if user in g.gr_mem and g.gr_gid != primary_gid
    )


def all_groups_of(user):
    return sorted(set(supplementary_groups(user)) | {primary_group(user)})


def group_members(group):
    """Mitglieder inklusive Benutzern, die die Gruppe als Primärgruppe haben."""
    g = grp.getgrnam(group)
    primary = [u.pw_name for u in pwd.getpwall() if u.pw_gid == g.gr_gid]
    return sorted(set(g.gr_mem) | set(primary))


def owner_group_of(path):
    s = os.stat(path)
    try:
        owner = pwd.getpwuid(s.st_uid).pw_name
    except KeyError:
        owner = str(s.st_uid)
    try:
        group = grp.getgrgid(s.st_gid).gr_name
    except KeyError:
        group = str(s.st_gid)
    return owner, group, stat.S_IMODE(s.st_mode)


# --------------------------------------------------------------------------
# Privilegierte Aktionen
# --------------------------------------------------------------------------
def find_program(name):
    path = shutil.which(name, path=SEARCH_PATH)
    if not path:
        hint = t("prog_acl_hint") if name in ("setfacl", "getfacl") else ""
        raise AdminError(t("prog_missing", name=name) + hint)
    return path


def admin_batch(jobs):
    """Führt mehrere Befehle mit EINEM pkexec-Aufruf aus.

    jobs: Liste von (befehl, [argumente]) oder (befehl, [argumente], stdin).
    Bricht beim ersten Fehler ab. Wirft AdminError.
    """
    normalized = []
    for job in jobs:
        cmd, args = job[0], [str(a) for a in job[1]]
        text = job[2] if len(job) > 2 else None
        if cmd not in ALLOWED_COMMANDS:
            raise AdminError(t("cmd_not_allowed", cmd=cmd))
        normalized.append({"cmd": cmd, "args": args, "input": text})

    allowed = {j["cmd"]: find_program(j["cmd"]) for j in normalized}
    feed = ""
    if ADMIN_PREFIX is not None:
        method, prefix = ("explicit" if ADMIN_PREFIX else "direct"), list(ADMIN_PREFIX)
    else:
        method = privilege_method()
        prefix = ["pkexec"] if method == "pkexec" else []
        if method == "sudo":
            sudo = shutil.which("sudo")
            if not sudo:
                raise AdminError(t("sudo_missing"))
            no_password = subprocess.run([sudo, "-n", "true"], capture_output=True).returncode == 0
            if no_password:                       # NOPASSWD oder gültiger Zeitstempel
                prefix = [sudo]
            elif _sudo_password is None:
                raise PasswordRequired(t("pw_required"))
            else:                                 # Passwort kommt über stdin (-S), nie über die Kommandozeile
                prefix = [sudo, "-k", "-S", "-p", ""]
                feed = _sudo_password + "\n"

    command = prefix + [
        sys.executable or shutil.which("python3") or "/usr/bin/python3",
        "-c", _HELPER, json.dumps(allowed),
    ]
    try:
        result = subprocess.run(
            command, input=feed + json.dumps(normalized),
            text=True, capture_output=True,
        )
    except FileNotFoundError:
        raise AdminError(t("pkexec_missing"))

    stderr = (result.stderr or "").strip()
    stdout = result.stdout or ""
    started = stdout.startswith(_MARKER)          # Hilfsprogramm lief wirklich (Rechte erteilt)
    if started:
        stdout = stdout[len(_MARKER):]
    if method == "sudo" and result.returncode != 0 and not started:
        log_action(normalized, "ABGEBROCHEN", stderr)
        if "sudoers" in stderr.lower():
            raise AdminError(t("sudo_denied", detail=stderr))
        raise WrongPassword(t("wrong_pw", detail=stderr))
    if method == "pkexec" and result.returncode in (126, 127):
        log_action(normalized, "ABGEBROCHEN", stderr)
        raise AdminError(
            t("pkexec_failed")
            + (t("pkexec_detail", detail=stderr.splitlines()[0]) if stderr else "")
        )
    if method == "explicit" and result.returncode in (126, 127):
        log_action(normalized, "ABGEBROCHEN")
        raise AdminError(t("auth_cancelled"))
    if result.returncode != 0:
        message = (result.stderr or stdout or t("op_failed")).strip()
        log_action(normalized, "FEHLER", message)
        raise AdminError(message)
    log_action(normalized)
    return stdout.strip()


def admin(cmd, args, input_text=None):
    return admin_batch([(cmd, args, input_text)])


def log_action(jobs, status="OK", detail=""):
    """Schreibt Befehle (ohne Passwörter) in das Aktionsprotokoll."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            for job in jobs:
                line = f"{stamp}  {status:<10} {job['cmd']} {' '.join(job['args'])}"
                fh.write(line + "\n")
            if detail:
                first_line = detail.strip().splitlines()[0][:160] if detail.strip() else ""
                if first_line:
                    fh.write(f"{stamp}  {'':<10} -> {first_line}\n")
    except OSError:
        pass  # Protokoll ist optional


def read_log(max_lines=500):
    """Letzte Zeilen des Aktionsprotokolls (leer, wenn es noch keins gibt)."""
    try:
        with open(LOG_FILE, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    return "".join(lines[-max_lines:])


# --------------------------------------------------------------------------
# Konkrete Aktionen
# --------------------------------------------------------------------------
def create_user(name, password=None, uid=None, comment=None, shell=None):
    name = validate_name(name, "lab_user")
    if name in [u.pw_name for u in pwd.getpwall()]:
        raise ValueError(t("user_exists", name=name))
    shells = list_shells()
    if shell in (None, ""):
        shell = "/bin/bash" if "/bin/bash" in shells or not shells else shells[0]
    elif shell not in shells:
        raise ValueError(t("shell_not_listed", shell=shell))
    args = ["-m", "-s", shell]
    if uid not in (None, ""):
        args += ["-u", str(validate_uid(uid))]
    comment = validate_comment(comment)
    if comment:
        args += ["-c", comment]
    jobs = [("useradd", args + ["--", name])]
    if password:
        jobs.append(("chpasswd", [], f"{name}:{password}\n"))
    admin_batch(jobs)


def rename_user(old, new, current_user, rename_home=True, rename_group=True):
    """Benennt einen Benutzer um (optional Home-Ordner und Privatgruppe).

    Gibt eine Liste von Hinweisen zurück, was zusätzlich getan/übersprungen wurde.
    """
    old = ensure_plain_identifier(old, "lab_user")
    new = validate_name(new, "lab_newuser")
    if old == current_user:
        raise ValueError(t("cant_rename_self"))
    if old not in [u.pw_name for u in pwd.getpwall()]:
        raise ValueError(t("user_missing", name=old))
    if new in [u.pw_name for u in pwd.getpwall()]:
        raise ValueError(t("user_exists", name=new))

    entry = pwd.getpwnam(old)
    notes = []
    usermod_args = ["-l", new]
    if rename_home:
        if entry.pw_dir == f"/home/{old}":
            new_home = f"/home/{new}"
            if os.path.exists(new_home):
                raise ValueError(t("home_exists", path=new_home))
            usermod_args += ["-d", new_home, "-m"]
            notes.append(t("note_home", old=entry.pw_dir, new=new_home))
        else:
            notes.append(t("note_home_skip", path=entry.pw_dir, user=old))

    jobs = [("usermod", usermod_args + ["--", old])]
    if rename_group and primary_group(old) == old:
        if new in list_groups():
            raise ValueError(t("group_clash", name=new))
        jobs.append(("groupmod", ["-n", new, "--", old]))
        notes.append(t("note_group", old=old, new=new))
    admin_batch(jobs)
    notes.append(t("note_manual"))
    return notes


def aging_info(name):
    """Passwort-Ablaufdaten (chage -l, braucht root)."""
    ensure_plain_identifier(name, "lab_user")
    return admin("chage", ["-l", "--", name])


def set_password_aging(name, max_days=None, min_days=None, warn_days=None,
                       expire=None, force_change=False):
    ensure_plain_identifier(name, "lab_user")
    args = aging_args(max_days, min_days, warn_days, expire, force_change)
    admin("chage", args + ["--", name])


def delete_user(name, current_user):
    name = ensure_plain_identifier(name, "lab_user")
    if name == current_user:
        raise ValueError(t("cant_delete_self"))
    admin("userdel", ["-r", "--", name])


def set_password(name, password):
    ensure_plain_identifier(name, "lab_user")
    admin("chpasswd", [], f"{name}:{password}\n")


def create_group(name):
    name = validate_name(name, "lab_group")
    if name in list_groups():
        raise ValueError(t("group_exists", name=name))
    admin("groupadd", ["--", name])


def delete_group(name):
    ensure_plain_identifier(name, "lab_group")
    if is_system_group(name):
        raise ValueError(t("system_group", name=name, low=gid_range()[0], high=gid_range()[1]))
    admin("groupdel", ["--", name])


def add_user_to_group(user, group):
    ensure_plain_identifier(user, "lab_user")
    ensure_plain_identifier(group, "lab_group")
    admin("usermod", ["-aG", group, "--", user])


def remove_user_from_group(user, group):
    ensure_plain_identifier(user, "lab_user")
    ensure_plain_identifier(group, "lab_group")
    if group == primary_group(user):
        raise ValueError(t("primary_remove", group=group, user=user))
    admin("gpasswd", ["-d", user, group])


def create_group_folder(path, group, owner):
    """Legt /srv/... an, setzt Besitzer:Gruppe und 2770 – ein einziger pkexec."""
    real = safe_srv_path(path)
    ensure_plain_identifier(group, "lab_group")
    ensure_plain_identifier(owner, "lab_owner")
    if os.path.exists(real) and not os.path.isdir(real):
        raise ValueError(t("path_notdir"))
    admin_batch([
        ("mkdir", ["-p", "--", real]),
        ("chown", [f"{owner}:{group}", "--", real]),
        ("chmod", [chmod_arg(0o2770), "--", real]),
    ])
    return real


def apply_owner_group_mode(path, owner, group, mode):
    ensure_plain_identifier(group, "lab_group")
    jobs = []
    if owner:
        ensure_plain_identifier(owner, "lab_owner")
        jobs.append(("chown", [f"{owner}:{group}", "--", path]))
    else:
        jobs.append(("chown", [f":{group}", "--", path]))
    if mode is not None:
        jobs.append(("chmod", [chmod_arg(mode), "--", path]))
    admin_batch(jobs)


def lock_user(name, current_user):
    ensure_plain_identifier(name, "lab_user")
    if name == current_user:
        raise ValueError(t("cant_lock_self"))
    admin("usermod", ["-L", "--", name])


def unlock_user(name):
    ensure_plain_identifier(name, "lab_user")
    admin("usermod", ["-U", "--", name])


def account_status(name):
    """Kontostatus (braucht root, daher per pkexec). Gibt lesbaren Text zurück."""
    ensure_plain_identifier(name, "lab_user")
    fields = admin("passwd", ["-S", "--", name]).split()
    state = fields[1] if len(fields) > 1 else "?"
    meaning = {
        "P": t("acct_P"),
        "L": t("acct_L"),
        "NP": t("acct_NP"),
    }.get(state) or t("acct_other", state=state)
    return f"{name}: {meaning}"


def list_shells():
    """Gültige Login-Shells aus /etc/shells."""
    shells = []
    try:
        with open("/etc/shells", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("/") and os.path.exists(line) and line not in shells:
                    shells.append(line)
    except OSError:
        pass
    return shells


def set_shell(name, shell):
    ensure_plain_identifier(name, "lab_user")
    if shell not in list_shells():
        raise ValueError(t("shell_not_listed", shell=shell))
    admin("usermod", ["-s", shell, "--", name])


def set_primary_group(name, group):
    ensure_plain_identifier(name, "lab_user")
    ensure_plain_identifier(group, "lab_group")
    if group not in list_groups():
        raise ValueError(t("group_missing", name=group))
    admin("usermod", ["-g", group, "--", name])


# ---- ACL -----------------------------------------------------------------
def _acl_subject(kind, name):
    if kind not in ("g", "u"):
        raise ValueError(t("acl_kind"))
    ensure_plain_identifier(name, "Gruppenname" if kind == "g" else "lab_user")
    return kind, name


def acl_apply(path, name, perms, inherit=False, recursive=False, kind="g"):
    """Setzt eine Gruppen- oder Benutzer-ACL, optional zusätzlich als Standard-ACL.

    Die ACL-Maske wird bewusst NICHT manuell gesetzt, sondern von setfacl
    berechnet – so verlieren andere ACL-Einträge nie still ihre Rechte.
    """
    kind, name = _acl_subject(kind, name)
    entry = f"{kind}:{name}:{perms}"
    if inherit:
        if not os.path.isdir(path):
            raise ValueError(t("acl_dir_only"))
        entry += f",d:{kind}:{name}:{perms}"
    args = ["-m", entry]
    if recursive:
        args.insert(0, "-R")
    admin("setfacl", args + ["--", path])


def acl_remove_entry(path, name, recursive=False, kind="g"):
    kind, name = _acl_subject(kind, name)
    args = ["-x", f"{kind}:{name},d:{kind}:{name}"]
    if recursive:
        args.insert(0, "-R")
    admin("setfacl", args + ["--", path])


def acl_remove_group(path, group, recursive=False):
    acl_remove_entry(path, group, recursive, kind="g")


def acl_remove_all(path, recursive=False):
    args = ["-b"]
    if recursive:
        args.insert(0, "-R")
    admin("setfacl", args + ["--", path])


def acl_read(path):
    """getfacl braucht normalerweise kein root – erst ohne pkexec versuchen."""
    program = find_program("getfacl")
    result = subprocess.run(
        [program, "-p", "--", path], text=True, capture_output=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    message = (result.stderr or "").lower()
    if "permission denied" in message or "keine berechtigung" in message:
        return admin("getfacl", ["-p", "--", path])
    raise AdminError((result.stderr or t("getfacl_failed")).strip())
