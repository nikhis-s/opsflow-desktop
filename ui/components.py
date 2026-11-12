"""Reusable Tkinter/ttk components used across all OpsFlow screens."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Sequence

from ui.theme import (
    COLORS, FONTS, PRIORITY_COLORS, SLA_COLORS, STATUS_COLORS, mix, px,
)


def flat_button(parent: tk.Misc, text: str, command: Callable[[], None],
                kind: str = "secondary", **kwargs) -> ttk.Button:
    style = {
        "primary": "Accent.TButton",
        "secondary": "Secondary.TButton",
        "ghost": "Ghost.TButton",
        "danger": "Danger.TButton",
        "link": "Link.TButton",
    }.get(kind, "Secondary.TButton")
    return ttk.Button(parent, text=text, command=command, style=style, cursor="hand2", **kwargs)


class Page(tk.Frame):
    """Base page with a consistent background and lifecycle hook."""

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, bg=COLORS["bg"])
        self.app = app
        self._jobs: list[str] = []
        self.bind("<Destroy>", self._on_destroy, add="+")

    def after(self, ms: int, func: Any = None, *args: Any) -> str:
        """Schedule a callback and remember it so it can be cancelled."""
        if func is None or not callable(func):
            return super().after(ms, func, *args)
        holder: list[str] = []

        def _run() -> None:
            if holder and holder[0] in self._jobs:
                self._jobs.remove(holder[0])
            func(*args)

        job = super().after(ms, _run)
        holder.append(job)
        self._jobs.append(job)
        return job

    def after_cancel(self, job: str) -> None:
        try:
            super().after_cancel(job)
        except tk.TclError:
            pass
        if job in self._jobs:
            self._jobs.remove(job)

    def _on_destroy(self, event: tk.Event) -> None:
        """Cancel pending timers so nothing fires against a dead widget."""
        if event.widget is not self:
            return
        for job in list(self._jobs):
            try:
                super().after_cancel(job)
            except tk.TclError:
                pass
        self._jobs.clear()

    def on_show(self) -> None:  # pragma: no cover - overridden by pages
        pass

    def refresh(self) -> None:
        self.on_show()


class Card(tk.Frame):
    def __init__(self, parent: tk.Misc, padding: int | tuple[int, int] = 18,
                 accent: str | None = None, bg: str | None = None,
                 border: str | None = None, **kwargs):
        self.card_bg = bg or COLORS["card"]
        super().__init__(
            parent, bg=self.card_bg, bd=0, highlightthickness=1,
            highlightbackground=border or COLORS["border"],
            highlightcolor=border or COLORS["border"], **kwargs,
        )
        self._padding = padding
        if accent:
            tk.Frame(self, bg=accent, height=px(3)).pack(fill="x", side="top")
        self.body = tk.Frame(self, bg=self.card_bg)
        if isinstance(padding, tuple):
            padx, pady = padding
        else:
            padx = pady = padding
        self.body.pack(fill="both", expand=True, padx=px(padx), pady=px(pady))


class KpiCard(Card):
    """Metric card with an accent rail, icon tile, value and context line."""

    def __init__(self, parent: tk.Misc, label: str, accent: str,
                 icon: str = "•", hint: str = ""):
        super().__init__(parent, padding=(18, 15), accent=accent)
        self.value_var = tk.StringVar(value="—")
        self.hint_var = tk.StringVar(value=hint)
        top = tk.Frame(self.body, bg=self.card_bg)
        top.pack(fill="x")
        tile_bg = mix(self.card_bg, accent, 0.16)
        icon_tile = tk.Frame(top, bg=tile_bg, width=px(38), height=px(38))
        icon_tile.pack(side="left")
        icon_tile.pack_propagate(False)
        tk.Label(icon_tile, text=icon, bg=tile_bg, fg=accent,
                 font=(FONTS["h3"].actual("family"), 14, "bold")).pack(expand=True)
        tk.Label(top, text=label.upper(), bg=self.card_bg, fg=COLORS["muted"],
                 font=FONTS["micro"], anchor="w").pack(side="left", padx=(px(11), 0))
        tk.Label(self.body, textvariable=self.value_var, bg=self.card_bg,
                 fg=COLORS["text"], font=FONTS["kpi"], anchor="w").pack(
            fill="x", pady=(px(9), 0))
        tk.Label(self.body, textvariable=self.hint_var, bg=self.card_bg,
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").pack(fill="x")

    def set(self, value: str | int, hint: str | None = None) -> None:
        self.value_var.set(str(value))
        if hint is not None:
            self.hint_var.set(hint)


class SectionHeader(tk.Frame):
    def __init__(self, parent: tk.Misc, title: str, subtitle: str = "",
                 bg: str | None = None):
        background = bg or COLORS["bg"]
        super().__init__(parent, bg=background)
        text = tk.Frame(self, bg=background)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=background, fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(text, text=subtitle, bg=background, fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(fill="x", pady=(px(3), 0))
        self.actions = tk.Frame(self, bg=background)
        self.actions.pack(side="right")


class Badge(tk.Label):
    _TONES = {
        "neutral": (COLORS["muted"], COLORS["card_alt"]),
        "accent": (COLORS["accent"], mix(COLORS["card"], COLORS["accent"], 0.14)),
        "info": (COLORS["blue"], mix(COLORS["card"], COLORS["blue"], 0.15)),
        "success": ("#86EFAC", mix(COLORS["card"], COLORS["green"], 0.14)),
        "warning": ("#FDE68A", mix(COLORS["card"], COLORS["amber"], 0.15)),
        "danger": ("#FCA5A5", mix(COLORS["card"], COLORS["red"], 0.17)),
        "purple": ("#C4B5FD", mix(COLORS["card"], COLORS["purple"], 0.16)),
        "dark": (COLORS["text_soft"], COLORS["surface"]),
    }

    def __init__(self, parent: tk.Misc, text: str = "", tone: str = "neutral",
                 bg: str | None = None, **kwargs):
        super().__init__(parent, text=text, bd=0, padx=px(9), pady=px(3),
                         font=FONTS["tiny"], anchor="center", **kwargs)
        self._card_bg = bg or COLORS["card"]
        self.set(text, tone)

    def set(self, text: str, tone: str | None = None) -> None:
        if tone is None:
            tone = self._tone_for(text)
        fg, background = self._TONES.get(tone, self._TONES["neutral"])
        self.configure(text=text.upper() if tone in ("warning", "danger") and text in
                       ("Critical", "High") else text,
                       fg=fg, bg=mix(self._card_bg, background, 0.9))
        self._current_tone = tone

    @staticmethod
    def _tone_for(value: str) -> str:
        lower = (value or "").lower()
        if lower in ("critical", "breached", "missed", "high"):
            return "danger"
        if lower in ("at risk", "pending", "warning"):
            return "warning"
        if lower in ("resolved", "met", "closed", "success"):
            return "success"
        if lower in ("in progress", "info"):
            return "info"
        if lower in ("open", "accent"):
            return "accent"
        return "neutral"

    def set_status(self, status: str) -> None:
        tone = {
            "Open": "accent", "In Progress": "info", "Pending": "warning",
            "Resolved": "success", "Closed": "neutral",
        }.get(status, "neutral")
        self.set(status, tone)

    def set_priority(self, priority: str) -> None:
        tone = {
            "Critical": "danger", "High": "warning", "Medium": "info", "Low": "neutral",
        }.get(priority, "neutral")
        self.set(priority, tone)


class DataTable(tk.Frame):
    """Treeview wrapper with scrollbars, zebra rows and empty state."""

    def __init__(
        self,
        parent: tk.Misc,
        columns: Sequence[dict[str, Any]],
        height: int = 10,
        on_double_click: Callable[[str], None] | None = None,
        on_select: Callable[[str], None] | None = None,
        empty_title: str = "Nothing here yet",
        empty_hint: str = "",
        selectmode: str = "browse",
    ):
        super().__init__(parent, bg=COLORS["card_soft"], bd=0,
                         highlightthickness=1, highlightbackground=COLORS["border_soft"])
        self.columns_spec = list(columns)
        self._base_widths = [px(int(column.get("width", 120))) for column in self.columns_spec]
        self._min_widths = [
            px(int(column.get("minwidth", 60))) for column in self.columns_spec
        ]
        self._payloads: dict[str, Any] = {}
        self._on_double_click = on_double_click
        self._on_select = on_select
        keys = [column["key"] for column in self.columns_spec]

        self.tree = ttk.Treeview(self, columns=keys, show="headings",
                                 height=height, selectmode=selectmode)
        for column, width in zip(self.columns_spec, self._base_widths):
            self.tree.heading(column["key"], text=column["label"],
                              anchor=column.get("heading_anchor", column.get("anchor", "w")))
            self.tree.column(
                column["key"],
                width=width,
                minwidth=px(int(column.get("minwidth", 60))),
                anchor=column.get("anchor", "w"),
                stretch=False,
            )
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=1)
        self.tree.bind("<Configure>", self._fit_columns, add="+")
        self.tree.tag_configure("row_odd", background=COLORS["card_soft"])
        self.tree.tag_configure("row_even", background="#0C1728")
        self.tree.tag_configure("row_critical",
                                background=mix(COLORS["card_soft"], COLORS["red"], 0.13))
        self.tree.tag_configure("row_high",
                                background=mix(COLORS["card_soft"], "#FB923C", 0.06))
        self.tree.tag_configure("sla_breach", foreground="#FCA5A5")
        self.tree.tag_configure("sla_risk", foreground="#FDE68A")
        self.tree.tag_configure("sla_met", foreground="#A7F3D0")
        self.tree.tag_configure("muted", foreground=COLORS["subtle"])
        self.tree.tag_configure("accent", foreground=COLORS["accent"])
        self.tree.tag_configure("warning", foreground="#FDE68A")
        self.tree.tag_configure("danger", foreground="#FCA5A5")
        self.tree.tag_configure("success", foreground="#86EFAC")

        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                                     style="Vertical.TScrollbar")
        self.vscroll.grid(row=0, column=1, sticky="ns", pady=1)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview,
                                     style="Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=self.vscroll.set,
                            xscrollcommand=self.hscroll.set)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._empty = tk.Frame(self, bg=COLORS["card_soft"])
        tk.Label(self._empty, text="◌", bg=COLORS["card_soft"], fg=COLORS["border"],
                 font=(FONTS["h1"].actual("family"), 28)).pack()
        tk.Label(self._empty, text=empty_title, bg=COLORS["card_soft"],
                 fg=COLORS["text_soft"], font=FONTS["semibold"]).pack(pady=(px(4), 0))
        if empty_hint:
            tk.Label(self._empty, text=empty_hint, bg=COLORS["card_soft"],
                     fg=COLORS["muted"], font=FONTS["small"]).pack(pady=(px(4), 0))

        if on_double_click:
            self.tree.bind("<Double-1>", self._double_click)
            self.tree.bind("<Return>", self._double_click)
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", self._select)
        bind_scroll_handoff(self.tree)

        self.after_idle(self._fit_columns)

    def _fit_columns(self, _event: tk.Event | None = None) -> None:
        """Scale columns to the available width so no column is clipped."""
        available = self.tree.winfo_width()
        if available <= 1:
            return
        available = max(1, available - 2)
        widths = list(self._base_widths)
        minimums = list(self._min_widths)
        count = len(widths)
        if count == 0:
            return
        flexible = [
            index for index, column in enumerate(self.columns_spec)
            if column.get("stretch")
        ]
        deficit = sum(widths) - available
        if deficit <= 0:
            extra = -deficit
            targets = flexible or list(range(count))
            share, remainder = divmod(extra, len(targets))
            for offset, index in enumerate(targets):
                widths[index] += share + (1 if offset < remainder else 0)
        else:
            # Shrink flexible columns first, then share the remaining deficit.
            for index in flexible:
                if deficit <= 0:
                    break
                reduction = min(widths[index] - minimums[index], deficit)
                widths[index] -= reduction
                deficit -= reduction
            if deficit > 0:
                reducible = sum(
                    widths[index] - minimums[index] for index in range(count)
                )
                if reducible > 0:
                    for index in range(count):
                        slack = widths[index] - minimums[index]
                        if slack <= 0:
                            continue
                        reduction = min(slack, int(deficit * slack / reducible))
                        widths[index] -= reduction
                        deficit -= reduction
                cursor = 0
                while deficit > 0 and any(
                    widths[index] > minimums[index] for index in range(count)
                ):
                    index = cursor % count
                    if widths[index] > minimums[index]:
                        widths[index] -= 1
                        deficit -= 1
                    cursor += 1
        for column, width in zip(self.columns_spec, widths):
            self.tree.column(column["key"], width=width)
        if sum(widths) > available:
            self.hscroll.grid(row=1, column=0, sticky="ew", padx=(1, 0))
        else:
            self.hscroll.grid_remove()
            self.tree.xview_moveto(0)

    def set_rows(
        self,
        rows: Sequence[Sequence[Any]],
        payloads: Sequence[Any] | None = None,
        tags: Sequence[Sequence[str]] | None = None,
        values_transform: Callable[[Sequence[Any]], Sequence[Any]] | None = None,
    ) -> None:
        self.tree.delete(*self.tree.get_children())
        self._payloads.clear()
        for index, row in enumerate(rows):
            values = values_transform(row) if values_transform else row
            item = self.tree.insert("", "end", values=values)
            if payloads is not None:
                self._payloads[item] = payloads[index]
            row_tags = list(tags[index]) if tags is not None else []
            if row_tags:
                self.tree.item(item, tags=tuple(row_tags))
        if rows:
            self._empty.place_forget()
        else:
            self._empty.place(relx=0.5, rely=0.5, anchor="center")

    def clear(self) -> None:
        self.set_rows([])

    def selected_item(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def selected_payload(self) -> Any:
        item = self.selected_item()
        return self._payloads.get(item) if item else None

    def select_first(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

    def select_payload(self, payload: Any) -> bool:
        for item, stored in self._payloads.items():
            if stored == payload:
                self.tree.selection_set(item)
                self.tree.focus(item)
                self.tree.see(item)
                return True
        return False

    def _double_click(self, _event: tk.Event) -> None:
        item = self.tree.identify_row(_event.y)
        if not item:
            item = self.selected_item()
        if item and self._on_double_click:
            payload = self._payloads.get(item)
            if payload is None:
                payload = item
            self._on_double_click(payload)

    def _select(self, _event: tk.Event) -> None:
        item = self.selected_item()
        if item and self._on_select:
            self._on_select(self._payloads.get(item))

    @property
    def row_count(self) -> int:
        return len(self.tree.get_children())


class ScrollableFrame(tk.Frame):
    """A themed vertical scroller that keeps content width in sync."""

    def __init__(self, parent: tk.Misc, bg: str | None = None):
        self.bg = bg or COLORS["bg"]
        super().__init__(parent, bg=self.bg)
        self.canvas = tk.Canvas(self, bg=self.bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.content = tk.Frame(self.canvas, bg=self.bg)
        self._window = self.canvas.create_window((0, 0), window=self.content,
                                                 anchor="nw", tags="inner")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # A single global router keeps wheel scrolling bound to the scroller
        # underneath the pointer, even when several pages are instantiated.
        self.canvas.bind_all("<MouseWheel>", _route_mousewheel)
        self.canvas.bind_all("<Button-4>", _route_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", _route_mousewheel_linux)

    def _on_content_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0)


def _scroller_under(widget: tk.Misc | None,
                    skip_scrollable: bool = False) -> "ScrollableFrame | None":
    """Return the scrollable ancestor of a widget, ignoring inner scrollers.

    Scrollable widgets (tables, text boxes, lists) normally absorb the mouse
    wheel themselves. With ``skip_scrollable`` the search continues past them
    so the surrounding page scroller can take over at the scroll limits.
    """
    while widget is not None:
        if isinstance(widget, (ttk.Treeview, tk.Text, tk.Listbox)):
            if not skip_scrollable:
                return None
        elif isinstance(widget, ScrollableFrame):
            return widget
        widget = getattr(widget, "master", None)
    return None


def _can_scroll(widget: tk.Misc, units: int) -> bool:
    """True when the widget still has content in the requested direction."""
    try:
        first, last = widget.yview()
        first = float(first)
        last = float(last)
    except (tk.TclError, ValueError, TypeError):
        return False
    if units < 0:
        return first > 0.001
    return last < 0.999


def bind_scroll_handoff(widget: tk.Misc) -> None:
    """Route the mouse wheel from a scrollable widget to its page scroller.

    The widget scrolls itself while it still has content; once it reaches its
    limit the surrounding page scroller takes over, so a table that fills the
    viewport never traps the user.
    """

    def _handler(event: tk.Event) -> str | None:
        units = int(-event.delta / 120) if event.delta else 0
        if units == 0:
            return None
        if _can_scroll(widget, units):
            try:
                widget.yview_scroll(units, "units")
            except tk.TclError:
                return None
            return "break"
        scroller = _scroller_under(widget, skip_scrollable=True)
        if scroller is not None and scroller.canvas.winfo_exists():
            scroller.canvas.yview_scroll(units, "units")
            return "break"
        return None

    widget.bind("<MouseWheel>", _handler)


def _route_mousewheel(event: tk.Event) -> str | None:
    units = int(-event.delta / 120) if event.delta else 0
    if units == 0:
        return None
    scroller = _scroller_under(event.widget, skip_scrollable=True)
    if scroller is not None and scroller.canvas.winfo_exists():
        scroller.canvas.yview_scroll(units, "units")
        return "break"
    return None


def _route_mousewheel_linux(event: tk.Event) -> str | None:
    units = -1 if event.num == 4 else 1
    scroller = _scroller_under(event.widget, skip_scrollable=True)
    if scroller is not None and scroller.canvas.winfo_exists():
        scroller.canvas.yview_scroll(units, "units")
        return "break"
    return None


class Meter(tk.Canvas):
    """Small themed progress meter used for SLA consumption."""

    def __init__(self, parent: tk.Misc, width: int = 220, height: int = 8,
                 bg: str | None = None):
        self._bg = bg or COLORS["card"]
        super().__init__(parent, width=px(width), height=px(height), bg=self._bg,
                         highlightthickness=0, bd=0)
        self._percent = 0.0
        self._color = COLORS["accent"]
        self.bind("<Configure>", lambda _event: self._draw())

    def set(self, percent: float, color: str) -> None:
        self._percent = max(0.0, min(100.0, float(percent)))
        self._color = color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        self.create_rectangle(0, 0, width, height, fill=COLORS["card_soft"], outline="")
        filled = int(width * self._percent / 100.0)
        if filled > 0:
            self.create_rectangle(0, 0, filled, height, fill=self._color, outline="")


class SidebarItem(tk.Frame):
    def __init__(self, parent: tk.Misc, key: str, label: str, icon: str,
                 command: Callable[[str], None]):
        super().__init__(parent, bg=COLORS["sidebar"], height=px(46), cursor="hand2")
        self.key = key
        self.command = command
        self.active = False
        self.pack_propagate(False)
        self.bar = tk.Frame(self, bg=COLORS["sidebar"], width=px(3))
        self.bar.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=icon, bg=COLORS["sidebar"], fg=COLORS["subtle"],
                             font=FONTS["h3"], width=3)
        self.icon.pack(side="left", padx=(px(10), 0))
        self.label = tk.Label(self, text=label, bg=COLORS["sidebar"], fg=COLORS["muted"],
                              font=FONTS["small"], anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        for widget in (self, self.icon, self.label):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _click(self, _event: tk.Event) -> None:
        self.command(self.key)

    def _enter(self, _event: tk.Event) -> None:
        if not self.active:
            self._paint(COLORS["sidebar_hover"], COLORS["text_soft"], COLORS["accent"])

    def _leave(self, _event: tk.Event) -> None:
        if not self.active:
            self._paint(COLORS["sidebar"], COLORS["muted"], COLORS["subtle"])

    def _paint(self, bg: str, fg: str, icon_fg: str) -> None:
        self.configure(bg=bg)
        self.bar.configure(bg=bg)
        self.icon.configure(bg=bg, fg=icon_fg)
        self.label.configure(bg=bg, fg=fg)

    def set_active(self, active: bool) -> None:
        self.active = active
        if active:
            self._paint(COLORS["sidebar_hover"], COLORS["text"], COLORS["accent"])
            self.bar.configure(bg=COLORS["accent"])
        else:
            self._paint(COLORS["sidebar"], COLORS["muted"], COLORS["subtle"])


def ticket_row_tags(index: int, priority: str, sla_state: str = "") -> list[str]:
    tags: list[str] = []
    if priority == "Critical":
        tags.append("row_critical")
    elif priority == "High":
        tags.append("row_high")
    else:
        tags.append("row_even" if index % 2 else "row_odd")
    if sla_state in ("Breached", "Missed"):
        tags.append("sla_breach")
    elif sla_state == "At risk":
        tags.append("sla_risk")
    elif sla_state == "Met":
        tags.append("sla_met")
    elif sla_state == "On track":
        tags.append("sla_met")
    return tags


def audit_tag(action: str) -> str:
    if action in ("SLA_BREACH", "ESCALATION_RAISED", "TICKET_DELETED"):
        return "danger"
    if action in ("SLA_RECALCULATED", "STATUS_CHANGED", "PRIORITY_CHANGED"):
        return "warning"
    if action in ("TICKET_CREATED", "CSV_IMPORT", "COMMENT_ADDED"):
        return "accent"
    if action.startswith("SLA_POLICY"):
        return "success"
    return ""


def divider(parent: tk.Misc, bg: str | None = None) -> tk.Frame:
    line = tk.Frame(parent, bg=bg or COLORS["border_soft"], height=px(1))
    line.pack(fill="x")
    return line
