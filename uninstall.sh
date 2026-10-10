#!/usr/bin/env bash
# Entfernt die installierte App und den Menüeintrag.
set -euo pipefail

sudo rm -rf /opt/linux-admin-gui
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/linux-admin-gui.desktop"
echo "Linux Admin GUI wurde entfernt. (Aktionsprotokoll unter ~/.local/state/linux-admin-gui bleibt erhalten.)"
