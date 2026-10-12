# Linux Admin GUI

**Deutsch** · [English](#english)

Grafische Verwaltung von Benutzern, Gruppen, Dateirechten und ACLs für Linux (Python/Tkinter).
© 2026 Eugen Becker. Alle Rechte vorbehalten.

## Installation aus GitHub (apt-basierte Systeme: Debian, Ubuntu, Mint)

    sudo apt install git
    git clone https://github.com/beckereugen04-coder/linux-admin-gui.git
    cd linux-admin-gui
    ./install.sh        # installiert python3-tk, acl und pkexec/policykit-1
    ./install_app.sh    # kopiert nach /opt/linux-admin-gui und legt einen Menüeintrag an

Starten: Menüeintrag „Linux Admin GUI“ oder `python3 /opt/linux-admin-gui/main.py`.
Ohne Installation direkt aus dem Ordner: `./start.sh`.
Aktualisieren: `git pull && ./install_app.sh` · Entfernen: `./uninstall.sh`.

Auf anderen Distributionen die Pakete von Hand installieren: Python 3, Tkinter, `acl`, `pkexec` (Polkit) oder `sudo`.

Falls die Skripte nicht ausführbar sind (z. B. nach einem Upload von Windows): `chmod +x *.sh` oder mit `bash install.sh` starten.
Die App selbst läuft nur unter Linux.

## Funktionen
- Benutzer: erstellen (Vollname, UID, Shell), löschen, umbenennen, sperren/entsperren, Passwort, Passwort-Ablauf, Shell, Primärgruppe, Gruppen
- Gruppen: erstellen, löschen (nur normale Gruppen), Mitglieder, Gruppenordner unter /srv (2770, SGID)
- Rechte: Besitzer/Gruppe/chmod inkl. SUID/SGID/Sticky
- ACL: für Gruppen und Benutzer setzen, vererben, rekursiv, Einträge oder alle ACLs entfernen
- Protokoll: Erfolge, Fehler, Abbrüche (`~/.local/state/linux-admin-gui/actions.log`, ohne Passwörter)
- Oberfläche: Seitenleiste, Aufklappmenüs, Suche, Deutsch/English, helles/dunkles Design (Einstellungen oben rechts)

Die Oberfläche läuft als normaler Benutzer; privilegierte Aktionen laufen gebündelt über `pkexec` oder `sudo`
(ein Passwortdialog pro Aktion). Über SSH wählt die Automatik `sudo` (Passwort im Anwendungsfenster):

    ssh -X benutzer@server
    ./start.sh

Dauerhaft festlegen: `LAG_PRIVILEGE=sudo ./start.sh`. Der Benutzer muss `sudo` verwenden dürfen (Gruppe `sudo` bzw. `wheel`).

Tastenkürzel: F5 aktualisieren, Strg+1…6 Seiten. Einstellungen: `~/.config/linux-admin-gui/settings.json`.

## Handbuch
Deutsch/English mit Screenshots im Ordner [`docs/`](docs/) (PDF und Word).

## Tests
    pip install pytest
    xvfb-run -a python3 -m pytest tests

Integrationstests (echtes `useradd`, `usermod`, `sudo` …) laufen nur als root und legen kurzzeitig Konten `tgui_*` an.
Führen Sie sie ausschließlich auf Test- oder Containersystemen aus. Als normaler Benutzer werden sie übersprungen.

## Dateien
`main.py` Oberfläche · `backend.py` Logik und Rechtebeschaffung · `i18n.py` Texte DE/EN · `theme.py` Design ·
`settings.py` Einstellungen · `tests/` Tests · `docs/` Handbuch

---

<a id="english"></a>

# Linux Admin GUI (English)

A graphical tool for managing users, groups, file permissions and ACLs on Linux (Python/Tkinter).
© 2026 Eugen Becker. All rights reserved.

## Install from GitHub (apt-based systems: Debian, Ubuntu, Mint)

    sudo apt install git
    git clone https://github.com/beckereugen04-coder/linux-admin-gui.git
    cd linux-admin-gui
    ./install.sh        # installs python3-tk, acl and pkexec/policykit-1
    ./install_app.sh    # copies to /opt/linux-admin-gui and adds a menu entry

Start it from the menu entry “Linux Admin GUI” or with `python3 /opt/linux-admin-gui/main.py`.
To run it straight from the folder without installing: `./start.sh`.
Update: `git pull && ./install_app.sh` · Remove: `./uninstall.sh`.

On other distributions install the packages manually: Python 3, Tkinter, `acl`, and `pkexec` (Polkit) or `sudo`.

If the scripts are not executable (e.g. after uploading from Windows): `chmod +x *.sh` or run `bash install.sh`.
The app itself runs on Linux only.

## Features
- Users: create (full name, UID, shell), delete, rename, lock/unlock, password, password expiry, shell, primary group, groups
- Groups: create, delete (regular groups only), members, group folders under /srv (2770, SGID)
- Permissions: owner/group/chmod including SUID/SGID/sticky
- ACLs: set for groups and users, inherit, recursive, remove entries or all ACLs
- Log: successes, errors, cancellations (`~/.local/state/linux-admin-gui/actions.log`, no passwords)
- Interface: sidebar, drop-down menus, search, German/English, light/dark theme (Settings, top right)

The interface runs as a normal user; privileged actions run bundled through `pkexec` or `sudo`
(one password prompt per action). Over SSH the automatic mode picks `sudo` (password asked in the application window):

    ssh -X user@server
    ./start.sh

Set it permanently with `LAG_PRIVILEGE=sudo ./start.sh`. The user must be allowed to use `sudo` (group `sudo` or `wheel`).

Shortcuts: F5 refresh, Ctrl+1…6 pages. Settings: `~/.config/linux-admin-gui/settings.json`.

## Manual
German/English with screenshots in [`docs/`](docs/) (PDF and Word).

## Tests
    pip install pytest
    xvfb-run -a python3 -m pytest tests

Integration tests (real `useradd`, `usermod`, `sudo` …) only run as root and briefly create accounts `tgui_*`.
Run them on test or container systems only. They are skipped for normal users.
