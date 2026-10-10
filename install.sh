#!/usr/bin/env bash
# Installiert die Abhängigkeiten (Debian/Ubuntu und Derivate).
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Dieses Skript unterstützt nur apt-basierte Systeme." >&2
    echo "Benötigt werden: python3, Tkinter, acl und pkexec (polkit)." >&2
    exit 1
fi

# Je nach Version heißt das Paket 'pkexec' oder (älter) 'policykit-1'.
sudo apt-get update
if apt-cache show pkexec >/dev/null 2>&1; then
    POLKIT_PKG=pkexec
else
    POLKIT_PKG=policykit-1
fi

sudo apt-get install -y python3 python3-tk acl "$POLKIT_PKG"
echo "Fertig. Starten mit ./start.sh oder installieren mit ./install_app.sh"
