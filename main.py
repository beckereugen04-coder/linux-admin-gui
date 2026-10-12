#!/usr/bin/env python3
"""Linux Admin GUI – Benutzer, Gruppen, Rechte und ACLs verwalten.

Die Oberfläche läuft als normaler Benutzer. Privilegierte Aktionen laufen gebündelt
über backend.admin_batch() (pkexec oder sudo).
"""
import os
import pwd
import stat
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import backend as be
import i18n
import settings
import theme
from i18n import t

APP_NAME = "Linux Admin GUI"
VERSION = "14.0"
AUTHOR = "Eugen Becker"
YEAR = "2026"
PAGES = ("users", "groups", "rights", "acl", "log", "about")


# ----------------------------------------------------------------------------
# Kleine Bausteine
# ----------------------------------------------------------------------------
def make_tree(parent, columns, widths, palette):
    """Tabelle mit Scrollbar, Zebra-Streifen und per Klick sortierbaren Spalten."""
    frame = ttk.Frame(parent, style="Card.TFrame")
    keys = [c[0] for c in columns]
    tree = ttk.Treeview(frame, columns=keys, show="headings", selectmode="browse")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.tag_configure("odd", background=palette["surface_alt"])
    tree.tag_configure("even", background=palette["surface"])

    def sort_by(col, reverse):
        rows = [(tree.set(k, col), k) for k in tree.get_children("")]
        try:
            rows.sort(key=lambda r: float(r[0]), reverse=reverse)
        except ValueError:
            rows.sort(key=lambda r: r[0].lower(), reverse=reverse)
        for index, (_, key) in enumerate(rows):
            tree.move(key, "", index)
        stripe(tree)
        tree.heading(col, command=lambda: sort_by(col, not reverse))

    for (key, label), width in zip(columns, widths):
        tree.heading(key, text=label, anchor="w", command=lambda c=key: sort_by(c, False))
        tree.column(key, width=width, anchor="w")
    tree.pack(side="left", fill="both", expand=True, padx=(1, 0), pady=1)
    scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
    return frame, tree


def stripe(tree):
    for index, item in enumerate(tree.get_children("")):
        tree.item(item, tags=("odd" if index % 2 else "even",))


class App:
    def __init__(self, root=None, prefs=None, save_prefs=True):
        self.prefs = prefs if prefs is not None else settings.load()
        self.save_prefs = save_prefs
        i18n.set_language(self.prefs["lang"])
        if "LAG_PRIVILEGE" not in os.environ:
            be.PRIVILEGE_METHOD = self.prefs["privilege"]

        self.root = root or tk.Tk()
        self.root.geometry("1240x780")
        self.root.minsize(1160, 680)
        self.current_user = pwd.getpwuid(os.getuid()).pw_name
        self.page = "users"
        self.syncing = False

        # Variablen bleiben beim Neuaufbau (Sprache/Design) erhalten
        self.status = tk.StringVar()
        self.title_var = tk.StringVar()
        self.search_users = tk.StringVar()
        self.search_groups = tk.StringVar()
        self.show_system = tk.BooleanVar(value=False)
        self.group_info = tk.StringVar()
        self.path_var = tk.StringVar()
        self.type_var = tk.StringVar()
        self.owner_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.octal_var = tk.StringVar()
        self.acl_path_var = tk.StringVar()
        self.acl_group_var = tk.StringVar()
        self.acl_kind = tk.StringVar(value="g")
        self.acl_recursive = tk.BooleanVar(value=False)
        self.acl_read = tk.BooleanVar(value=True)
        self.acl_write = tk.BooleanVar(value=True)
        self.acl_execute = tk.BooleanVar(value=True)
        self.checks = {key: tk.BooleanVar() for key in
                       ("ur", "uw", "ux", "gr", "gw", "gx", "or", "ow", "ox", "suid", "sgid", "sticky")}
        self.octal_var.trace_add("write", self.update_checks_from_octal)

        self.root.bind("<F5>", lambda e: self.refresh())
        for index, key in enumerate(PAGES, start=1):
            self.root.bind(f"<Control-Key-{index}>", lambda e, k=key: self.show_page(k))
        self.build()

    def run(self):
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def build(self):
        for child in self.root.winfo_children():
            child.destroy()
        self.p = theme.apply(self.root, self.prefs["theme"])
        self.font = theme.pick_font(self.root)
        self.root.title(f"{APP_NAME} v{VERSION}")

        side = ttk.Frame(self.root, style="Sidebar.TFrame", width=208)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self.build_sidebar(side)

        main = ttk.Frame(self.root)
        main.pack(side="left", fill="both", expand=True)
        self.build_topbar(main)
        ttk.Label(main, textvariable=self.status, style="Status.TLabel", anchor="w").pack(side="bottom", fill="x")
        self.body = ttk.Frame(main)
        self.body.pack(fill="both", expand=True, padx=24, pady=(4, 16))
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)

        self.pages = {}
        builders = {"users": self.build_users, "groups": self.build_groups, "rights": self.build_rights,
                    "acl": self.build_acl, "log": self.build_log, "about": self.build_about}
        for key in PAGES:
            frame = ttk.Frame(self.body)
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = frame
            builders[key](frame)

        self.refresh()
        self.refresh_log()
        self.show_page(self.page)
        self.show_privilege_status()

    def rebuild(self):
        self.root.after(10, self.build)

    def logo(self, parent, size, bg):
        canvas = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
        r = size // 4
        pts = [r, 0, size - r, 0, size, 0, size, r, size, size - r, size, size, size - r, size,
               r, size, 0, size, 0, size - r, 0, r, 0, 0]
        canvas.create_polygon(pts, smooth=True, fill=self.p["accent"], outline="")
        canvas.create_text(size / 2, size / 2, text="LA", fill="white", font=(self.font, int(size * 0.34), "bold"))
        return canvas

    def build_sidebar(self, side):
        head = ttk.Frame(side, style="Sidebar.TFrame")
        head.pack(fill="x", padx=14, pady=(24, 22))
        self.logo(head, 40, self.p["sidebar"]).pack(side="left")
        titles = ttk.Frame(head, style="Sidebar.TFrame")
        titles.pack(side="left", padx=(10, 0))
        ttk.Label(titles, text="Linux Admin", style="SidebarTitle.TLabel").pack(anchor="w")
        ttk.Label(titles, text=f"GUI  ·  v{VERSION}", style="Sidebar.TLabel").pack(anchor="w")
        self.nav = {}
        for key in PAGES:
            button = ttk.Button(side, text=t(f"nav_{key}"), style="Nav.TButton",
                                command=lambda k=key: self.show_page(k))
            button.pack(fill="x", pady=1)
            self.nav[key] = button
        ttk.Label(side, text=f"© {YEAR} {AUTHOR}", style="Sidebar.TLabel").pack(side="bottom", pady=16)

    def build_topbar(self, main):
        bar = ttk.Frame(main)
        bar.pack(fill="x", padx=24, pady=(22, 12))
        ttk.Label(bar, textvariable=self.title_var, style="Title.TLabel").pack(side="left")
        menu_button = ttk.Menubutton(bar, text=t("settings"), width=0)
        menu = theme.style_menu(tk.Menu(menu_button), self.p)
        menu_button["menu"] = menu
        menu_button.pack(side="right")

        self.lang_var = tk.StringVar(value=self.prefs["lang"])
        self.theme_var = tk.StringVar(value=self.prefs["theme"])
        self.priv_var = tk.StringVar(value=self.prefs["privilege"])
        sub_lang = theme.style_menu(tk.Menu(menu), self.p)
        for code, name in i18n.LANGUAGES.items():
            sub_lang.add_radiobutton(label=self.pad(name), value=code, variable=self.lang_var,
                                     command=lambda c=code: self.set_language(c))
        sub_theme = theme.style_menu(tk.Menu(menu), self.p)
        for value in ("light", "dark"):
            sub_theme.add_radiobutton(label=self.pad(t(f"theme_{value}")), value=value, variable=self.theme_var,
                                      command=lambda v=value: self.set_theme(v))
        sub_priv = theme.style_menu(tk.Menu(menu), self.p)
        for value in ("auto", "pkexec", "sudo"):
            sub_priv.add_radiobutton(label=self.pad(t(f"priv_{value}")), value=value, variable=self.priv_var,
                                     command=lambda v=value: self.set_privilege(v))
        menu.add_cascade(label=self.pad(t("set_language")), menu=sub_lang)
        menu.add_cascade(label=self.pad(t("set_theme")), menu=sub_theme)
        menu.add_cascade(label=self.pad(t("set_rights")), menu=sub_priv)

    def show_page(self, key):
        self.page = key
        self.pages[key].tkraise()
        for name, button in self.nav.items():
            button.configure(style="NavActive.TButton" if name == key else "Nav.TButton")
        self.title_var.set(t(f"nav_{key}"))
        if key == "log":
            self.refresh_log()

    # ------------------------------------------------------------------
    # Einstellungen
    # ------------------------------------------------------------------
    def persist(self):
        if self.save_prefs:
            settings.save(self.prefs)

    def set_language(self, code):
        if code == self.prefs["lang"]:
            return
        self.prefs["lang"] = code
        i18n.set_language(code)
        self.persist()
        self.rebuild()

    def set_theme(self, name):
        if name == self.prefs["theme"]:
            return
        self.prefs["theme"] = name
        self.persist()
        self.rebuild()

    def set_privilege(self, method):
        self.prefs["privilege"] = method
        be.PRIVILEGE_METHOD = method
        be.clear_sudo_password()
        self.persist()
        self.show_privilege_status()

    def show_privilege_status(self):
        method = be.privilege_method() if be.ADMIN_PREFIX is None else "direct"
        self.status.set(t("status_ready", method=t(f"priv_name_{method}")))

    # ------------------------------------------------------------------
    # Hilfsfunktionen: Karten, Menüs, Dialoge
    # ------------------------------------------------------------------
    def card(self, parent, title=None):
        outer = ttk.Frame(parent, style="Card.TFrame", padding=16)
        if title:
            ttk.Label(outer, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        inner = ttk.Frame(outer, style="Plain.TFrame")
        inner.pack(fill="both", expand=True)
        return outer, inner

    def fill_menu(self, menu, entries):
        for entry in entries:
            if entry is None:
                menu.add_separator()
            else:
                key, command = entry
                menu.add_command(label=self.pad(t(key)), command=command)
        return menu

    def menubutton(self, parent, text_key, entries):
        button = ttk.Menubutton(parent, text=t(text_key), width=0)
        menu = theme.style_menu(tk.Menu(button), self.p)
        self.fill_menu(menu, entries)
        button["menu"] = menu
        return button

    @staticmethod
    def pad(text):
        """Etwas Luft links und rechts, damit Menüeinträge nicht gedrängt wirken."""
        return f"   {text}      "

    def bind_context_menu(self, tree, menu):
        """Rechtsklick-Menü: Zeile beim Drücken markieren, Menü erst beim LOSLASSEN öffnen.

        Öffnet man es schon beim Drücken, löst Tk beim Loslassen den Eintrag unter dem
        Mauszeiger aus bzw. schließt das Menü sofort wieder (man müsste die Taste halten).
        """
        def press(event):
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
                tree.focus(row)

        def release(event):
            if not tree.identify_row(event.y):
                return
            # Die von tk_popup gesetzte Maus-Sperre bleibt bewusst bestehen: Nur sie sorgt dafür,
            # dass ein Klick neben das Menü es wieder schließt.
            menu.tk_popup(event.x_root + 2, event.y_root + 2)

        tree.bind("<Button-3>", press)
        tree.bind("<ButtonRelease-3>", release)

    @staticmethod
    def set_text(widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _dialog(self, title, parent=None):
        parent = parent or self.root
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.transient(parent)
        dialog.resizable(False, False)
        dialog.configure(bg=self.p["bg"])
        return dialog

    def _modal(self, dialog, parent=None):
        parent = parent or self.root
        previous = None
        try:
            previous = parent.grab_current()
        except tk.TclError:
            pass
        dialog.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_reqheight()) // 3
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.wait_visibility()
        dialog.grab_set()
        dialog.wait_window()
        if previous is not None:
            try:
                previous.grab_set()
            except tk.TclError:
                pass

    def _badge(self, parent, symbol, color):
        badge = tk.Canvas(parent, width=34, height=34, bg=self.p["bg"], highlightthickness=0)
        badge.create_oval(2, 2, 32, 32, fill=color, outline="")
        badge.create_text(17, 17, text=symbol, fill="white", font=(self.font, 14, "bold"))
        badge.pack(side="left", anchor="n", padx=(0, 14))

    def message(self, text, kind="info", parent=None):
        """Hinweis- oder Fehlerdialog (im aktuellen Design, in der aktuellen Sprache)."""
        dialog = self._dialog(APP_NAME, parent)
        body = ttk.Frame(dialog, padding=(24, 22, 24, 6))
        body.pack(fill="both", expand=True)
        error = kind == "error"
        self._badge(body, "!" if error else "i", self.p["danger"] if error else self.p["accent"])
        ttk.Label(body, text=text, wraplength=420, justify="left").pack(side="left")
        row = ttk.Frame(dialog, padding=(24, 12, 24, 20))
        row.pack(fill="x")
        ok = ttk.Button(row, text=t("btn_ok"), style="Accent.TButton", command=dialog.destroy)
        ok.pack(side="right")
        dialog.bind("<Return>", lambda e: dialog.destroy())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        ok.focus_set()
        self._modal(dialog, parent)

    def error(self, text, parent=None):
        self.message(text, "error", parent)

    def confirm(self, text, danger=False, ok_text=None, parent=None):
        dialog = self._dialog(APP_NAME, parent)
        result = {"value": False}
        body = ttk.Frame(dialog, padding=(24, 22, 24, 6))
        body.pack(fill="both", expand=True)
        self._badge(body, "?", self.p["danger"] if danger else self.p["accent"])
        ttk.Label(body, text=text, wraplength=420, justify="left").pack(side="left")
        row = ttk.Frame(dialog, padding=(24, 12, 24, 20))
        row.pack(fill="x")

        def accept(_e=None):
            result["value"] = True
            dialog.destroy()

        yes = ttk.Button(row, text=ok_text or t("btn_ok"), style="Accent.TButton", command=accept)
        yes.pack(side="right")
        ttk.Button(row, text=t("btn_cancel"), command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.bind("<Return>", accept)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        yes.focus_set()
        self._modal(dialog, parent)
        return result["value"]

    def ask_form(self, title, fields, validate=None, ok_text=None, intro=None):
        """Formular. fields: key, label, kind (entry|password|combo|check), value, values.
        validate(values) -> Fehlertext oder None. Gibt dict oder None zurück."""
        dialog = self._dialog(title)
        if intro:
            ttk.Label(dialog, text=intro, justify="left", wraplength=440).pack(anchor="w", padx=24, pady=(20, 2))
        body = ttk.Frame(dialog)
        body.pack(fill="x", padx=24, pady=12)
        variables, first = {}, None
        for row, field in enumerate(fields):
            kind = field.get("kind", "entry")
            if kind == "check":
                var = tk.BooleanVar(value=field.get("value", False))
                ttk.Checkbutton(body, text=field["label"], variable=var).grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=5)
            else:
                var = tk.StringVar(value=field.get("value", ""))
                ttk.Label(body, text=field["label"]).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 16))
                if kind == "combo":
                    widget = ttk.Combobox(body, textvariable=var, values=field["values"], state="readonly", width=28)
                else:
                    widget = ttk.Entry(body, textvariable=var, width=32, show="•" if kind == "password" else "")
                widget.grid(row=row, column=1, sticky="ew", pady=5)
                first = first or widget
            variables[field["key"]] = var

        result = {"value": None}

        def confirm_form(_event=None):
            values = {key: var.get() for key, var in variables.items()}
            if validate:
                error = validate(values)
                if error:
                    self.error(error, parent=dialog)
                    return
            result["value"] = values
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=24, pady=(6, 20))
        ttk.Button(buttons, text=ok_text or t("btn_ok"), style="Accent.TButton", command=confirm_form).pack(
            side="right")
        ttk.Button(buttons, text=t("btn_cancel"), command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.bind("<Return>", confirm_form)
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        if first is not None:
            first.focus_set()
        self._modal(dialog)
        return result["value"]

    def pick_item(self, heading, items, button_text, label):
        values = self.ask_form(
            heading, [{"key": "item", "kind": "combo", "label": label, "value": items[0], "values": items}],
            ok_text=button_text)
        return values["item"] if values else None

    # ------------------------------------------------------------------
    # Aktionen mit Wartefenster und sudo-Passwortabfrage
    # ------------------------------------------------------------------
    def run_blocking(self, func, *args):
        """Führt func aus. Verlangt sudo ein Passwort, fragt die GUI danach (nicht das Terminal)
        und versucht es erneut – höchstens dreimal. Das Passwort lebt nur für diese Aktion."""
        attempts, prefix = 0, ""
        try:
            while True:
                try:
                    return self._run_thread(func, *args)
                except (be.PasswordRequired, be.WrongPassword) as exc:
                    attempts += 1
                    if attempts > 3:
                        raise be.AdminError(t("sudo_toomany"))
                    if isinstance(exc, be.WrongPassword):
                        prefix = t("sudo_wrong_prefix")
                    values = self.ask_form(
                        t("sudo_title"), [{"key": "pw", "kind": "password", "label": t("sudo_label")}],
                        ok_text=t("btn_ok"), intro=t("sudo_intro", prefix=prefix, user=self.current_user))
                    if values is None:
                        raise be.AdminError(t("sudo_cancelled"))
                    be.set_sudo_password(values["pw"])
        finally:
            be.clear_sudo_password()

    def _run_thread(self, func, *args):
        """Führt func in einem Thread aus und hält die GUI dabei lebendig."""
        result = {}

        def worker():
            try:
                result["value"] = func(*args)
            except BaseException as exc:  # an den GUI-Thread weiterreichen
                result["error"] = exc

        previous = self.root.grab_current()
        wait = tk.Toplevel(self.root)
        wait.title(APP_NAME)
        wait.transient(self.root)
        wait.resizable(False, False)
        wait.configure(bg=self.p["bg"])
        wait.protocol("WM_DELETE_WINDOW", lambda: None)
        ttk.Label(wait, text=t("wait_text"), padding=28, justify="center").pack()
        wait.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - wait.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - wait.winfo_reqheight()) // 3
        wait.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        try:
            wait.wait_visibility()
            wait.grab_set()
        except tk.TclError:
            pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while thread.is_alive():
            self.root.update()
            time.sleep(0.02)

        try:
            wait.grab_release()
        except tk.TclError:
            pass
        wait.destroy()
        if previous is not None:
            try:
                previous.grab_set()
            except tk.TclError:
                pass
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def act(self, func, *args, ok=None, parent=None):
        """Aktion ausführen, Fehler als Dialog zeigen. True bei Erfolg."""
        try:
            self.run_blocking(func, *args)
        except (ValueError, be.AdminError) as exc:
            self.refresh_log()
            self.error(str(exc), parent)
            return False
        except Exception as exc:  # unerwartet, aber die GUI soll weiterleben
            self.refresh_log()
            self.error(t("err_unexpected", detail=exc), parent)
            return False
        if ok:
            self.status.set(ok)
        self.refresh_log()
        return True

    def selected_user(self):
        selection = self.users_tree.selection()
        if not selection:
            self.message(t("select_user_first"))
            return None
        return self.users_tree.item(selection[0], "values")[0]

    def selected_group(self):
        selection = self.groups_tree.selection()
        if not selection:
            self.message(t("select_group_first"))
            return None
        return self.groups_tree.item(selection[0], "values")[0]

    # ------------------------------------------------------------------
    # Aktualisieren
    # ------------------------------------------------------------------
    def refresh(self):
        self.refresh_users()
        self.refresh_groups()
        self.refresh_group_combos()

    def refresh_users(self):
        needle = self.search_users.get().strip().lower()
        self.users_tree.delete(*self.users_tree.get_children())
        for name in be.list_users():
            try:
                entry = pwd.getpwnam(name)
                row = (name, entry.pw_uid, be.primary_group(name), entry.pw_dir, entry.pw_shell)
            except KeyError:
                continue
            if needle and needle not in " ".join(str(v) for v in row).lower():
                continue
            self.users_tree.insert("", "end", values=row)
        stripe(self.users_tree)

    def refresh_groups(self):
        needle = self.search_groups.get().strip().lower()
        self.groups_tree.delete(*self.groups_tree.get_children())
        for name in be.list_groups(include_system=self.show_system.get()):
            try:
                gid = be.grp.getgrnam(name).gr_gid
                members = ", ".join(be.group_members(name))
            except KeyError:
                continue
            if needle and needle not in f"{name} {gid} {members}".lower():
                continue
            self.groups_tree.insert("", "end", values=(name, gid, members))
        stripe(self.groups_tree)
        self.group_info.set(t("group_info_default"))

    def refresh_group_combos(self):
        values = be.list_groups()
        self.group_combo["values"] = values
        acl_values = be.list_groups() if self.acl_kind.get() == "g" else be.list_users()
        self.acl_combo["values"] = acl_values
        if self.group_var.get() not in values:
            self.group_var.set("")
        if self.acl_group_var.get() not in acl_values:
            self.acl_group_var.set("")

    # ------------------------------------------------------------------
    # Seite: Benutzer
    # ------------------------------------------------------------------
    def user_sections(self):
        account = [("m_lock", self.lock_user), ("m_unlock", self.unlock_user), ("m_status", self.show_account_status),
                   None, ("m_setpw", self.change_password), ("m_aging_show", self.show_aging),
                   ("m_aging_set", self.change_aging)]
        groups = [("m_addgroup", self.add_to_group), ("m_rmgroup", self.remove_from_group),
                  ("m_memberships", self.show_memberships), None, ("m_primary", self.change_primary_group)]
        edit = [("m_rename", self.rename_user), ("m_shell", self.change_shell)]
        return account, groups, edit

    def build_users(self, page):
        account, groups, edit = self.user_sections()
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 14))
        ttk.Button(bar, text="⟳", width=3, style="Icon.TButton", command=self.refresh).pack(side="right")
        search = ttk.Entry(bar, textvariable=self.search_users, width=13)
        search.pack(side="right", padx=(0, 8))
        search.bind("<KeyRelease>", lambda e: self.refresh_users())
        ttk.Label(bar, text=t("lbl_search")).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text=t("u_create"), width=0, style="Accent.TButton",
                   command=self.create_user).pack(side="left")
        ttk.Button(bar, text=t("u_delete"), width=0, style="Danger.TButton",
                   command=self.delete_user).pack(side="left", padx=(8, 0))
        self.menubutton(bar, "m_account", account).pack(side="left", padx=(16, 0))
        self.menubutton(bar, "m_groups", groups).pack(side="left", padx=(6, 0))
        self.menubutton(bar, "m_edit", edit).pack(side="left", padx=(6, 0))

        columns = [("user", t("col_user")), ("uid", t("col_uid")), ("primary", t("col_primary")),
                   ("home", t("col_home")), ("shell", t("col_shell"))]
        frame, self.users_tree = make_tree(page, columns, (170, 80, 160, 300, 180), self.p)
        frame.pack(fill="both", expand=True)

        self.user_menu = theme.style_menu(tk.Menu(self.root), self.p)
        for index, section in enumerate((account, groups, edit)):
            if index:
                self.user_menu.add_separator()
            self.fill_menu(self.user_menu, section)
        self.bind_context_menu(self.users_tree, self.user_menu)
        self.users_tree.bind("<Double-1>", lambda e: self.show_memberships() if self.users_tree.selection() else None)

    def create_user(self):
        shells = be.list_shells()
        default_shell = "/bin/bash" if "/bin/bash" in shells else (shells[0] if shells else "")

        def validate(values):
            try:
                name = be.validate_name(values["name"], "lab_user")
                if name in [u.pw_name for u in pwd.getpwall()]:
                    return t("user_exists", name=name)
                if values["uid"].strip():
                    be.validate_uid(values["uid"])
                be.validate_comment(values["comment"])
            except ValueError as exc:
                return str(exc)
            if values["pw1"] != values["pw2"]:
                return t("err_pw_mismatch")
            return None

        values = self.ask_form(
            t("f_create_title"),
            [
                {"key": "name", "label": t("f_name")},
                {"key": "comment", "label": t("f_comment")},
                {"key": "uid", "label": t("f_uid")},
                {"key": "shell", "kind": "combo", "label": t("f_shell"), "value": default_shell, "values": shells},
                {"key": "pw1", "kind": "password", "label": t("f_pw")},
                {"key": "pw2", "kind": "password", "label": t("f_pw2")},
            ],
            validate=validate, ok_text=t("f_create_ok"),
        )
        if not values:
            return
        name = values["name"].strip()
        if self.act(be.create_user, name, values["pw1"] or None, values["uid"].strip() or None,
                    values["comment"].strip() or None, values["shell"] or None,
                    ok=t("ok_user_created", name=name)):
            self.refresh()

    def delete_user(self):
        name = self.selected_user()
        if not name:
            return
        if name == self.current_user:
            self.error(t("cant_delete_self"))
            return

        def validate(values):
            return None if values["typed"].strip() == name else t("del_mismatch")

        values = self.ask_form(
            t("del_title"), [{"key": "typed", "label": t("f_name")}], validate=validate,
            ok_text=t("u_delete"), intro=t("del_intro", name=name))
        if values and self.act(be.delete_user, name, self.current_user, ok=t("ok_user_deleted", name=name)):
            self.refresh()

    def change_password(self):
        name = self.selected_user()
        if not name:
            return

        def validate(values):
            if not values["pw1"]:
                return t("err_pw_empty")
            return None if values["pw1"] == values["pw2"] else t("err_pw_mismatch")

        values = self.ask_form(
            t("pw_title", name=name),
            [{"key": "pw1", "kind": "password", "label": t("f_pw_new")},
             {"key": "pw2", "kind": "password", "label": t("f_pw2")}],
            validate=validate, ok_text=t("m_setpw"))
        if values:
            self.act(be.set_password, name, values["pw1"], ok=t("ok_pw_changed", name=name))

    def show_memberships(self):
        user = self.selected_user()
        if not user:
            return
        primary = be.primary_group(user)
        lines = [t("memberships_primary", group=g) if g == primary else g for g in be.all_groups_of(user)]
        dialog = self._dialog(t("memberships_title", name=user))
        ttk.Label(dialog, text=t("memberships_title", name=user), font=(self.font, 12, "bold")).pack(
            anchor="w", padx=24, pady=(20, 8))
        box = tk.Listbox(dialog, height=min(max(len(lines), 4), 14), width=36, activestyle="none")
        box.configure(bg=self.p["surface"], fg=self.p["text"], selectbackground=self.p["select_bg"],
                      selectforeground=self.p["select_fg"], relief="flat", highlightthickness=1,
                      highlightbackground=self.p["border"], font=(self.font, 11))
        for line in lines:
            box.insert("end", line)
        box.pack(padx=24, pady=4, fill="both", expand=True)
        row = ttk.Frame(dialog)
        row.pack(fill="x", padx=24, pady=(10, 20))
        ttk.Button(row, text=t("btn_close"), style="Accent.TButton", command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        self._modal(dialog)

    def add_to_group(self):
        user = self.selected_user()
        if not user:
            return
        member_of = set(be.all_groups_of(user))
        candidates = [g for g in be.list_groups() if g not in member_of]
        groups = [g for g in candidates if not be.is_system_group(g)] + \
                 [g for g in candidates if be.is_system_group(g)]
        if not groups:
            self.message(t("already_all", user=user))
            return
        group = self.pick_item(t("addgroup_title", user=user), groups, t("btn_add"), t("pick_group_label"))
        if not group:
            return
        if be.is_system_group(group) and not self.confirm(
                t("system_group_warn", group=group, user=user), danger=True):
            return
        if self.act(be.add_user_to_group, user, group, ok=t("ok_added", user=user, group=group)):
            self.refresh()
            self.message(t("relogin_hint"))

    def remove_from_group(self):
        user = self.selected_user()
        if not user:
            return
        groups = be.supplementary_groups(user)
        if not groups:
            self.message(t("no_extra_groups", user=user, primary=be.primary_group(user)))
            return
        group = self.pick_item(t("rmgroup_title", user=user), groups, t("btn_remove"), t("pick_group_label"))
        if group and self.act(be.remove_user_from_group, user, group, ok=t("ok_removed", user=user, group=group)):
            self.refresh()
            self.message(t("relogin_hint"))

    def lock_user(self):
        name = self.selected_user()
        if not name:
            return
        if name == self.current_user:
            self.error(t("cant_lock_self"))
            return
        if self.confirm(t("lock_confirm", name=name), danger=True, ok_text=t("m_lock")):
            self.act(be.lock_user, name, self.current_user, ok=t("ok_locked", name=name))

    def unlock_user(self):
        name = self.selected_user()
        if name:
            self.act(be.unlock_user, name, ok=t("ok_unlocked", name=name))

    def show_account_status(self):
        name = self.selected_user()
        if not name:
            return
        try:
            text = self.run_blocking(be.account_status, name)
        except (ValueError, be.AdminError) as exc:
            self.refresh_log()
            self.error(str(exc))
            return
        self.refresh_log()
        self.status.set(text)
        self.message(text)

    def change_shell(self):
        name = self.selected_user()
        if not name:
            return
        shells = be.list_shells()
        if not shells:
            self.error(t("no_shells"))
            return
        shell = self.pick_item(t("shell_title", name=name), shells, t("btn_change"), t("pick_shell_label"))
        if shell and self.act(be.set_shell, name, shell, ok=t("ok_shell", name=name, shell=shell)):
            self.refresh_users()

    def change_primary_group(self):
        name = self.selected_user()
        if not name:
            return
        current = be.primary_group(name)
        groups = [g for g in be.list_groups() if g != current]
        group = self.pick_item(t("primary_title", name=name, current=current), groups, t("btn_change"),
                               t("pick_group_label"))
        if not group:
            return
        if not self.confirm(t("primary_confirm", name=name, current=current, group=group)):
            return
        if self.act(be.set_primary_group, name, group, ok=t("ok_primary", name=name, group=group)):
            self.refresh()

    def rename_user(self):
        old = self.selected_user()
        if not old:
            return
        if old == self.current_user:
            self.error(t("cant_rename_self"))
            return

        def validate(values):
            try:
                new = be.validate_name(values["new"], "lab_newuser")
            except ValueError as exc:
                return str(exc)
            if new in [u.pw_name for u in pwd.getpwall()]:
                return t("user_exists", name=new)
            return None

        values = self.ask_form(
            t("rename_title", name=old),
            [{"key": "new", "label": t("f_newname")},
             {"key": "home", "kind": "check", "value": True, "label": t("f_rename_home")},
             {"key": "group", "kind": "check", "value": True, "label": t("f_rename_group")}],
            validate=validate, ok_text=t("m_rename"), intro=t("rename_intro"))
        if not values:
            return
        new = values["new"].strip()
        try:
            notes = self.run_blocking(be.rename_user, old, new, self.current_user, values["home"], values["group"])
        except (ValueError, be.AdminError) as exc:
            self.refresh_log()
            self.error(str(exc))
            return
        self.refresh_log()
        self.refresh()
        self.status.set(t("ok_renamed", old=old, new=new))
        self.message(t("rename_done", old=old, new=new, notes="\n".join(notes)))

    def show_aging(self):
        name = self.selected_user()
        if not name:
            return
        try:
            text = self.run_blocking(be.aging_info, name)
        except (ValueError, be.AdminError) as exc:
            self.refresh_log()
            self.error(str(exc))
            return
        self.refresh_log()
        self.message(f"{t('aging_title', name=name)}\n\n{text}")

    def change_aging(self):
        name = self.selected_user()
        if not name:
            return

        def collect(values):
            return dict(max_days=values["max"].strip(), min_days=values["min"].strip(),
                        warn_days=values["warn"].strip(), expire=values["expire"].strip(),
                        force_change=values["force"])

        def validate(values):
            try:
                be.aging_args(**collect(values))
            except ValueError as exc:
                return str(exc)
            return None

        values = self.ask_form(
            t("aging_title", name=name),
            [{"key": "max", "label": t("f_max")}, {"key": "min", "label": t("f_min")},
             {"key": "warn", "label": t("f_warn")}, {"key": "expire", "label": t("f_expire")},
             {"key": "force", "kind": "check", "label": t("f_force")}],
            validate=validate, ok_text=t("btn_apply"), intro=t("aging_intro"))
        if values:
            self.act(lambda: be.set_password_aging(name, **collect(values)), ok=t("ok_aging", name=name))

    # ------------------------------------------------------------------
    # Seite: Gruppen
    # ------------------------------------------------------------------
    def build_groups(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 14))
        ttk.Button(bar, text="⟳", width=3, style="Icon.TButton", command=self.refresh).pack(side="right")
        search = ttk.Entry(bar, textvariable=self.search_groups, width=13)
        search.pack(side="right", padx=(0, 8))
        search.bind("<KeyRelease>", lambda e: self.refresh_groups())
        ttk.Label(bar, text=t("lbl_search")).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text=t("g_create"), style="Accent.TButton", command=self.create_group).pack(side="left")
        ttk.Button(bar, text=t("g_folder"), command=self.create_group_folder).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text=t("g_delete"), style="Danger.TButton", command=self.delete_group).pack(
            side="left", padx=(8, 0))
        ttk.Checkbutton(page, text=t("g_show_system"), variable=self.show_system,
                        command=self.refresh_groups).pack(anchor="w", pady=(0, 10))

        columns = [("group", t("col_group")), ("gid", t("col_gid")), ("members", t("col_members"))]
        frame, self.groups_tree = make_tree(page, columns, (220, 90, 640), self.p)
        frame.pack(fill="both", expand=True)
        ttk.Label(page, textvariable=self.group_info, style="Muted.TLabel", wraplength=900, justify="left").pack(
            fill="x", pady=(10, 0))
        self.groups_tree.bind("<<TreeviewSelect>>", self.show_group_members)

        self.group_menu = theme.style_menu(tk.Menu(self.root), self.p)
        self.fill_menu(self.group_menu, [("g_folder", self.create_group_folder), None, ("g_delete", self.delete_group)])
        self.bind_context_menu(self.groups_tree, self.group_menu)

    def show_group_members(self, _event=None):
        selection = self.groups_tree.selection()
        if not selection:
            return
        group = self.groups_tree.item(selection[0], "values")[0]
        try:
            members = be.group_members(group)
        except KeyError:
            return
        self.group_info.set(t("group_info_members", name=group, members=", ".join(members) or t("none_members")))

    def create_group(self):
        def validate(values):
            try:
                be.validate_name(values["name"], "lab_group")
            except ValueError as exc:
                return str(exc)
            return None

        values = self.ask_form(t("g_create"), [{"key": "name", "label": t("f_group_name")}],
                               validate=validate, ok_text=t("g_create"))
        if not values:
            return
        name = values["name"].strip()
        if self.act(be.create_group, name, ok=t("ok_group_created", name=name)):
            self.refresh()
            self.group_var.set(name)

    def delete_group(self):
        name = self.selected_group()
        if not name:
            return
        if be.is_system_group(name):
            low, high = be.gid_range()
            self.error(t("system_group", name=name, low=low, high=high))
            return
        if self.confirm(t("delete_group_confirm", name=name), danger=True, ok_text=t("g_delete")):
            if self.act(be.delete_group, name, ok=t("ok_group_deleted", name=name)):
                self.refresh()

    def create_group_folder(self):
        group = self.selected_group()
        if not group:
            return

        def validate(values):
            try:
                be.safe_srv_path(values["path"])
            except ValueError as exc:
                return str(exc)
            return None

        values = self.ask_form(
            t("folder_title"), [{"key": "path", "label": t("folder_path_label"), "value": f"/srv/{group}"}],
            validate=validate, ok_text=t("btn_next"))
        if not values:
            return
        real = be.safe_srv_path(values["path"])
        owner = self.current_user
        text = (t("folder_confirm_exists", path=real, group=group) if os.path.isdir(real)
                else t("folder_confirm_new", path=real, owner=owner, group=group))
        if not self.confirm(text):
            return
        if self.act(be.create_group_folder, real, group, owner, ok=t("ok_folder", path=real, owner=owner, group=group)):
            self.path_var.set(real)
            self.load_permissions()

    # ------------------------------------------------------------------
    # Seite: Rechte
    # ------------------------------------------------------------------
    def build_rights(self, page):
        page.columnconfigure(0, weight=1, uniform="cols")
        page.columnconfigure(1, weight=1, uniform="cols")

        target, inner = self.card(page, t("r_target"))
        target.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        entry = ttk.Entry(inner, textvariable=self.path_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.load_permissions())
        ttk.Button(inner, text=t("btn_file"), command=lambda: self.choose_path(False)).pack(side="left", padx=(10, 0))
        ttk.Button(inner, text=t("btn_folder"), command=lambda: self.choose_path(True)).pack(side="left", padx=(6, 0))
        ttk.Button(inner, text=t("btn_load"), style="Accent.TButton", command=self.load_permissions).pack(
            side="left", padx=(6, 0))

        props, inner = self.card(page, t("r_props"))
        props.grid(row=1, column=0, sticky="nsew", padx=(0, 7))
        rows = [(t("r_type"), self.type_var, None), (t("r_owner"), self.owner_var, None),
                (t("r_mode"), self.mode_var, ("DejaVu Sans Mono", 11))]
        for row, (label, var, font) in enumerate(rows):
            ttk.Label(inner, text=label, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 16))
            kwargs = {"font": font} if font else {}
            ttk.Label(inner, textvariable=var, style="Card.TLabel", **kwargs).grid(
                row=row, column=1, columnspan=2, sticky="w")
        ttk.Label(inner, text=t("r_group"), style="CardMuted.TLabel").grid(row=3, column=0, sticky="w", pady=6)
        self.group_combo = ttk.Combobox(inner, textvariable=self.group_var, state="readonly", width=15)
        self.group_combo.grid(row=3, column=1, sticky="w")
        ttk.Button(inner, text=t("r_new_group"), command=self.create_group).grid(row=3, column=2, padx=(8, 0))
        ttk.Label(inner, text=t("r_octal"), style="CardMuted.TLabel").grid(row=4, column=0, sticky="w", pady=6)
        octal = ttk.Frame(inner, style="Plain.TFrame")
        octal.grid(row=4, column=1, columnspan=2, sticky="w")
        ttk.Entry(octal, textvariable=self.octal_var, width=8).pack(side="left")
        ttk.Label(octal, text=t("r_octal_hint"), style="CardMuted.TLabel").pack(side="left", padx=(10, 0))

        perms, inner = self.card(page, t("r_perms"))
        perms.grid(row=1, column=1, sticky="nsew", padx=(7, 0))
        for column, key in enumerate(("r_read", "r_write", "r_exec"), start=1):
            ttk.Label(inner, text=t(key), style="CardMuted.TLabel").grid(row=0, column=column, padx=12, pady=(0, 6))
        for row, (key, prefix) in enumerate((("r_owner_row", "u"), ("r_group_row", "g"), ("r_others_row", "o")), start=1):
            ttk.Label(inner, text=t(key), style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
            for column, perm in enumerate("rwx", start=1):
                ttk.Checkbutton(inner, style="Card.TCheckbutton", variable=self.checks[prefix + perm],
                                command=self.update_octal_from_checks).grid(row=row, column=column)
        ttk.Separator(inner).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(10, 8))
        ttk.Label(inner, text=t("r_special"), style="CardMuted.TLabel").grid(row=5, column=0, columnspan=4, sticky="w")
        special = ttk.Frame(inner, style="Plain.TFrame")
        special.grid(row=6, column=0, columnspan=4, sticky="w", pady=(4, 0))
        for key, label_key in (("suid", "sp_suid"), ("sgid", "sp_sgid"), ("sticky", "sp_sticky")):
            ttk.Checkbutton(special, text=t(label_key), style="Card.TCheckbutton", variable=self.checks[key],
                            command=self.update_octal_from_checks).pack(side="left", padx=(0, 14))

        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(16, 8))
        ttk.Button(actions, text=t("r_apply_all"), style="Accent.TButton",
                   command=self.apply_group_and_permissions).pack(side="left")
        ttk.Button(actions, text=t("r_apply_group"), command=self.apply_group_only).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text=t("r_apply_safe"), command=self.group_only_preset).pack(side="left", padx=(8, 0))
        ttk.Label(page, text=t("r_hint"), style="Muted.TLabel", wraplength=840, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w")

    def choose_path(self, directory):
        if directory:
            path = filedialog.askdirectory(title=t("dlg_choose_folder"))
        else:
            path = filedialog.askopenfilename(title=t("dlg_choose_file"))
        if path:
            self.path_var.set(path)
            self.load_permissions()

    BITS = {"ur": stat.S_IRUSR, "uw": stat.S_IWUSR, "ux": stat.S_IXUSR,
            "gr": stat.S_IRGRP, "gw": stat.S_IWGRP, "gx": stat.S_IXGRP,
            "or": stat.S_IROTH, "ow": stat.S_IWOTH, "ox": stat.S_IXOTH,
            "suid": stat.S_ISUID, "sgid": stat.S_ISGID, "sticky": stat.S_ISVTX}

    def checks_to_mode(self):
        mode = 0
        for key, bit in self.BITS.items():
            if self.checks[key].get():
                mode |= bit
        return mode

    def set_checks_from_mode(self, mode):
        for key, bit in self.BITS.items():
            self.checks[key].set(bool(mode & bit))

    def update_octal_from_checks(self):
        self.syncing = True
        self.octal_var.set(be.format_octal(self.checks_to_mode()))
        self.syncing = False

    def update_checks_from_octal(self, *_):
        if self.syncing:
            return
        try:
            mode = be.parse_mode(self.octal_var.get())
        except ValueError:
            return
        self.syncing = True
        self.set_checks_from_mode(mode)
        self.syncing = False

    def existing_path(self):
        path = self.path_var.get().strip()
        if not path or not os.path.exists(path):
            self.message(t("need_path"))
            return None
        return path

    def load_permissions(self):
        path = self.path_var.get().strip()
        if not path or not os.path.exists(path):
            return
        try:
            owner, group, mode = be.owner_group_of(path)
        except OSError as exc:
            self.error(str(exc))
            return
        self.owner_var.set(owner)
        if group in self.group_combo["values"]:
            self.group_var.set(group)
        self.mode_var.set(stat.filemode(os.stat(path).st_mode))
        self.syncing = True
        self.set_checks_from_mode(mode)
        self.octal_var.set(be.format_octal(mode))
        self.syncing = False
        self.type_var.set(t("type_folder") if os.path.isdir(path) else t("type_file"))
        self.status.set(t("ok_loaded"))

    def apply_group_and_permissions(self):
        path = self.existing_path()
        if not path:
            return
        if not self.group_var.get().strip():
            self.message(t("select_group_first"))
            return
        try:
            mode = be.parse_mode(self.octal_var.get())
            owner = be.owner_group_of(path)[0]
        except (ValueError, OSError) as exc:
            self.error(str(exc))
            return
        group = self.group_var.get().strip()
        if self.act(be.apply_owner_group_mode, path, owner, group, mode,
                    ok=t("ok_saved", owner=owner, group=group, mode=be.format_octal(mode))):
            self.load_permissions()

    def apply_group_only(self):
        path = self.existing_path()
        if not path:
            return
        if not self.group_var.get().strip():
            self.message(t("select_group_first"))
            return
        try:
            owner = be.owner_group_of(path)[0]
        except OSError as exc:
            self.error(str(exc))
            return
        group = self.group_var.get().strip()
        if self.act(be.apply_owner_group_mode, path, owner, group, None,
                    ok=t("ok_group_changed", owner=owner, group=group)):
            self.load_permissions()

    def group_only_preset(self):
        path = self.existing_path()
        if not path:
            return
        if not self.group_var.get().strip():
            self.message(t("select_group_first"))
            return
        group = self.group_var.get().strip()
        is_dir = os.path.isdir(path)
        mode = 0o2770 if is_dir else 0o660
        what = t("safe_dir") if is_dir else t("safe_file")
        if not self.confirm(t("safe_confirm", group=group, what=what)):
            return
        try:
            owner = be.owner_group_of(path)[0]
        except OSError as exc:
            self.error(str(exc))
            return
        if self.act(be.apply_owner_group_mode, path, owner, group, mode,
                    ok=t("ok_safe", owner=owner, group=group, mode=be.format_octal(mode))):
            self.load_permissions()

    # ------------------------------------------------------------------
    # Seite: ACL
    # ------------------------------------------------------------------
    def build_acl(self, page):
        target, inner = self.card(page, t("a_target"))
        target.pack(fill="x", pady=(0, 14))
        entry = ttk.Entry(inner, textvariable=self.acl_path_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: self.load_acl())
        ttk.Button(inner, text=t("btn_file"), command=lambda: self.choose_acl_path(False)).pack(side="left", padx=(10, 0))
        ttk.Button(inner, text=t("btn_folder"), command=lambda: self.choose_acl_path(True)).pack(side="left", padx=(6, 0))

        who, inner = self.card(page, t("a_who"))
        who.pack(fill="x", pady=(0, 14))
        row1 = ttk.Frame(inner, style="Plain.TFrame")
        row1.pack(fill="x")
        for text_key, value in (("a_group", "g"), ("a_user", "u")):
            ttk.Radiobutton(row1, text=t(text_key), value=value, variable=self.acl_kind, style="Card.TRadiobutton",
                            command=self.refresh_group_combos).pack(side="left", padx=(0, 14))
        self.acl_combo = ttk.Combobox(row1, textvariable=self.acl_group_var, state="readonly", width=30)
        self.acl_combo.pack(side="left", padx=(6, 0))
        row2 = ttk.Frame(inner, style="Plain.TFrame")
        row2.pack(fill="x", pady=(12, 0))
        for key, var in (("a_r", self.acl_read), ("a_w", self.acl_write), ("a_x", self.acl_execute)):
            ttk.Checkbutton(row2, text=t(key), variable=var, style="Card.TCheckbutton").pack(side="left", padx=(0, 16))
        ttk.Checkbutton(row2, text=t("a_recursive"), variable=self.acl_recursive, style="Card.TCheckbutton").pack(
            side="left", padx=(16, 0))

        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=(0, 12))
        ttk.Button(actions, text=t("a_set"), style="Accent.TButton", command=self.apply_acl).pack(side="left")
        ttk.Button(actions, text=t("a_inherit"), command=self.apply_default_acl).pack(side="left", padx=(8, 0))
        self.menubutton(actions, "a_remove_menu", [("a_remove_entry", self.remove_entry_acl),
                                                   ("a_remove_all", self.remove_all_acl)]).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text=t("a_load"), command=self.load_acl).pack(side="left", padx=(8, 0))

        out = ttk.Frame(page, style="Card.TFrame")
        out.pack(fill="both", expand=True)
        self.acl_text = tk.Text(out, height=10, state="disabled", wrap="none")
        theme.style_text(self.acl_text, self.p, mono=True)
        scroll = ttk.Scrollbar(out, orient="vertical", command=self.acl_text.yview)
        self.acl_text.configure(yscrollcommand=scroll.set)
        self.acl_text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)
        ttk.Label(page, text=t("a_hint"), style="Muted.TLabel", wraplength=900, justify="left").pack(
            fill="x", pady=(10, 0))

    def acl_inputs(self, need_group=True, need_perms=True):
        path = self.acl_path_var.get().strip()
        if not path or not os.path.exists(path):
            self.message(t("need_path"))
            return None
        name = self.acl_group_var.get().strip()
        known = be.list_groups() if self.acl_kind.get() == "g" else be.list_users()
        if need_group and name not in known:
            self.error(t("a_pick_error"))
            return None
        perms = None
        if need_perms:
            try:
                perms = be.perms_string(self.acl_read.get(), self.acl_write.get(), self.acl_execute.get())
            except ValueError as exc:
                self.error(str(exc))
                return None
        return path, name, perms

    def kind_label(self):
        return t("a_group") if self.acl_kind.get() == "g" else t("a_user")

    def apply_acl(self):
        data = self.acl_inputs()
        if not data:
            return
        path, name, perms = data
        if self.act(be.acl_apply, path, name, perms, False, self.acl_recursive.get(), self.acl_kind.get(),
                    ok=t("ok_acl_set", kind=self.kind_label(), name=name, perms=perms)):
            self.load_acl()

    def apply_default_acl(self):
        data = self.acl_inputs()
        if not data:
            return
        path, name, perms = data
        if not os.path.isdir(path):
            self.error(t("acl_dir_only"))
            return
        if self.act(be.acl_apply, path, name, perms, True, self.acl_recursive.get(), self.acl_kind.get(),
                    ok=t("ok_acl_inherit", kind=self.kind_label(), name=name, perms=perms, path=path)):
            self.load_acl()

    def remove_entry_acl(self):
        data = self.acl_inputs(need_perms=False)
        if not data:
            return
        path, name, _ = data
        if not self.confirm(t("a_remove_confirm", kind=self.kind_label(), name=name, path=path), danger=True):
            return
        if self.act(be.acl_remove_entry, path, name, self.acl_recursive.get(), self.acl_kind.get(),
                    ok=t("ok_acl_removed", kind=self.kind_label(), name=name)):
            self.load_acl()

    def remove_all_acl(self):
        data = self.acl_inputs(need_group=False, need_perms=False)
        if not data:
            return
        path = data[0]
        if not self.confirm(t("a_remove_all_confirm", path=path), danger=True):
            return
        if self.act(be.acl_remove_all, path, self.acl_recursive.get(), ok=t("ok_acl_all_removed")):
            self.load_acl()

    def load_acl(self):
        path = self.acl_path_var.get().strip()
        if not path or not os.path.exists(path):
            self.set_text(self.acl_text, "")
            return
        try:
            self.set_text(self.acl_text, self.run_blocking(be.acl_read, path))
            self.status.set(t("ok_acl_loaded"))
        except Exception as exc:
            self.set_text(self.acl_text, str(exc))

    def choose_acl_path(self, directory):
        if directory:
            path = filedialog.askdirectory(title=t("dlg_choose_folder"))
        else:
            path = filedialog.askopenfilename(title=t("dlg_choose_file"))
        if path:
            self.acl_path_var.set(path)
            self.load_acl()

    # ------------------------------------------------------------------
    # Seite: Protokoll
    # ------------------------------------------------------------------
    def build_log(self, page):
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 14))
        ttk.Button(bar, text="⟳", width=3, style="Icon.TButton", command=self.refresh_log).pack(side="left")
        ttk.Button(bar, text=t("l_copy"), command=self.copy_log).pack(side="left", padx=(8, 0))
        ttk.Label(bar, text=t("l_file", path="~/.local/state/linux-admin-gui/actions.log"),
                  style="Muted.TLabel").pack(side="right")
        out = ttk.Frame(page, style="Card.TFrame")
        out.pack(fill="both", expand=True)
        self.log_text = tk.Text(out, state="disabled", wrap="none")
        theme.style_text(self.log_text, self.p, mono=True)
        scroll = ttk.Scrollbar(out, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scroll.pack(side="right", fill="y", padx=(0, 1), pady=1)

    def refresh_log(self):
        if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
            return
        self.set_text(self.log_text, be.read_log(500) or t("l_empty"))
        self.log_text.see("end")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(be.read_log(500))
        self.status.set(t("l_copied"))

    # ------------------------------------------------------------------
    # Seite: Über
    # ------------------------------------------------------------------
    def build_about(self, page):
        page.columnconfigure(0, weight=1)
        outer, inner = self.card(page)
        outer.grid(row=0, column=0, sticky="n", pady=(6, 0))
        outer.configure(padding=(40, 34))
        head = ttk.Frame(inner, style="Plain.TFrame")
        head.pack(anchor="w")
        self.logo(head, 72, self.p["surface"]).pack(side="left")
        titles = ttk.Frame(head, style="Plain.TFrame")
        titles.pack(side="left", padx=20)
        ttk.Label(titles, text=APP_NAME, style="H1.TLabel").pack(anchor="w")
        ttk.Label(titles, text=t("about_version", version=VERSION), style="CardMuted.TLabel").pack(anchor="w")
        ttk.Label(inner, text=t("about_tagline"), style="CardTitle.TLabel").pack(anchor="w", pady=(22, 6))
        ttk.Label(inner, text=t("about_overview"), style="Card.TLabel", wraplength=620, justify="left").pack(anchor="w")
        ttk.Label(inner, text=t("about_features_title"), style="CardTitle.TLabel").pack(anchor="w", pady=(20, 6))
        for key in ("about_f1", "about_f2", "about_f3", "about_f4", "about_f5", "about_f6"):
            ttk.Label(inner, text="•  " + t(key), style="Card.TLabel", wraplength=620, justify="left").pack(
                anchor="w", pady=1)
        ttk.Separator(inner).pack(fill="x", pady=(22, 14))
        ttk.Label(inner, text=t("about_copyright", year=YEAR, author=AUTHOR), style="Card.TLabel",
                  font=(self.font, 10, "bold")).pack(anchor="w")
        ttk.Label(inner, text=t("about_stack"), style="CardMuted.TLabel").pack(anchor="w", pady=(2, 0))


def main():
    App().run()


if __name__ == "__main__":
    main()
