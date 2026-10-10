import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import i18n  # noqa: E402
import settings  # noqa: E402
import theme  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _placeholders(text):
    return set(re.findall(r"\{(\w+)\}", text))


@pytest.fixture(autouse=True)
def reset_language():
    yield
    i18n.set_language("de")


# ---------------------------------------------------------------- i18n -----
def test_every_entry_has_both_languages_with_same_placeholders():
    for key, entry in i18n.CATALOG.items():
        assert entry.get("de") and entry.get("en"), key
        assert _placeholders(entry["de"]) == _placeholders(entry["en"]), key


def test_all_keys_used_in_code_exist():
    src = _source("main.py") + _source("backend.py")
    keys = set(re.findall(r'\bt\(\s*"([A-Za-z0-9_]+)"', src))
    keys |= set(re.findall(r'\(\s*"([a-z]+_[a-z_]+)"\s*,\s*(?:self\.|\[)', src))
    keys |= set(re.findall(r'menubutton\([a-z]+, "([a-z_]+)"', src))
    keys |= set(re.findall(r'"(lab_[a-z]+)"', src))
    keys |= {f"nav_{k}" for k in ("users", "groups", "rights", "acl", "log", "about")}
    keys |= {f"theme_{v}" for v in ("light", "dark")}
    keys |= {f"priv_{v}" for v in ("auto", "pkexec", "sudo")}
    keys |= {f"priv_name_{v}" for v in ("direct", "pkexec", "sudo")}
    missing = sorted(k for k in keys if k not in i18n.CATALOG)
    assert not missing, missing


def test_switching_language_changes_text():
    i18n.set_language("de")
    assert i18n.t("btn_cancel") == "Abbrechen"
    i18n.set_language("en")
    assert i18n.t("btn_cancel") == "Cancel"


def test_unknown_language_falls_back_to_german_and_unknown_key_returns_key():
    i18n.set_language("fr")
    assert i18n.LANG == "de"
    assert i18n.t("does_not_exist") == "does_not_exist"


def test_placeholders_are_filled():
    i18n.set_language("en")
    assert "anna" in i18n.t("user_exists", name="anna")


def test_about_text_has_no_test_system_wording_and_names_the_author():
    for lang in ("de", "en"):
        i18n.set_language(lang)
        text = " ".join(i18n.t(k) for k in ("about_tagline", "about_overview", "about_f1", "about_f6"))
        assert "Lern" not in text and "learning" not in text.lower()
        assert "Eugen Becker" in i18n.t("about_copyright", year="2026", author="Eugen Becker")


def test_backend_messages_follow_language():
    import backend
    i18n.set_language("en")
    with pytest.raises(ValueError) as err:
        backend.validate_name("-D")
    assert "Invalid" in str(err.value)
    i18n.set_language("de")
    with pytest.raises(ValueError) as err:
        backend.validate_name("-D")
    assert "Ungültig" in str(err.value)


# ------------------------------------------------------------- settings -----
def test_settings_roundtrip(tmp_path):
    path = str(tmp_path / "cfg" / "settings.json")
    prefs = {"lang": "en", "theme": "dark", "privilege": "sudo"}
    assert settings.save(prefs, path) is True
    assert settings.load(path) == prefs


def test_settings_invalid_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"lang": "xx", "theme": "pink", "privilege": "rm -rf"}')
    loaded = settings.load(str(path))
    assert loaded["lang"] in settings.LANGS and loaded["theme"] == "light" and loaded["privilege"] == "auto"


@pytest.mark.parametrize("content", ["", "not json", "[1, 2]", "null"])
def test_settings_broken_file_gives_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert settings.load(str(path)) == settings.defaults()


def test_settings_missing_file_gives_defaults(tmp_path):
    assert settings.load(str(tmp_path / "nope.json")) == settings.defaults()


def test_default_language_from_locale(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert settings.default_language() == "de"
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert settings.default_language() == "en"


def test_save_failure_is_ignored(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert settings.save({"lang": "de"}, str(blocker / "sub" / "s.json")) is False


# ---------------------------------------------------------------- theme -----
def test_palettes_have_identical_keys():
    assert set(theme.PALETTES["light"]) == set(theme.PALETTES["dark"])


@pytest.mark.parametrize("name", ["light", "dark"])
def test_palette_colors_are_valid_hex(name):
    for key, value in theme.PALETTES[name].items():
        assert re.fullmatch(r"#[0-9a-f]{6}", value), (name, key, value)


def _luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("name", ["light", "dark"])
def test_text_contrast_is_readable(name):
    p = theme.PALETTES[name]
    assert _contrast(p["text"], p["bg"]) >= 7
    assert _contrast(p["text"], p["surface"]) >= 7
    assert _contrast(p["muted"], p["surface"]) >= 4.5
    assert _contrast(p["accent_fg"], p["accent"]) >= 4.5     # Text auf Akzent-Schaltflächen
    assert _contrast(p["accent_fg"], p["accent_hover"]) >= 3.5
    assert _contrast(p["danger"], p["button"]) >= 3.5        # rote Schrift auf "Löschen"
    assert _contrast(p["sidebar_text"], p["sidebar"]) >= 7
    assert _contrast(p["select_fg"], p["select_bg"]) >= 7
