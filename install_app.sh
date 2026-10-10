#!/usr/bin/env bash
# Installiert die App nach /opt/linux-admin-gui und legt einen Starter im Menü an.
set -euo pipefail
cd "$(dirname "$0")"

APP_DIR=/opt/linux-admin-gui
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

sudo install -d -m 755 "$APP_DIR"
sudo install -m 644 main.py backend.py i18n.py settings.py theme.py "$APP_DIR/"

mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/linux-admin-gui.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Linux Admin GUI
Comment=Benutzer, Gruppen, Rechte und ACLs verwalten
Exec=python3 $APP_DIR/main.py
Terminal=false
Categories=System;Settings;
DESKTOP

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true
echo "Installiert nach $APP_DIR. Starter: $DESKTOP_DIR/linux-admin-gui.desktop"
