"""Oberflächen-Tests. Brauchen ein Display (z. B. xvfb-run python3 -m pytest tests)."""
import os
import stat
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

tk = pytest.importorskip("tkinter")
if not os.environ.get("DISPLAY"):
    pytest.skip("kein Display (xvfb-run verwenden)", allow_module_level=True)

from tkinter import ttk  # noqa: E402

import backend as be  # noqa: E402
import i18n  # noqa: E402
import main  # noqa: E402
import settings  # noqa: E402
import theme  # noqa: E402
from i18n import t  # noqa: E402

needs_root = pytest.mark.skipif(os.geteuid() != 0 or not be.shutil.which("useradd"),
                                reason="braucht root und useradd")


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def settle(app, rounds=8):
    """Wartet, bis verzögerte Neuaufbauten (after) abgearbeitet sind."""
    import time
    for _ in range(rounds):
        app.root.update()
        time.sleep(0.03)


def labels(app):
    texts = []
    for w in walk(app.root):
        try:
            texts.append(str(w.cget("text")))
        except tk.TclError:
            pass
    return texts


@pytest.fixture
def make_app(monkeypatch, tmp_path):
    monkeypatch.setattr(be, "ADMIN_PREFIX", [])
    monkeypatch.setattr(be, "LOG_FILE", str(tmp_path / "actions.log"))
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    created = []

    def factory(lang="de", theme_name="light", save=False):
        prefs = {"lang": lang, "theme": theme_name, "privilege": "auto"}
        app = main.App(prefs=prefs, save_prefs=save)
        created.append(app)
        app.root.update()
        return app

    yield factory
    for app in created:
        try:
            app.root.destroy()
        except tk.TclError:
            pass
    i18n.set_language("de")


# ------------------------------------------------------------ Aufbau / Texte --
@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_every_page_builds_in_every_language_and_theme(make_app, lang, theme_name):
    app = make_app(lang, theme_name)
    for key in main.PAGES:
        app.show_page(key)
        app.root.update()
        assert app.title_var.get() == t(f"nav_{key}")
    assert set(app.pages) == set(main.PAGES)


def test_navigation_highlights_current_page(make_app):
    app = make_app()
    app.show_page("rights")
    assert str(app.nav["rights"].cget("style")) == "NavActive.TButton"
    assert str(app.nav["users"].cget("style")) == "Nav.TButton"


def test_switch_language_rebuilds_with_new_texts_and_persists(make_app, tmp_path):
    app = make_app("de", "light", save=True)
    assert "Benutzer" in labels(app)
    app.set_language("en")
    settle(app)
    assert "Users" in labels(app) and "Benutzer" not in labels(app)
    assert settings.load(str(tmp_path / "settings.json"))["lang"] == "en"


def test_switch_theme_changes_colors_and_persists(make_app, tmp_path):
    app = make_app("de", "light", save=True)
    style = ttk.Style(app.root)
    assert style.lookup("TFrame", "background") == theme.PALETTES["light"]["bg"]
    app.set_theme("dark")
    settle(app)
    assert ttk.Style(app.root).lookup("TFrame", "background") == theme.PALETTES["dark"]["bg"]
    assert settings.load(str(tmp_path / "settings.json"))["theme"] == "dark"


def test_page_is_kept_after_rebuild(make_app):
    app = make_app()
    app.show_page("acl")
    app.set_theme("dark")
    settle(app)
    assert app.page == "acl" and app.title_var.get() == t("nav_acl")


def test_about_page_has_overview_and_copyright(make_app):
    for lang in ("de", "en"):
        app = make_app(lang)
        texts = " ".join(labels(app))
        assert "Eugen Becker" in texts and "2026" in texts
        assert "Lern" not in texts and "learning" not in texts.lower()
        assert f"{main.VERSION}" in texts


def test_user_toolbar_uses_dropdown_menus_instead_of_many_buttons(make_app):
    app = make_app()
    page = app.pages["users"]
    menubuttons = [w for w in walk(page) if isinstance(w, ttk.Menubutton)]
    plain_buttons = [w for w in walk(page) if isinstance(w, ttk.Button)]
    assert len(menubuttons) == 3
    assert len(plain_buttons) <= 3              # Erstellen, Löschen, Aktualisieren
    entries = []
    for mb in menubuttons:
        menu = app.root.nametowidget(str(mb.cget("menu")))
        entries += [menu.entrycget(i, "label").strip() for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert len(entries) == 12
    assert t("m_lock") in entries and t("m_rename") in entries and t("m_primary") in entries


def test_context_menu_contains_all_user_actions(make_app):
    app = make_app()
    menu = app.user_menu
    labels_ = [menu.entrycget(i, "label").strip() for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert len(labels_) == 12


# ------------------------------------------------------------------ Dialoge --
def _press(app, text):
    def run():
        dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        for w in walk(dialog):
            if isinstance(w, ttk.Button) and str(w.cget("text")) == text:
                w.invoke()
                return
        raise AssertionError(f"Button {text!r} nicht gefunden")
    app.root.after(200, run)


def test_confirm_ok_and_cancel(make_app):
    app = make_app()
    _press(app, t("btn_ok"))
    assert app.confirm("Sicher?") is True
    _press(app, t("btn_cancel"))
    assert app.confirm("Sicher?") is False


def test_confirm_buttons_follow_language(make_app):
    app = make_app("en")
    _press(app, "Cancel")
    assert app.confirm("Sure?") is False


def test_form_validation_keeps_dialog_open_until_valid(make_app):
    app = make_app()
    errors = []
    app.error = lambda text, parent=None: errors.append(text)

    def fill():
        dialog = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        entry = [w for w in walk(dialog) if isinstance(w, ttk.Entry)][0]
        entry.insert(0, "falsch")
        [b for b in walk(dialog) if isinstance(b, ttk.Button) and str(b.cget("text")) == "Weiter"][0].invoke()
        entry.delete(0, "end")
        entry.insert(0, "richtig")
        [b for b in walk(dialog) if isinstance(b, ttk.Button) and str(b.cget("text")) == "Weiter"][0].invoke()

    app.root.after(200, fill)
    values = app.ask_form("Test", [{"key": "x", "label": "X"}],
                          validate=lambda v: "nein" if v["x"] == "falsch" else None, ok_text="Weiter")
    assert errors == ["nein"] and values == {"x": "richtig"}


# --------------------------------------------------------- Tabellen / Suche --
def test_search_filters_users_and_groups(make_app, monkeypatch):
    app = make_app()
    monkeypatch.setattr(be, "list_users", lambda: ["anna", "bert"])
    monkeypatch.setattr(be, "list_groups", lambda include_system=True: ["team", "other"])
    monkeypatch.setattr(be, "primary_group", lambda u: u)
    monkeypatch.setattr(be, "group_members", lambda g: ["anna"])
    monkeypatch.setattr(be.grp, "getgrnam", lambda n: type("G", (), {"gr_gid": 3000})())
    monkeypatch.setattr(be.pwd, "getpwnam", lambda n: be.pwd.struct_passwd((n, "x", 2000, 2000, "", f"/home/{n}", "/bin/sh")))
    app.refresh()
    assert len(app.users_tree.get_children()) == 2
    app.search_users.set("ber")
    app.refresh_users()
    assert [app.users_tree.item(i, "values")[0] for i in app.users_tree.get_children()] == ["bert"]
    app.search_groups.set("tea")
    app.refresh_groups()
    assert len(app.groups_tree.get_children()) == 1


def test_show_system_groups_toggle(make_app):
    app = make_app()
    app.show_system.set(False)
    app.refresh_groups()
    without = len(app.groups_tree.get_children())
    app.show_system.set(True)
    app.refresh_groups()
    assert len(app.groups_tree.get_children()) > without


def test_zebra_striping_applied(make_app, monkeypatch):
    app = make_app()
    app.show_system.set(True)
    app.refresh_groups()
    tags = [app.groups_tree.item(i, "tags")[0] for i in app.groups_tree.get_children()][:4]
    assert tags == ["even", "odd", "even", "odd"]


# ------------------------------------------------------------ Rechte / ACL ---
def test_rights_special_bits_and_apply(make_app, tmp_path):
    app = make_app()
    folder = tmp_path / "ordner"
    folder.mkdir()
    os.chmod(folder, 0o2770)
    app.path_var.set(str(folder))
    app.load_permissions()
    assert app.octal_var.get() == "2770" and app.checks["sgid"].get() is True
    app.checks["sgid"].set(False)
    app.update_octal_from_checks()
    assert app.octal_var.get() == "770"
    app.group_var.set(be.owner_group_of(str(folder))[1])
    app.apply_group_and_permissions()
    assert not os.stat(folder).st_mode & stat.S_ISGID           # SGID wirklich entfernt


def test_rights_without_group_asks_for_group(make_app, tmp_path):
    app = make_app()
    shown = []
    app.message = lambda text, kind="info", parent=None: shown.append(text)
    app.path_var.set(str(tmp_path))
    app.group_var.set("")
    app.apply_group_and_permissions()
    assert shown == [t("select_group_first")]


def test_octal_field_updates_checkboxes(make_app):
    app = make_app()
    app.octal_var.set("640")
    assert app.checks["gr"].get() and not app.checks["gw"].get() and not app.checks["or"].get()
    app.octal_var.set("889")                                    # ungültig: nichts ändern
    assert app.checks["gr"].get()


def test_acl_kind_switch_changes_selection_list(make_app):
    app = make_app()
    app.acl_kind.set("g")
    app.refresh_group_combos()
    groups = list(app.acl_combo["values"])
    app.acl_kind.set("u")
    app.refresh_group_combos()
    assert list(app.acl_combo["values"]) != groups or not groups


@pytest.mark.skipif(not be.shutil.which("setfacl"), reason="acl fehlt")
def test_acl_set_inherit_and_remove(make_app, tmp_path):
    app = make_app()
    app.confirm = lambda *a, **k: True
    folder = tmp_path / "acl"
    folder.mkdir()
    app.acl_path_var.set(str(folder))
    app.acl_kind.set("g")
    app.refresh_group_combos()
    app.acl_group_var.set("daemon")
    app.apply_default_acl()
    text = app.acl_text.get("1.0", "end")
    assert "group:daemon:rwx" in text and "default:group:daemon:rwx" in text
    app.remove_entry_acl()
    assert "daemon" not in app.acl_text.get("1.0", "end")


# ------------------------------------------------------ echte Aktionen (root) --
@needs_root
def test_create_and_delete_user_through_the_ui(make_app):
    app = make_app()
    app.confirm = lambda *a, **k: True
    app.message = lambda *a, **k: None
    name = "tgui_ui_user"
    try:
        app.ask_form = lambda title, fields, validate=None, ok_text=None, intro=None: {
            "name": name, "comment": "UI Test", "uid": "", "shell": "/bin/sh", "pw1": "Geheim123", "pw2": "Geheim123"}
        app.create_user()
        names = [app.users_tree.item(i, "values")[0] for i in app.users_tree.get_children()]
        assert name in names
        for iid in app.users_tree.get_children():
            if app.users_tree.item(iid, "values")[0] == name:
                app.users_tree.selection_set(iid)
        app.current_user = "someone-else"
        app.ask_form = lambda *a, **k: {"typed": name}
        app.delete_user()
        names = [app.users_tree.item(i, "values")[0] for i in app.users_tree.get_children()]
        assert name not in names
        assert "tgui_ui_user" in be.read_log()
    finally:
        subprocess.run(["userdel", "-r", name], capture_output=True)
        subprocess.run(["groupdel", name], capture_output=True)


def test_failed_action_shows_error_dialog_text(make_app):
    app = make_app()
    errors = []
    app.error = lambda text, parent=None: errors.append(text)
    assert app.act(be.create_group, "-D") is False
    assert errors and "Ungültig" in errors[0]
    i18n.set_language("en")
    assert app.act(be.create_group, "-D") is False
    assert "Invalid" in errors[1]


def test_ui_stays_responsive_during_long_action(make_app):
    import time
    app = make_app()
    ticks = []

    def tick():
        ticks.append(1)
        app.root.after(30, tick)

    app.root.after(30, tick)
    app.run_blocking(lambda: time.sleep(0.4))
    assert len(ticks) >= 5
