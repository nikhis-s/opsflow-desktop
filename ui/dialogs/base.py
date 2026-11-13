"""Shared dialog scaffolding: themed frame, header, footer and helpers."""
from __future__ import annotations

import tkinter as tk

from ui.components import ManagedTimers, bind_scroll_handoff
from ui.theme import COLORS, FONTS, px


def _text_widget(parent: tk.Misc, height: int = 5, bg: str | None = None, **kwargs) -> tk.Text:
    widget = tk.Text(
        parent, height=height, wrap="word", bg=bg or COLORS["card_soft"],
        fg=COLORS["text_soft"], insertbackground=COLORS["accent"],
        selectbackground=COLORS["selection"], relief="flat", bd=0,
        highlightthickness=1, highlightbackground=COLORS["border"],
        highlightcolor=COLORS["accent_deep"], font=FONTS["body"],
        padx=px(10), pady=px(8), **kwargs,
    )
    bind_scroll_handoff(widget)
    return widget


def _field_label(parent: tk.Misc, text: str, required: bool = False) -> tk.Frame:
    frame = tk.Frame(parent, bg=COLORS["card"])
    tk.Label(frame, text=text, bg=COLORS["card"], fg=COLORS["muted"],
             font=FONTS["tiny"], anchor="w").pack(side="left")
    if required:
        tk.Label(frame, text=" *", bg=COLORS["card"], fg=COLORS["accent"],
                 font=FONTS["tiny"]).pack(side="left")
    return frame


class BaseDialog(ManagedTimers, tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str = "",
        width: int = 720,
        height: int = 620,
        resizable: bool = False,
    ):
        super().__init__(parent)
        self._init_managed_timers()
        self.parent_window = parent.winfo_toplevel()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # Scale the requested size, then make sure the whole dialog fits on
        # smaller laptop displays (including the taskbar/title bar allowance).
        self._width = max(px(380), min(px(width), screen_w - px(40)))
        self._height = max(px(260), min(px(height), screen_h - px(80)))
        self.title(f"OpsFlow · {title}")
        self.configure(bg=COLORS["card"])
        self.transient(self.parent_window)
        self.resizable(resizable, resizable)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        # tkinter's grab_set() takes a *local* grab, which keeps the dialog
        # modal to this application without taking a global grab.
        try:
            self.grab_set()
        except tk.TclError:
            pass

        header = tk.Frame(self, bg=COLORS["surface"])
        header.pack(fill="x")
        tk.Frame(header, bg=COLORS["accent"], height=px(3)).pack(fill="x")
        header_inner = tk.Frame(header, bg=COLORS["surface"])
        header_inner.pack(fill="x", padx=px(24), pady=(px(16), px(14)))
        text = tk.Frame(header_inner, bg=COLORS["surface"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=COLORS["surface"], fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(text, text=subtitle, bg=COLORS["surface"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(fill="x", pady=(px(2), 0))
        close = tk.Label(header_inner, text="✕", bg=COLORS["surface"],
                         fg=COLORS["muted"], font=FONTS["medium"], cursor="hand2",
                         padx=px(8), pady=px(2))
        close.pack(side="right")
        close.bind("<Button-1>", lambda _event: self.close())
        close.bind("<Enter>", lambda _event: close.configure(fg=COLORS["text"]))
        close.bind("<Leave>", lambda _event: close.configure(fg=COLORS["muted"]))

        self.body = tk.Frame(self, bg=COLORS["card"])
        self.body.pack(fill="both", expand=True, padx=px(24), pady=(px(16), px(8)))
        self.footer = tk.Frame(self, bg=COLORS["card"])
        self.footer.pack(fill="x", padx=px(24), pady=(px(4), px(18)))
        self.error_var = tk.StringVar(value="")
        self.error_label = tk.Label(self.footer, textvariable=self.error_var,
                                    bg=COLORS["card"], fg=COLORS["red"],
                                    font=FONTS["small"], anchor="w",
                                    wraplength=max(px(240), self._width - px(60)))
        self.error_label.pack(fill="x", pady=(0, px(6)))
        self.buttons = tk.Frame(self.footer, bg=COLORS["card"])
        self.buttons.pack(fill="x")
        self._center()
        self.schedule(80, self._safe_focus)

    def set_min_size(self, width: int, height: int) -> None:
        """Apply a scaled minimum size without allowing it to exceed the screen."""
        self.minsize(min(px(width), self._width), min(px(height), self._height))

    def _safe_focus(self) -> None:
        """Take keyboard focus, but only once the dialog is really on screen.

        Forcing focus on a window that is not viewable blocks on macOS, so the
        call is skipped until the dialog has been mapped.
        """
        try:
            if not self.winfo_viewable():
                return
            self.focus_force()
        except tk.TclError:
            pass

    def focus_later(self, widget: tk.Misc, delay: int = 100) -> None:
        """Move keyboard focus to a widget once the dialog is on screen."""
        self.schedule(delay, self._focus_widget, widget)

    def _focus_widget(self, widget: tk.Misc) -> None:
        try:
            if not self.winfo_viewable():
                return
            widget.focus_set()
        except tk.TclError:
            pass

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.parent_window
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = max(0, parent_x + (parent_w - self._width) // 2)
        y = max(0, parent_y + (parent_h - self._height) // 2 - px(10))
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = min(x, max(0, screen_w - self._width - px(20)))
        y = min(y, max(0, screen_h - self._height - px(50)))
        self.geometry(f"{self._width}x{self._height}+{x}+{y}")

    def show_error(self, message: str) -> None:
        self.error_var.set(message)
        self.bell()

    def clear_error(self) -> None:
        self.error_var.set("")

    def clear_footer(self) -> None:
        for child in self.buttons.winfo_children():
            child.destroy()

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

