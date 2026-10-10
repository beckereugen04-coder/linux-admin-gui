"""Helles und dunkles Design für ttk und klassische Tk-Widgets."""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTES = {
    "light": {
        "bg": "#f4f6fa", "surface": "#ffffff", "surface_alt": "#f7f9fc", "field_bg": "#ffffff",
        "text": "#1e293b", "muted": "#64748b", "border": "#d5dbe5",
        "button": "#e9edf4", "button_hover": "#dde3ee",
        "accent": "#2563eb", "accent_hover": "#1d4ed8", "accent_fg": "#ffffff",
        "select_bg": "#dbe7ff", "select_fg": "#0f172a", "danger": "#dc2626",
        "sidebar": "#1e293b", "sidebar_text": "#cbd5e1", "sidebar_hover": "#2c3b57", "sidebar_title": "#ffffff",
    },
    "dark": {
        "bg": "#171b22", "surface": "#1f242d", "surface_alt": "#232933", "field_bg": "#161a21",
        "text": "#e5e9f0", "muted": "#94a3b8", "border": "#343b48",
        "button": "#2a313c", "button_hover": "#343c49",
        "accent": "#2f6fe4", "accent_hover": "#4a85ee", "accent_fg": "#ffffff",
        "select_bg": "#2d4a7c", "select_fg": "#ffffff", "danger": "#f87171",
        "sidebar": "#11141a", "sidebar_text": "#aab4c5", "sidebar_hover": "#1d232d", "sidebar_title": "#ffffff",
    },
}
FONT_CANDIDATES = ("Inter", "Noto Sans", "Ubuntu", "Cantarell", "Segoe UI", "DejaVu Sans")


def pick_font(root):
    families = set(tkfont.families(root))
    for name in FONT_CANDIDATES:
        if name in families:
            return name
    return "TkDefaultFont"


def apply(root, name):
    """Konfiguriert alle ttk-Stile und gibt die Palette zurück."""
    p = PALETTES.get(name, PALETTES["light"])
    style = ttk.Style(root)
    style.theme_use("clam")
    fam = pick_font(root)
    for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(fname).configure(family=fam, size=10)
        except tk.TclError:
            pass
    try:
        tkfont.nametofont("TkMenuFont").configure(family=fam, size=11)
    except tk.TclError:
        pass
    root.configure(bg=p["bg"])
    flat = dict(lightcolor=p["border"], darkcolor=p["border"], bordercolor=p["border"])

    style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["field_bg"],
                    troughcolor=p["bg"], focuscolor=p["accent"], selectbackground=p["select_bg"],
                    selectforeground=p["select_fg"], font=(fam, 10), **flat)
    style.configure("TFrame", background=p["bg"])
    style.configure("Sidebar.TFrame", background=p["sidebar"])
    style.configure("Card.TFrame", background=p["surface"], relief="solid", borderwidth=1, **flat)
    style.configure("Plain.TFrame", background=p["surface"], borderwidth=0, relief="flat")

    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Card.TLabel", background=p["surface"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("CardMuted.TLabel", background=p["surface"], foreground=p["muted"])
    style.configure("Title.TLabel", background=p["bg"], font=(fam, 18, "bold"))
    style.configure("CardTitle.TLabel", background=p["surface"], font=(fam, 11, "bold"))
    style.configure("H1.TLabel", background=p["surface"], font=(fam, 20, "bold"))
    style.configure("Sidebar.TLabel", background=p["sidebar"], foreground=p["sidebar_text"])
    style.configure("SidebarTitle.TLabel", background=p["sidebar"], foreground=p["sidebar_title"], font=(fam, 12, "bold"))
    style.configure("Status.TLabel", background=p["surface"], foreground=p["muted"], padding=(14, 6))

    style.configure("TButton", padding=(14, 7), relief="flat", borderwidth=1, focusthickness=0,
                    background=p["button"], foreground=p["text"], **flat)
    style.map("TButton", background=[("pressed", p["button_hover"]), ("active", p["button_hover"])],
              bordercolor=[("focus", p["accent"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    bordercolor=p["accent"], lightcolor=p["accent"], darkcolor=p["accent"])
    style.map("Accent.TButton", background=[("pressed", p["accent_hover"]), ("active", p["accent_hover"])],
              bordercolor=[("active", p["accent_hover"])])
    style.configure("Danger.TButton", foreground=p["danger"])
    style.configure("Icon.TButton", padding=(11, 7), font=(fam, 12))
    style.configure("Nav.TButton", background=p["sidebar"], foreground=p["sidebar_text"], anchor="w",
                    padding=(20, 11), borderwidth=0, bordercolor=p["sidebar"], lightcolor=p["sidebar"],
                    darkcolor=p["sidebar"], font=(fam, 11))
    style.map("Nav.TButton", background=[("active", p["sidebar_hover"])], bordercolor=[("focus", p["sidebar"])])
    style.configure("NavActive.TButton", background=p["accent"], foreground=p["accent_fg"], anchor="w",
                    padding=(20, 11), borderwidth=0, bordercolor=p["accent"], lightcolor=p["accent"],
                    darkcolor=p["accent"], font=(fam, 11, "bold"))
    style.map("NavActive.TButton", background=[("active", p["accent_hover"])])

    style.configure("TMenubutton", padding=(14, 7), relief="flat", background=p["button"],
                    foreground=p["text"], arrowcolor=p["muted"], **flat)
    style.map("TMenubutton", background=[("active", p["button_hover"])])

    style.configure("TEntry", padding=6, fieldbackground=p["field_bg"], foreground=p["text"], insertcolor=p["text"], **flat)
    style.map("TEntry", bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
              darkcolor=[("focus", p["accent"])])
    style.configure("TCombobox", padding=6, fieldbackground=p["field_bg"], foreground=p["text"],
                    arrowcolor=p["muted"], background=p["button"], **flat)
    style.map("TCombobox", fieldbackground=[("readonly", p["field_bg"])], foreground=[("readonly", p["text"])],
              bordercolor=[("focus", p["accent"])], selectbackground=[("readonly", p["field_bg"])],
              selectforeground=[("readonly", p["text"])])
    root.option_add("*TCombobox*Listbox.background", p["surface"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["accent_fg"])

    for base, bg in (("TCheckbutton", p["bg"]), ("Card.TCheckbutton", p["surface"]),
                     ("TRadiobutton", p["bg"]), ("Card.TRadiobutton", p["surface"])):
        style.configure(base, background=bg, foreground=p["text"], indicatorbackground=p["field_bg"],
                        indicatorforeground=p["accent_fg"], focuscolor=bg, **flat)
        style.map(base, background=[("active", bg)],
                  indicatorbackground=[("selected", p["accent"]), ("active", p["button_hover"])])

    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                    rowheight=32, borderwidth=0, relief="flat")
    style.map("Treeview", background=[("selected", p["select_bg"])], foreground=[("selected", p["select_fg"])])
    style.configure("Treeview.Heading", background=p["surface_alt"], foreground=p["muted"], relief="flat",
                    padding=(10, 8), font=(fam, 10, "bold"), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", p["button"])])

    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=p["border"], troughcolor=p["surface"],
                        bordercolor=p["surface"], lightcolor=p["border"], darkcolor=p["border"],
                        arrowcolor=p["muted"], gripcount=0, relief="flat")
        style.map(f"{orient}.TScrollbar", background=[("active", p["muted"])])
    style.configure("TSeparator", background=p["border"])
    style.configure("TLabelframe", background=p["surface"], **flat)
    return p


def style_menu(menu, p):
    menu.configure(bg=p["surface"], fg=p["text"], activebackground=p["accent"], activeforeground=p["accent_fg"],
                   bd=0, relief="flat", activeborderwidth=0, disabledforeground=p["muted"],
                   selectcolor=p["accent"], tearoff=0)
    return menu


def style_text(widget, p, mono=False):
    widget.configure(bg=p["surface"], fg=p["text"], insertbackground=p["text"], selectbackground=p["select_bg"],
                     selectforeground=p["select_fg"], relief="flat", borderwidth=0, highlightthickness=0, padx=10, pady=8)
    if mono:
        widget.configure(font=("DejaVu Sans Mono", 10))
    return widget
