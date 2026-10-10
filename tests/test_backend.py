import os
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backend  # noqa: E402


# ---------------------------------------------------------------- Namen ----
@pytest.mark.parametrize("name", ["anna", "_svc", "team-1", "a_b", "x" * 32])
def test_valid_names(name):
    assert backend.validate_name(name) == name


@pytest.mark.parametrize(
    "name", ["-D", "--help", "-rf", "Anna", "ärger", "a b", "a:b", "", "1abc", "x" * 33, "a\nb"]
)
def test_invalid_names(name):
    with pytest.raises(ValueError):
        backend.validate_name(name)


@pytest.mark.parametrize("name", ["-x", "", "a:b", "a\nb"])
def test_plain_identifier_rejects(name):
    with pytest.raises(ValueError):
        backend.ensure_plain_identifier(name)


# ---------------------------------------------------------------- Modus ----
def test_parse_mode_ok():
    assert backend.parse_mode("770") == 0o770
    assert backend.parse_mode("2770") == 0o2770


@pytest.mark.parametrize("text", ["", "77", "889", "77777", "abc", "7 70"])
def test_parse_mode_bad(text):
    with pytest.raises(ValueError):
        backend.parse_mode(text)


def test_chmod_arg_and_format():
    assert backend.chmod_arg(0o770) == "00770"
    assert backend.chmod_arg(0o2770) == "02770"
    assert backend.format_octal(0o770) == "770"
    assert backend.format_octal(0o2770) == "2770"


def test_chmod_five_digits_really_clears_sgid(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    subprocess.run(["chmod", backend.chmod_arg(0o2770), str(d)], check=True)
    assert os.stat(d).st_mode & stat.S_ISGID
    subprocess.run(["chmod", backend.chmod_arg(0o770), str(d)], check=True)
    assert not os.stat(d).st_mode & stat.S_ISGID


def test_perms_string():
    assert backend.perms_string(True, False, True) == "rx"
    with pytest.raises(ValueError):
        backend.perms_string(False, False, False)


# ------------------------------------------------------------- /srv-Pfad ----
@pytest.fixture
def fake_srv(tmp_path, monkeypatch):
    srv = tmp_path / "srv"
    srv.mkdir()
    monkeypatch.setattr(backend, "SRV_ROOT", str(srv))
    return srv


def test_srv_path_ok(fake_srv):
    assert backend.safe_srv_path(f"{fake_srv}/team") == f"{fake_srv}/team"
    assert backend.safe_srv_path(f"{fake_srv}/a/b/c")


@pytest.mark.parametrize("suffix", ["", "/", "/../etc", "/team/../../etc", "/.."])
def test_srv_path_rejects(fake_srv, suffix):
    with pytest.raises(ValueError):
        backend.safe_srv_path(f"{fake_srv}{suffix}")


def test_srv_path_rejects_relative_and_other(fake_srv):
    with pytest.raises(ValueError):
        backend.safe_srv_path("srv/team")
    with pytest.raises(ValueError):
        backend.safe_srv_path("/etc")


def test_srv_path_rejects_symlink_escape(fake_srv, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (fake_srv / "link").symlink_to(outside)
    with pytest.raises(ValueError):
        backend.safe_srv_path(f"{fake_srv}/link/x")


def test_real_srv_prefix_is_not_confused(monkeypatch, tmp_path):
    # '/srvx' darf nicht als Unterordner von '/srv' durchgehen
    srv = tmp_path / "srv"
    srv.mkdir()
    (tmp_path / "srvx").mkdir()
    monkeypatch.setattr(backend, "SRV_ROOT", str(srv))
    with pytest.raises(ValueError):
        backend.safe_srv_path(f"{tmp_path}/srvx/team")


# --------------------------------- admin_batch ohne pkexec (als aktueller User)
@pytest.fixture
def no_pkexec(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "ADMIN_PREFIX", [])
    monkeypatch.setattr(backend, "LOG_FILE", str(tmp_path / "log" / "actions.log"))


def test_batch_runs_in_order_and_logs(no_pkexec, tmp_path):
    target = tmp_path / "x"
    backend.admin_batch([
        ("mkdir", ["-p", "--", str(target)]),
        ("chmod", ["00750", "--", str(target)]),
    ])
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o750
    log = (tmp_path / "log" / "actions.log").read_text()
    assert "mkdir" in log and "chmod" in log


def test_batch_stops_on_first_error(no_pkexec, tmp_path):
    later = tmp_path / "later"
    with pytest.raises(backend.AdminError):
        backend.admin_batch([
            ("chmod", ["00750", "--", str(tmp_path / "gibt-es-nicht")]),
            ("mkdir", ["--", str(later)]),
        ])
    assert not later.exists()


def test_batch_rejects_unknown_command(no_pkexec):
    with pytest.raises(backend.AdminError):
        backend.admin_batch([("rm", ["-rf", "/"])])


def test_password_not_in_log(no_pkexec, tmp_path, monkeypatch):
    # chpasswd würde root brauchen; wir prüfen nur das Logging-Format
    backend.log_action([{"cmd": "chpasswd", "args": [], "input": "u:geheim\n"}])
    log = (tmp_path / "log" / "actions.log").read_text()
    assert "geheim" not in log


# ----------------------------------------------------------------- ACLs ----
@pytest.mark.skipif(not backend.shutil.which("setfacl"), reason="acl nicht installiert")
class TestAcl:
    def test_inherit_sets_access_and_default(self, no_pkexec, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        backend.acl_apply(str(d), "daemon", "rwx", inherit=True)
        out = backend.acl_read(str(d))
        assert "group:daemon:rwx" in out
        assert "default:group:daemon:rwx" in out

    def test_mask_is_not_reduced(self, no_pkexec, tmp_path):
        """Regression: v10 setzte die Maske auf die gewählten Rechte."""
        d = tmp_path / "d"
        d.mkdir()
        os.chmod(d, 0o770)
        backend.acl_apply(str(d), "daemon", "r", inherit=True)
        out = backend.acl_read(str(d))
        assert "group::rwx" in out
        assert "mask::rwx" in out  # unverändert, owning group behält 'w'

    def test_default_acl_on_file_rejected(self, tmp_path):
        f = tmp_path / "f"
        f.write_text("x")
        with pytest.raises(ValueError):
            backend.acl_apply(str(f), "daemon", "r", inherit=True)

    def test_remove_group(self, no_pkexec, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        backend.acl_apply(str(d), "daemon", "rwx", inherit=True)
        backend.acl_remove_group(str(d), "daemon")
        assert "daemon" not in backend.acl_read(str(d))

    def test_remove_all(self, no_pkexec, tmp_path):
        d = tmp_path / "d"
        d.mkdir()
        backend.acl_apply(str(d), "daemon", "rwx", inherit=True)
        backend.acl_remove_all(str(d))
        out = backend.acl_read(str(d))
        assert "daemon" not in out and "default:" not in out

    def test_recursive_reaches_existing_files(self, no_pkexec, tmp_path):
        d = tmp_path / "d"
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "f").write_text("x")
        backend.acl_apply(str(d), "daemon", "r", inherit=True, recursive=True)
        assert "group:daemon:r--" in backend.acl_read(str(d / "sub" / "f"))


# ------------------------------------------------------- Gruppen / Benutzer ----
def test_system_group_detection():
    assert backend.is_system_group("root") is True
    assert backend.is_system_group("gibt-es-sicher-nicht") is False


def test_delete_system_group_refused():
    with pytest.raises(ValueError):
        backend.delete_group("root")


def test_cannot_delete_current_user():
    with pytest.raises(ValueError):
        backend.delete_user("anna", "anna")


def test_create_user_rejects_option_injection():
    with pytest.raises(ValueError):
        backend.create_user("-D")


def test_group_folder_rejects_traversal(fake_srv):
    with pytest.raises(ValueError):
        backend.create_group_folder(f"{fake_srv}/../etc", "root", "root")
    with pytest.raises(ValueError):
        backend.create_group_folder(f"{fake_srv}/", "root", "root")


def test_group_members_includes_primary():
    members = backend.group_members("root")
    assert "root" in members


# ----------------------------------------------------- Benutzer-ACLs (neu) ----
@pytest.mark.skipif(not backend.shutil.which("setfacl"), reason="acl nicht installiert")
def test_user_acl_roundtrip(no_pkexec, tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    backend.acl_apply(str(d), "daemon", "rx", inherit=True, kind="u")
    out = backend.acl_read(str(d))
    assert "user:daemon:r-x" in out and "default:user:daemon:r-x" in out
    backend.acl_remove_entry(str(d), "daemon", kind="u")
    assert "daemon" not in backend.acl_read(str(d))


def test_acl_rejects_bad_kind_and_name(tmp_path):
    with pytest.raises(ValueError):
        backend.acl_apply(str(tmp_path), "daemon", "r", kind="x")
    with pytest.raises(ValueError):
        backend.acl_apply(str(tmp_path), "-evil", "r", kind="u")


def test_lock_current_user_refused():
    with pytest.raises(ValueError):
        backend.lock_user("anna", "anna")


def test_set_shell_rejects_unknown_shell():
    with pytest.raises(ValueError):
        backend.set_shell("anna", "/tmp/evil")


def test_list_shells_only_existing():
    shells = backend.list_shells()
    assert shells and all(os.path.exists(s) for s in shells)


# ------------------------- Integration: echte Befehle (nur als root, z. B. Container)
needs_root = pytest.mark.skipif(
    os.geteuid() != 0 or not backend.shutil.which("useradd"),
    reason="braucht root und useradd",
)


@pytest.fixture
def temp_account(no_pkexec):
    user, group = "tgui_user", "tgui_group"
    yield user, group
    subprocess.run(["userdel", "-r", user], capture_output=True)
    # nach set_primary_group bleibt die ursprüngliche Privatgruppe des Benutzers übrig
    subprocess.run(["groupdel", user], capture_output=True)
    subprocess.run(["groupdel", group], capture_output=True)


@needs_root
def test_integration_user_group_lifecycle(temp_account):
    user, group = temp_account
    backend.create_user(user, "Pa55:wort")
    assert user in backend.list_users()

    backend.create_group(group)
    backend.add_user_to_group(user, group)
    assert group in backend.supplementary_groups(user)
    assert user in backend.group_members(group)

    # Primärgruppe darf nicht "entfernt" werden
    with pytest.raises(ValueError):
        backend.remove_user_from_group(user, backend.primary_group(user))

    backend.remove_user_from_group(user, group)
    assert group not in backend.supplementary_groups(user)

    backend.set_primary_group(user, group)
    assert backend.primary_group(user) == group

    backend.set_shell(user, "/bin/sh")
    assert backend.pwd.getpwnam(user).pw_shell == "/bin/sh"

    backend.lock_user(user, "someone-else")
    assert "gesperrt" in backend.account_status(user)
    backend.unlock_user(user)
    assert "gesperrt" not in backend.account_status(user)

    backend.set_password(user, "NeuesPasswort1")
    # Gruppe ist noch Primärgruppe -> Löschen muss sauber fehlschlagen
    with pytest.raises(backend.AdminError):
        backend.delete_group(group)

    backend.delete_user(user, "someone-else")
    assert user not in backend.list_users()
    backend.delete_group(group)
    assert group not in backend.list_groups()


@needs_root
def test_integration_duplicate_user_rejected(temp_account):
    user, _ = temp_account
    backend.create_user(user)
    with pytest.raises(ValueError):
        backend.create_user(user)


@needs_root
def test_integration_group_folder(no_pkexec, tmp_path, monkeypatch):
    srv = tmp_path / "srv"
    srv.mkdir()
    monkeypatch.setattr(backend, "SRV_ROOT", str(srv))
    real = backend.create_group_folder(f"{srv}/team", "daemon", "root")
    st = os.stat(real)
    assert stat.S_IMODE(st.st_mode) == 0o2770
    assert backend.owner_group_of(real)[:2] == ("root", "daemon")


# ================================================================ v13 ======
# ---- UID / Kommentar / chage-Argumente (rein logisch) -----------------------
def test_validate_uid():
    assert backend.validate_uid("4242") == 4242
    for bad in ("abc", "", "0", "999", "70000", "-5"):
        with pytest.raises(ValueError):
            backend.validate_uid(bad)


def test_validate_uid_rejects_taken(monkeypatch):
    class Fake:  # ein belegter UID im erlaubten Bereich
        pw_uid = 4243
        pw_name = "x"
    monkeypatch.setattr(backend.pwd, "getpwall", lambda: [Fake()])
    with pytest.raises(ValueError):
        backend.validate_uid("4243")


@pytest.mark.parametrize("text", ["a:b", "zeile1\nzeile2", "x" * 101, "tab\there"])
def test_validate_comment_rejects(text):
    with pytest.raises(ValueError):
        backend.validate_comment(text)


def test_validate_comment_ok():
    assert backend.validate_comment("  Anna Müller, Büro 3 ") == "Anna Müller, Büro 3"
    assert backend.validate_comment(None) == ""


def test_aging_args():
    assert backend.aging_args(max_days="90") == ["-M", "90"]
    assert backend.aging_args(max_days=-1) == ["-M", "-1"]
    assert backend.aging_args("90", "1", "7", "2027-12-31", True) == [
        "-M", "90", "-m", "1", "-W", "7", "-E", "2027-12-31", "-d", "0"]
    assert backend.aging_args(expire="nie") == ["-E", "-1"]


@pytest.mark.parametrize("kwargs", [
    {}, {"max_days": "abc"}, {"max_days": "100000"}, {"min_days": "-1"},
    {"warn_days": "x"}, {"expire": "31.12.2027"}, {"expire": "2027-13-40"},
])
def test_aging_args_rejects(kwargs):
    with pytest.raises(ValueError):
        backend.aging_args(**kwargs)


def test_rename_guards():
    with pytest.raises(ValueError):
        backend.rename_user("anna", "bert", "anna")        # eigener Benutzer
    with pytest.raises(ValueError):
        backend.rename_user("root", "-D", "anna")          # ungültiger Name
    with pytest.raises(ValueError):
        backend.rename_user("gibt-es-nicht", "neu", "anna")


# ---- Protokoll --------------------------------------------------------------
def test_log_records_failure_and_hides_password(no_pkexec, tmp_path):
    with pytest.raises(backend.AdminError):
        backend.admin_batch([("chmod", ["00750", "--", str(tmp_path / "nope")])])
    backend.log_action([{"cmd": "chpasswd", "args": [], "input": "u:geheim\n"}])
    text = backend.read_log()
    assert "FEHLER" in text and "chmod" in text and "->" in text
    assert "geheim" not in text


def test_read_log_tail_and_missing(no_pkexec, tmp_path):
    assert backend.read_log() == ""
    for i in range(10):
        backend.log_action([{"cmd": "mkdir", "args": [str(i)], "input": None}])
    lines = backend.read_log(max_lines=3).splitlines()
    assert len(lines) == 3 and lines[-1].endswith("mkdir 9")


# ---- Integration (echte Befehle, nur als root) -------------------------------
@pytest.fixture
def temp_names(no_pkexec):
    names = ["tgui_a", "tgui_b"]
    yield names
    for n in names:                      # erst alle Benutzer, dann alle Gruppen
        subprocess.run(["userdel", "-r", n], capture_output=True)
    for n in names:
        subprocess.run(["groupdel", n], capture_output=True)


@needs_root
def test_integration_create_with_uid_comment_shell(temp_names):
    user = temp_names[0]
    backend.create_user(user, None, uid="4242", comment="Test Konto, Raum 7", shell="/bin/sh")
    entry = backend.pwd.getpwnam(user)
    assert entry.pw_uid == 4242
    assert entry.pw_gecos.startswith("Test Konto, Raum 7")
    assert entry.pw_shell == "/bin/sh"
    with pytest.raises(ValueError):          # UID jetzt vergeben
        backend.create_user(temp_names[1], None, uid="4242")


@needs_root
def test_integration_rename_user_home_and_group(temp_names):
    old, new = temp_names
    backend.create_user(old)
    notes = backend.rename_user(old, new, "someone-else")
    assert old not in [u.pw_name for u in backend.pwd.getpwall()]
    entry = backend.pwd.getpwnam(new)
    assert entry.pw_dir == f"/home/{new}" and os.path.isdir(entry.pw_dir)
    assert not os.path.exists(f"/home/{old}")
    assert backend.primary_group(new) == new
    assert any("Home-Verzeichnis" in n for n in notes) and any("Privatgruppe" in n for n in notes)


@needs_root
def test_integration_rename_without_home_and_group(temp_names):
    old, new = temp_names
    backend.create_user(old)
    backend.rename_user(old, new, "someone-else", rename_home=False, rename_group=False)
    assert backend.pwd.getpwnam(new).pw_dir == f"/home/{old}"
    assert backend.primary_group(new) == old       # Gruppe blieb alt
    subprocess.run(["rm", "-rf", f"/home/{old}"])


@needs_root
def test_integration_rename_group_clash_refused(temp_names):
    old, new = temp_names
    backend.create_user(old)
    backend.create_group(new)
    with pytest.raises(ValueError):
        backend.rename_user(old, new, "someone-else")


@needs_root
def test_integration_password_aging(temp_names):
    user = temp_names[0]
    backend.create_user(user, "Pa55wort")
    backend.set_password_aging(user, max_days="90", min_days="1", warn_days="7", expire="2037-12-31")
    info = backend.aging_info(user)
    assert "90" in info and "7" in info
    assert "Dec 31, 2037" in info or "2037" in info
    backend.set_password_aging(user, expire="nie", force_change=True)
    after = backend.aging_info(user)
    assert "never" in after.lower() or "nie" in after.lower()
    with pytest.raises(ValueError):
        backend.set_password_aging(user)           # keine Änderung angegeben


# ---- Systemgruppen-Bereich (nogroup mit GID 65534 zählt als Systemgruppe) -----
@pytest.mark.skipif(not any(g.gr_gid > 60000 for g in backend.grp.getgrall()),
                    reason="keine Gruppe oberhalb GID_MAX vorhanden")
def test_high_gid_group_counts_as_system():
    high = [g.gr_name for g in backend.grp.getgrall() if g.gr_gid > 60000][0]
    assert backend.is_system_group(high) is True
    assert high not in backend.list_groups(include_system=False)
    with pytest.raises(ValueError):
        backend.delete_group(high)


def test_gid_range_default():
    low, high = backend.gid_range()
    assert low <= 1000 and high >= low


# ================================================================ v13.2 ====
# ---- Rechte-Methode (pkexec / sudo / direkt) --------------------------------
def _as_user(monkeypatch, euid=1000, ssh=False, tools=("sudo", "pkexec"), method="auto"):
    monkeypatch.setattr(backend.os, "geteuid", lambda: euid)
    monkeypatch.setattr(backend, "PRIVILEGE_METHOD", method)
    monkeypatch.setattr(backend.shutil, "which", lambda n, path=None: f"/usr/bin/{n}" if n in tools else None)
    for var in ("SSH_CONNECTION", "SSH_TTY"):
        monkeypatch.delenv(var, raising=False)
    if ssh:
        monkeypatch.setenv("SSH_CONNECTION", "10.0.0.2 5555 10.0.0.1 22")


def test_method_root_is_direct(monkeypatch):
    _as_user(monkeypatch, euid=0)
    assert backend.privilege_method() == "direct"


def test_method_auto_local_prefers_pkexec(monkeypatch):
    _as_user(monkeypatch)
    assert backend.privilege_method() == "pkexec"


def test_method_auto_ssh_prefers_sudo(monkeypatch):
    _as_user(monkeypatch, ssh=True)
    assert backend.privilege_method() == "sudo"


def test_method_ssh_without_sudo_falls_back_to_pkexec(monkeypatch):
    _as_user(monkeypatch, ssh=True, tools=("pkexec",))
    assert backend.privilege_method() == "pkexec"


def test_method_explicit_override(monkeypatch):
    _as_user(monkeypatch, ssh=True, method="pkexec")
    assert backend.privilege_method() == "pkexec"
    _as_user(monkeypatch, method="sudo")
    assert backend.privilege_method() == "sudo"


# ---- sudo-Ablauf mit simuliertem subprocess.run -----------------------------
class FakeRun:
    """Simuliert sudo: erst 'sudo -n true' (braucht Passwort), dann den eigentlichen Aufruf."""
    def __init__(self, password="richtig", nopasswd=False, sudoers_ok=True):
        self.password, self.nopasswd, self.sudoers_ok = password, nopasswd, sudoers_ok
        self.calls = []

    def __call__(self, command, input=None, **kwargs):
        self.calls.append((command, input))
        R = subprocess.CompletedProcess
        if command[1:] == ["-n", "true"]:
            return R(command, 0 if self.nopasswd else 1, "", "sudo: a password is required")
        if not self.sudoers_ok:
            return R(command, 1, "", "sudo: tester is not in the sudoers file.")
        if not self.nopasswd:
            first = (input or "").split("\n", 1)[0]
            if first != self.password:
                return R(command, 1, "", "sudo: 3 incorrect password attempts")
        return R(command, 0, backend._MARKER + "ok", "")


@pytest.fixture
def sudo_env(monkeypatch, tmp_path):
    _as_user(monkeypatch, method="sudo")
    monkeypatch.setattr(backend, "ADMIN_PREFIX", None)
    monkeypatch.setattr(backend, "LOG_FILE", str(tmp_path / "actions.log"))
    monkeypatch.setattr(backend, "find_program", lambda n: f"/usr/bin/{n}")
    backend.clear_sudo_password()
    yield monkeypatch
    backend.clear_sudo_password()


def test_sudo_asks_for_password_first(sudo_env):
    sudo_env.setattr(backend.subprocess, "run", FakeRun())
    with pytest.raises(backend.PasswordRequired):
        backend.admin("mkdir", ["-p", "--", "/x"])


def test_sudo_wrong_password(sudo_env):
    sudo_env.setattr(backend.subprocess, "run", FakeRun())
    backend.set_sudo_password("falsch")
    with pytest.raises(backend.WrongPassword):
        backend.admin("mkdir", ["-p", "--", "/x"])


def test_sudo_correct_password_feeds_stdin_not_cmdline(sudo_env):
    fake = FakeRun()
    sudo_env.setattr(backend.subprocess, "run", fake)
    backend.set_sudo_password("richtig")
    assert backend.admin("mkdir", ["-p", "--", "/x"]) == "ok"
    command, stdin = fake.calls[-1]
    assert "richtig" not in " ".join(command)           # nie in der Prozessliste
    assert stdin.startswith("richtig\n")                # sondern über stdin
    assert command[:5] == ["/usr/bin/sudo", "-k", "-S", "-p", ""]


def test_sudo_nopasswd_needs_no_password(sudo_env):
    fake = FakeRun(nopasswd=True)
    sudo_env.setattr(backend.subprocess, "run", fake)
    assert backend.admin("mkdir", ["-p", "--", "/x"]) == "ok"
    command, stdin = fake.calls[-1]
    assert command[0] == "/usr/bin/sudo" and "-S" not in command and stdin.startswith("[")


def test_sudo_not_in_sudoers_is_plain_error(sudo_env):
    sudo_env.setattr(backend.subprocess, "run", FakeRun(sudoers_ok=False))
    backend.set_sudo_password("egal")
    with pytest.raises(backend.AdminError) as err:
        backend.admin("mkdir", ["-p", "--", "/x"])
    assert not isinstance(err.value, backend.WrongPassword)
    assert "sudoers" in str(err.value).lower()


def test_sudo_command_failure_is_not_auth_error(sudo_env):
    """Schlägt der Befehl selbst fehl (Hilfsprogramm lief), ist es kein Passwortproblem."""
    def run(command, input=None, **kw):
        R = subprocess.CompletedProcess
        if command[1:] == ["-n", "true"]:
            return R(command, 0, "", "")
        return R(command, 1, backend._MARKER, "useradd: user 'x' already exists")
    sudo_env.setattr(backend.subprocess, "run", run)
    with pytest.raises(backend.AdminError) as err:
        backend.admin("useradd", ["--", "x"])
    assert not isinstance(err.value, (backend.WrongPassword, backend.PasswordRequired))
    assert "already exists" in str(err.value)


def test_pkexec_failure_mentions_ssh_and_sudo(monkeypatch, tmp_path):
    _as_user(monkeypatch, method="pkexec")
    monkeypatch.setattr(backend, "ADMIN_PREFIX", None)
    monkeypatch.setattr(backend, "LOG_FILE", str(tmp_path / "a.log"))
    monkeypatch.setattr(backend, "find_program", lambda n: f"/usr/bin/{n}")
    monkeypatch.setattr(backend.subprocess, "run", lambda c, **k: subprocess.CompletedProcess(
        c, 127, "", "Error executing command as another user: Not authorized"))
    with pytest.raises(backend.AdminError) as err:
        backend.admin("mkdir", ["--", "/x"])
    assert "SSH" in str(err.value) and "sudo" in str(err.value) and "Not authorized" in str(err.value)


# ---- Echtes sudo im Container (nur root, sudo installiert) -------------------
@pytest.mark.skipif(os.geteuid() != 0 or not backend.shutil.which("sudo")
                    or not backend.shutil.which("runuser"), reason="braucht root, sudo, runuser")
def test_integration_real_sudo_as_normal_user():
    import pathlib, tempfile
    user, target = "tgui_sudo", "/opt/tgui_sudo_made"
    tmp_path = pathlib.Path(tempfile.mkdtemp())
    os.chmod(tmp_path, 0o755)                 # der Testbenutzer muss das Skript lesen dürfen
    code = tmp_path / "code"
    code.mkdir()
    for module in ("backend.py", "i18n.py"):
        subprocess.run(["cp", os.path.join(os.path.dirname(__file__), "..", module), str(code)], check=True)
        os.chmod(code / module, 0o644)
    os.chmod(code, 0o755)
    script = tmp_path / "run.py"
    script.write_text(f'''
import sys, os
sys.dont_write_bytecode = True
sys.path.insert(0, "{code}")
import backend as be
be.PRIVILEGE_METHOD = "sudo"
print("method:", be.privilege_method())
try:
    be.admin("mkdir", ["-p", "--", "{target}"])
except be.PasswordRequired:
    print("PasswordRequired")
be.set_sudo_password("falsches-passwort")
try:
    be.admin("mkdir", ["-p", "--", "{target}"])
except be.WrongPassword:
    print("WrongPassword")
be.set_sudo_password("Secret-1234")
be.admin("mkdir", ["-p", "--", "{target}"])
print("created:", os.path.isdir("{target}"))
''')
    os.chmod(script, 0o644)
    sudoers = f"/etc/sudoers.d/{user}"
    try:
        subprocess.run(["useradd", "-m", user], check=True)
        subprocess.run(["chpasswd"], input=f"{user}:Secret-1234\n", text=True, check=True)
        with open(sudoers, "w") as fh:
            fh.write(f"{user} ALL=(ALL) ALL\n")
        os.chmod(sudoers, 0o440)
        env = {"PATH": os.environ["PATH"], "HOME": f"/home/{user}"}
        r = subprocess.run(["runuser", "-u", user, "--", backend.sys.executable, str(script)],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        assert lines == ["method: sudo", "PasswordRequired", "WrongPassword", "created: True"], r.stdout
        st = os.stat(target)
        assert st.st_uid == 0                          # wirklich als root angelegt
    finally:
        subprocess.run(["rm", "-rf", target, sudoers, str(tmp_path)])
        subprocess.run(["userdel", "-r", user], capture_output=True)
        subprocess.run(["groupdel", user], capture_output=True)
