"""Confirmation dialog used before destructive actions."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from ui.components import flat_button
from ui.dialogs.base import BaseDialog
from ui.theme import COLORS, FONTS, px


class ConfirmDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, message: str,
                 confirm_label: str = "Confirm", danger: bool = False,
                 on_confirm: Callable[[], None] | None = None):
        self.on_confirm = on_confirm
        super().__init__(parent, title, "This action is recorded in the audit trail.",
                         width=520, height=280)
        tk.Label(self.body, text=message, bg=COLORS["card"], fg=COLORS["text_soft"],
                 font=FONTS["body"], wraplength=px(460), justify="left").pack(
            anchor="w", fill="x", pady=(px(6), 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, confirm_label, self._confirm,
                    "danger" if danger else "primary").pack(side="right", padx=(0, px(8)))

    def _confirm(self) -> None:
        callback = self.on_confirm
        self.close()
        if callback:
            callback()

