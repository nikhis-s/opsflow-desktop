"""Central dark theme and reusable styling for OpsFlow."""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

COLORS = {
    "bg": "#070D17",
    "sidebar": "#0A1220",
    "sidebar_hover": "#101C2F",
    "surface": "#0D1727",
    "card": "#101C2E",
    "card_alt": "#142238",
    "card_soft": "#0C1626",
    "border": "#203049",
    "border_soft": "#18263B",
    "text": "#E8F0FA",
    "text_soft": "#C7D4E6",
    "muted": "#8DA2BE",
    "subtle": "#5E7490",
    "accent": "#22D3EE",
    "accent_hover": "#67E8F9",
    "accent_deep": "#0891B2",
    "blue": "#5B8DEF",
    "green": "#34D399",
    "green_deep": "#065F46",
    "amber": "#FBBF24",
    "amber_deep": "#78350F",
    "red": "#F87171",
    "red_deep": "#7F1D1D",
    "purple": "#A78BFA",
    "purple_deep": "#4C1D95",
    "grid": "#1A2940",
    "selection": "#173A56",
}

STATUS_COLORS = {
    "Open": COLORS["accent"],
    "In Progress": COLORS["blue"],
    "Pending": COLORS["amber"],
    "Resolved": COLORS["green"],
    "Closed": COLORS["subtle"],
}

PRIORITY_COLORS = {
    "Critical": COLORS["red"],
    "High": "#FB923C",
    "Medium": COLORS["amber"],
    "Low": COLORS["muted"],
}

SLA_COLORS = {
    "On track": COLORS["green"],
    "At risk": COLORS["amber"],
    "Breached": COLORS["red"],
    "Met": COLORS["green"],
    "Missed": COLORS["red"],
}

FONTS: dict[str, tkfont.Font] = {}


def _font_family(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for candidate in ("Segoe UI Variable", "Segoe UI", "Inter", "Helvetica Neue", "Arial"):
        if candidate in available:
            return candidate
    return "TkDefaultFont"


def _mono_family(root: tk.Misc) -> str:
    available = set(tkfont.families(root))
    for candidate in ("Cascadia Mono", "Consolas", "JetBrains Mono", "Courier New"):
        if candidate in available:
            return candidate
    return "TkFixedFont"


def mix(color_a: str, color_b: str, factor: float) -> str:
    """Blend two hex colors (0.0 = color_a, 1.0 = color_b)."""
    a = tuple(int(color_a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(color_b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    result = tuple(round(a[i] + (b[i] - a[i]) * factor) for i in range(3))
    return "#" + "".join(f"{value:02x}" for value in result)


def apply_theme(root: tk.Tk) -> ttk.Style:
    family = _font_family(root)
    mono = _mono_family(root)
    for name, size, weight in (
        ("body", 10, "normal"),
        ("small", 9, "normal"),
        ("tiny", 8, "normal"),
        ("medium", 10, "bold"),
        ("semibold", 11, "bold"),
        ("h1", 23, "bold"),
        ("h2", 16, "bold"),
        ("h3", 13, "bold"),
        ("kpi", 26, "bold"),
        ("mono", 9, "normal"),
    ):
        FONTS[name] = tkfont.Font(root=root, family=mono if name == "mono" else family,
                                  size=size, weight=weight)

    root.configure(bg=COLORS["bg"])
    root.option_add("*Font", FONTS["body"])
    root.option_add("*Background", COLORS["bg"])
    root.option_add("*Foreground", COLORS["text"])
    root.option_add("*selectBackground", COLORS["selection"])
    root.option_add("*selectForeground", COLORS["text"])
    root.option_add("*TCombobox*Listbox.background", COLORS["surface"])
    root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", COLORS["selection"])
    root.option_add("*TCombobox*Listbox.selectForeground", COLORS["text"])
    root.option_add("*Menu.background", COLORS["surface"])
    root.option_add("*Menu.foreground", COLORS["text"])
    root.option_add("*Menu.activeBackground", COLORS["card_alt"])
    root.option_add("*Menu.activeForeground", COLORS["accent"])

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"],
                    font=FONTS["body"], borderwidth=0)
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("App.TFrame", background=COLORS["bg"])
    style.configure("Surface.TFrame", background=COLORS["surface"])
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("CardAlt.TFrame", background=COLORS["card_alt"])
    style.configure("Sidebar.TFrame", background=COLORS["sidebar"])

    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"])
    style.configure("Subtle.TLabel", background=COLORS["bg"], foreground=COLORS["subtle"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("CardSubtle.TLabel", background=COLORS["card"], foreground=COLORS["subtle"])
    style.configure("Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("SurfaceMuted.TLabel", background=COLORS["surface"], foreground=COLORS["muted"])
    style.configure("Accent.TLabel", background=COLORS["bg"], foreground=COLORS["accent"])
    style.configure("CardAccent.TLabel", background=COLORS["card"], foreground=COLORS["accent"])
    style.configure("Success.TLabel", background=COLORS["bg"], foreground=COLORS["green"])
    style.configure("Danger.TLabel", background=COLORS["bg"], foreground=COLORS["red"])
    style.configure("Warning.TLabel", background=COLORS["bg"], foreground=COLORS["amber"])
    style.configure("PageTitle.TLabel", background=COLORS["bg"], foreground=COLORS["text"],
                    font=FONTS["h1"])
    style.configure("PageSubtitle.TLabel", background=COLORS["bg"], foreground=COLORS["muted"],
                    font=FONTS["small"])
    style.configure("SectionTitle.TLabel", background=COLORS["bg"], foreground=COLORS["text"],
                    font=FONTS["h2"])
    style.configure("CardTitle.TLabel", background=COLORS["card"], foreground=COLORS["text"],
                    font=FONTS["semibold"])
    style.configure("CardHeading.TLabel", background=COLORS["card"], foreground=COLORS["text"],
                    font=FONTS["h2"])
    style.configure("CardKpi.TLabel", background=COLORS["card"], foreground=COLORS["text"],
                    font=FONTS["kpi"])
    style.configure("CardEyebrow.TLabel", background=COLORS["card"], foreground=COLORS["subtle"],
                    font=FONTS["tiny"])

    # Buttons
    style.configure(
        "Accent.TButton",
        background=COLORS["accent"], foreground="#04141C",
        borderwidth=0, focusthickness=0, padding=(16, 9),
        font=FONTS["medium"],
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", COLORS["accent_deep"]), ("active", COLORS["accent_hover"]),
                    ("disabled", COLORS["border"])],
        foreground=[("disabled", COLORS["subtle"])],
    )
    style.configure(
        "Secondary.TButton",
        background=COLORS["card_alt"], foreground=COLORS["text_soft"],
        borderwidth=1, bordercolor=COLORS["border"], lightcolor=COLORS["border"],
        darkcolor=COLORS["border"], padding=(14, 8), font=FONTS["small"],
    )
    style.map(
        "Secondary.TButton",
        background=[("pressed", COLORS["surface"]), ("active", "#1A2B45"),
                    ("disabled", COLORS["card"])],
        foreground=[("disabled", COLORS["subtle"])],
        bordercolor=[("active", COLORS["accent_deep"])],
    )
    style.configure(
        "Ghost.TButton",
        background=COLORS["card"], foreground=COLORS["muted"],
        borderwidth=0, padding=(10, 7), font=FONTS["small"],
    )
    style.map("Ghost.TButton",
              background=[("active", COLORS["card_alt"])],
              foreground=[("active", COLORS["accent"]), ("disabled", COLORS["subtle"])])
    style.configure(
        "Danger.TButton",
        background=COLORS["red_deep"], foreground="#FECACA",
        borderwidth=0, padding=(14, 8), font=FONTS["small"],
    )
    style.map("Danger.TButton", background=[("active", "#991B1B"), ("pressed", "#7F1D1D")])
    style.configure(
        "Link.TButton",
        background=COLORS["card"], foreground=COLORS["accent"],
        borderwidth=0, padding=(4, 2), font=FONTS["small"],
    )
    style.map("Link.TButton", background=[("active", COLORS["card"])],
              foreground=[("active", COLORS["accent_hover"])])

    # Inputs
    style.configure(
        "TEntry",
        fieldbackground=COLORS["card_soft"], foreground=COLORS["text"],
        insertcolor=COLORS["accent"], bordercolor=COLORS["border"],
        lightcolor=COLORS["border"], darkcolor=COLORS["border"],
        padding=(10, 7), relief="flat",
    )
    style.map("TEntry",
              bordercolor=[("focus", COLORS["accent_deep"])],
              lightcolor=[("focus", COLORS["accent_deep"])],
              darkcolor=[("focus", COLORS["accent_deep"])],
              fieldbackground=[("disabled", COLORS["surface"]),
                               ("readonly", COLORS["surface"])])
    style.configure(
        "Search.TEntry",
        fieldbackground=COLORS["card_soft"], foreground=COLORS["text"],
        insertcolor=COLORS["accent"], bordercolor=COLORS["border_soft"],
        lightcolor=COLORS["border_soft"], darkcolor=COLORS["border_soft"],
        padding=(12, 8),
    )
    style.map("Search.TEntry", bordercolor=[("focus", COLORS["accent_deep"])],
              lightcolor=[("focus", COLORS["accent_deep"])],
              darkcolor=[("focus", COLORS["accent_deep"])])

    style.configure(
        "TCombobox",
        fieldbackground=COLORS["card_soft"], background=COLORS["card_alt"],
        foreground=COLORS["text"], arrowcolor=COLORS["muted"],
        bordercolor=COLORS["border"], lightcolor=COLORS["border"],
        darkcolor=COLORS["border"], padding=(8, 7), relief="flat",
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["card_soft"]), ("disabled", COLORS["surface"])],
        foreground=[("readonly", COLORS["text"]), ("disabled", COLORS["subtle"])],
        background=[("active", COLORS["card_alt"]), ("pressed", COLORS["surface"])],
        arrowcolor=[("active", COLORS["accent"])],
        bordercolor=[("focus", COLORS["accent_deep"])],
    )

    style.configure(
        "Treeview",
        background=COLORS["card_soft"], fieldbackground=COLORS["card_soft"],
        foreground=COLORS["text_soft"], borderwidth=0, relief="flat",
        rowheight=35, font=FONTS["small"],
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["surface"], foreground=COLORS["muted"],
        relief="flat", borderwidth=0, padding=(10, 9), font=FONTS["tiny"],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", COLORS["card_alt"])],
        foreground=[("active", COLORS["text"])],
    )
    style.map(
        "Treeview",
        background=[("selected", COLORS["selection"])],
        foreground=[("selected", COLORS["text"])],
    )
    style.layout("Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"}),
    ])

    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["card_alt"], troughcolor=COLORS["card_soft"],
        bordercolor=COLORS["card_soft"], arrowcolor=COLORS["subtle"],
        lightcolor=COLORS["card_alt"], darkcolor=COLORS["card_alt"],
        width=12, arrowsize=10,
    )
    style.map("Vertical.TScrollbar", background=[("active", COLORS["border"])])
    style.configure(
        "Horizontal.TScrollbar",
        background=COLORS["card_alt"], troughcolor=COLORS["card_soft"],
        bordercolor=COLORS["card_soft"], arrowcolor=COLORS["subtle"],
        lightcolor=COLORS["card_alt"], darkcolor=COLORS["card_alt"],
        arrowsize=10,
    )

    style.configure("TSeparator", background=COLORS["border_soft"])
    style.configure("TCheckbutton", background=COLORS["card"], foreground=COLORS["text_soft"],
                    font=FONTS["small"], focuscolor=COLORS["accent"])
    style.map("TCheckbutton", background=[("active", COLORS["card"])],
              indicatorcolor=[("selected", COLORS["accent"])])
    style.configure("TRadiobutton", background=COLORS["card"], foreground=COLORS["text_soft"])

    style.configure("TNotebook", background=COLORS["card"], borderwidth=0,
                    tabmargins=(0, 0, 0, 0))
    style.configure("TNotebook.Tab", background=COLORS["card_soft"],
                    foreground=COLORS["muted"], padding=(16, 8),
                    font=FONTS["small"], borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", COLORS["card_alt"]), ("active", COLORS["surface"])],
              foreground=[("selected", COLORS["accent"]), ("active", COLORS["text"])])

    style.configure("TProgressbar", background=COLORS["accent"],
                    troughcolor=COLORS["card_soft"], borderwidth=0, thickness=6)
    return style
