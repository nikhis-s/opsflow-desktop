"""Assign a ticket, change its status, or add an internal note."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from models import STATUSES, Ticket
from services.ticket_service import TicketService, ValidationError
from ui.components import flat_button
from ui.dialogs.base import BaseDialog, _field_label, _text_widget
from ui.theme import COLORS, FONTS, px


class AssignDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Assign ticket", f"{ticket.id} · {ticket.title}",
                         width=520, height=330)
        tk.Label(self.body, text="Assign this ticket to an owner or queue.", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).pack(anchor="w", pady=(0, px(8)))
        _field_label(self.body, "Assignee", True).pack(anchor="w", pady=(0, px(4)))
        self.assignee_var = tk.StringVar(value=ticket.assignee)
        self.combo = ttk.Combobox(
            self.body, textvariable=self.assignee_var,
            values=["Unassigned", *tickets.get_assignees()], state="normal",
        )
        self.combo.pack(fill="x", pady=(0, px(8)))
        tk.Label(
            self.body,
            text="Assigning a ticket is recorded in the audit trail.",
            bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"],
        ).pack(anchor="w")
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Assign ticket", self.save, "primary").pack(
            side="right", padx=(0, px(8)))
        self.focus_later(self.combo)

    def save(self) -> None:
        self.clear_error()
        try:
            updated = self.tickets.assign_ticket(self.ticket.id, self.assignee_var.get())
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()


class StatusDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Change status", f"{ticket.id} · currently {ticket.status}",
                         width=560, height=430)
        _field_label(self.body, "New status", True).pack(anchor="w", pady=(0, px(4)))
        self.status_var = tk.StringVar(value=ticket.status)
        self.combo = ttk.Combobox(self.body, textvariable=self.status_var,
                                  values=list(STATUSES), state="readonly")
        self.combo.pack(fill="x", pady=(0, px(12)))
        _field_label(self.body, "Note (optional internal comment)").pack(
            anchor="w", pady=(0, px(4)))
        self.note = _text_widget(self.body, height=5)
        self.note.pack(fill="both", expand=True)
        self.hint = tk.Label(
            self.body,
            text="Resolved/Closed stamps resolution time. Reopening clears the completion stamps.",
            bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"],
            wraplength=px(480), justify="left",
        )
        self.hint.pack(anchor="w", pady=(px(8), 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Update status", self.save, "primary").pack(
            side="right", padx=(0, px(8)))
        self.focus_later(self.combo)

    def save(self) -> None:
        self.clear_error()
        if self.status_var.get() == self.ticket.status:
            self.show_error("Choose a different status, or add the note from the ticket activity tab.")
            return
        try:
            updated = self.tickets.change_status(
                self.ticket.id, self.status_var.get(),
                note=self.note.get("1.0", "end-1c"),
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()


class CommentDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Any], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Add internal note", f"{ticket.id} · {ticket.title}",
                         width=580, height=430)
        tk.Label(
            self.body,
            text="Internal notes are stored in OpsFlow and never sent externally.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"],
        ).pack(anchor="w", pady=(0, px(8)))
        self.note = _text_widget(self.body, height=8)
        self.note.pack(fill="both", expand=True)
        self.internal_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.body, text="Internal note", variable=self.internal_var).pack(
            anchor="w", pady=(px(8), 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Add note", self.save, "primary").pack(
            side="right", padx=(0, px(8)))
        self.focus_later(self.note, 120)

    def save(self) -> None:
        self.clear_error()
        try:
            comment = self.tickets.add_comment(
                self.ticket.id, self.note.get("1.0", "end-1c"),
                internal=self.internal_var.get(),
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(comment)
        self.close()

