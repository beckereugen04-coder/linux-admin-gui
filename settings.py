"""Einstellungen (Sprache, Design, Rechte-Methode) – gespeichert unter ~/.config/linux-admin-gui/settings.json."""
import json
import os

LANGS = ("de", "en")
THEMES = ("light", "dark")
PRIVILEGES = ("auto", "pkexec", "sudo")


def settings_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "linux-admin-gui", "settings.json")


def default_language():
    locale = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
    return "de" if locale.startswith("de") else "en"


def defaults():
    return {"lang": default_language(), "theme": "light", "privilege": "auto"}


def load(path=None):
    """Liest die Einstellungen; unbekannte oder fehlerhafte Werte werden durch Standardwerte ersetzt."""
    prefs = defaults()
    try:
        with open(path or settings_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return prefs
    if isinstance(data, dict):
        if data.get("lang") in LANGS:
            prefs["lang"] = data["lang"]
        if data.get("theme") in THEMES:
            prefs["theme"] = data["theme"]
        if data.get("privilege") in PRIVILEGES:
            prefs["privilege"] = data["privilege"]
    return prefs


def save(prefs, path=None):
    """Speichert atomar. Fehler (z. B. schreibgeschütztes Home) werden bewusst ignoriert."""
    target = path or settings_path()
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh, indent=2)
        os.replace(tmp, target)
        return True
    except OSError:
        return False
