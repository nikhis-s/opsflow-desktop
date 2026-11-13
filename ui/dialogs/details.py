"""Ticket details: SLA meters, internal notes and recorded activity."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from models import Ticket, format_local, human_duration
from services.audit_service import AuditService
from services.escalation_engine import EscalationEngine
from services.sla_engine import MET, SLAEngine
from services.ticket_service import TicketService, ValidationError
from ui.components import Badge, Meter, flat_button
from ui.dialogs.base import BaseDialog, _text_widget
from ui.dialogs.confirm import ConfirmDialog
from ui.dialogs.ticket import TicketDialog
from ui.dialogs.workflow import AssignDialog, StatusDialog
from ui.theme import COLORS, FONTS, SLA_COLORS, px


class TicketDetailsDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        sla: SLAEngine,
        audit: AuditService,
        escalations: EscalationEngine,
        ticket_id: str,
        on_changed: Callable[[], None] | None = None,
    ):
        self.tickets = tickets
        self.sla = sla
        self.audit = audit
        self.escalations = escalations
        self.ticket_id = ticket_id
        self.on_changed = on_changed
        self.ticket: Ticket | None = None
        super().__init__(parent, "Ticket details", "", width=1120, height=840,
                         resizable=True)
        self.set_min_size(960, 700)
        self._build()

    # --------------------------------------------------------------- layout
    def _build(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.clear_footer()
        try:
            self.ticket = self.tickets.get_ticket(self.ticket_id)
        except Exception as exc:
            tk.Label(self.body, text=f"Unable to load ticket: {exc}", bg=COLORS["card"],
                     fg=COLORS["red"], font=FONTS["body"]).pack(anchor="w")
            return
        ticket = self.ticket
        self.title(f"OpsFlow · {ticket.id}")
        self.body.grid_columnconfigure(0, weight=3)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self.body, bg=COLORS["card"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, px(16)))
        right = tk.Frame(self.body, bg=COLORS["card"])
        right.grid(row=0, column=1, sticky="nsew")

        # Header
        eyebrow = tk.Frame(left, bg=COLORS["card"])
        eyebrow.pack(fill="x")
        tk.Label(eyebrow, text=ticket.id, bg=COLORS["card"], fg=COLORS["accent"],
                 font=FONTS["mono"]).pack(side="left")
        tk.Label(eyebrow, text=f"  ·  Created {format_local(ticket.created_at)}",
                 bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        tk.Label(left, text=ticket.title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["h1"], wraplength=px(490), justify="left", anchor="w").pack(
            fill="x", pady=(px(4), px(8)))
        badge_row = tk.Frame(left, bg=COLORS["card"])
        badge_row.pack(fill="x", pady=(0, px(14)))
        status_badge = Badge(badge_row, ticket.status, bg=COLORS["card"])
        status_badge.set_status(ticket.status)
        status_badge.pack(side="left", padx=(0, px(6)))
        priority_badge = Badge(badge_row, ticket.priority, bg=COLORS["card"])
        priority_badge.set_priority(ticket.priority)
        priority_badge.pack(side="left", padx=(0, px(6)))
        evaluation = self.sla.evaluate(ticket)
        sla_badge = Badge(badge_row, evaluation.overall_state, bg=COLORS["card"])
        sla_badge.pack(side="left", padx=(0, px(6)))
        tk.Label(badge_row, text=ticket.category, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left", padx=(px(8), 0))

        # SLA meters
        meters = tk.Frame(left, bg=COLORS["card"])
        meters.pack(fill="x", pady=(0, px(16)))
        meters.grid_columnconfigure(0, weight=1)
        meters.grid_columnconfigure(1, weight=1)
        self._deadline_card(
            meters, 0, "RESPONSE SLA", ticket.response_deadline,
            evaluation.response.state, evaluation.response.remaining_seconds,
            evaluation.response.consumed_percent, ticket.first_response_at,
        )
        self._deadline_card(
            meters, 1, "RESOLUTION SLA", ticket.resolution_deadline,
            evaluation.resolution.state, evaluation.resolution.remaining_seconds,
            evaluation.resolution.consumed_percent, ticket.resolved_at,
        )

        # Description
        tk.Label(left, text="DESCRIPTION", bg=COLORS["card"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(anchor="w", pady=(0, px(4)))
        desc = _text_widget(left, height=4)
        desc.pack(fill="x", pady=(0, px(16)))
        desc.insert("1.0", ticket.description or "No description provided.")
        desc.configure(state="disabled")

        # Metadata
        meta = tk.Frame(left, bg=COLORS["card"])
        meta.pack(fill="both", expand=True)
        meta.grid_columnconfigure(0, weight=1)
        meta.grid_columnconfigure(1, weight=1)
        fields = [
            ("Requester", ticket.requester),
            ("Assignee", ticket.assignee),
            ("Category", ticket.category),
            ("Priority", ticket.priority),
            ("Created", format_local(ticket.created_at)),
            ("Last updated", format_local(ticket.updated_at)),
            ("First response", format_local(ticket.first_response_at)),
            ("Resolved", format_local(ticket.resolved_at)),
            ("Response deadline", format_local(ticket.response_deadline)),
            ("Resolution deadline", format_local(ticket.resolution_deadline)),
        ]
        for index, (label, value) in enumerate(fields):
            cell = tk.Frame(meta, bg=COLORS["card"])
            cell.grid(row=index // 2, column=index % 2, sticky="ew", pady=(0, px(10)),
                      padx=(0, px(12) if index % 2 == 0 else 0))
            tk.Label(cell, text=label.upper(), bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"], anchor="w").pack(fill="x")
            tk.Label(cell, text=value or "—", bg=COLORS["card"], fg=COLORS["text_soft"],
                     font=FONTS["small"], anchor="w").pack(fill="x")

        # Right: notes
        notes_header = tk.Frame(right, bg=COLORS["card"])
        notes_header.pack(fill="x")
        comments = self.tickets.get_comments(ticket.id)
        tk.Label(notes_header, text="INTERNAL NOTES", bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        tk.Label(notes_header, text=f"{len(comments)}", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="right")

        notes_frame = tk.Frame(right, bg=COLORS["card_soft"], highlightthickness=1,
                               highlightbackground=COLORS["border_soft"])
        notes_frame.pack(fill="both", expand=True, pady=(px(6), px(8)))
        notes_text = _text_widget(notes_frame, height=10, bg=COLORS["card_soft"])
        notes_text.pack(fill="both", expand=True, padx=1, pady=1)
        notes_text.tag_configure("author", foreground=COLORS["text"],
                                 font=FONTS["medium"], spacing1=4)
        notes_text.tag_configure("time", foreground=COLORS["subtle"], font=FONTS["tiny"])
        notes_text.tag_configure("body", foreground=COLORS["text_soft"],
                                 font=FONTS["small"], spacing3=8, lmargin1=0, lmargin2=0)
        notes_text.tag_configure("divider", foreground=COLORS["border"])
        if not comments:
            notes_text.insert("end", "No internal notes yet.\n", "body")
        for comment in comments:
            notes_text.insert("end", f"{comment.author}", "author")
            notes_text.insert("end", f"   {format_local(comment.created_at)}\n", "time")
            notes_text.insert("end", f"{comment.body}\n", "body")
            notes_text.insert("end", "─" * 48 + "\n", "divider")
        notes_text.configure(state="disabled")
        notes_text.see("end")

        input_row = tk.Frame(right, bg=COLORS["card"])
        input_row.pack(fill="x")
        self.note_text = _text_widget(input_row, height=3)
        self.note_text.pack(fill="x", pady=(0, px(6)))
        flat_button(input_row, "Add internal note", self._add_note, "secondary").pack(
            side="right")

        activity_header = tk.Frame(right, bg=COLORS["card"])
        activity_header.pack(fill="x", pady=(px(14), 0))
        tk.Label(activity_header, text="RECENT ACTIVITY", bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        activity_frame = tk.Frame(right, bg=COLORS["card_soft"], highlightthickness=1,
                                  highlightbackground=COLORS["border_soft"])
        activity_frame.pack(fill="x", pady=(px(6), 0))
        activity_text = _text_widget(activity_frame, height=7, bg=COLORS["card_soft"])
        activity_text.pack(fill="both", expand=True, padx=1, pady=1)
        activity_text.tag_configure("action", foreground=COLORS["accent"],
                                    font=FONTS["tiny"])
        activity_text.tag_configure("time", foreground=COLORS["subtle"], font=FONTS["tiny"])
        activity_text.tag_configure("body", foreground=COLORS["muted"],
                                    font=FONTS["small"], spacing3=4)
        for event in self.audit.for_ticket(ticket.id, limit=20):
            activity_text.insert("end", event.action, "action")
            activity_text.insert("end", f"  {format_local(event.created_at)}\n", "time")
            activity_text.insert("end", event.details + "\n", "body")
        activity_text.configure(state="disabled")

        # Footer actions
        flat_button(self.buttons, "Delete", self._delete, "danger").pack(side="left")
        flat_button(self.buttons, "Close", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Edit", self._edit, "secondary").pack(
            side="right", padx=(0, px(8)))
        flat_button(self.buttons, "Change status", self._status, "secondary").pack(
            side="right", padx=(0, px(8)))
        flat_button(self.buttons, "Assign", self._assign, "primary").pack(
            side="right", padx=(0, px(8)))

    def _deadline_card(
        self, parent: tk.Misc, column: int, title: str, deadline: Any,
        state: str, remaining: int | None, consumed: float, completed_at: Any,
    ) -> None:
        color = SLA_COLORS.get(state, COLORS["accent"])
        card = tk.Frame(parent, bg=COLORS["card_soft"], highlightthickness=1,
                        highlightbackground=COLORS["border_soft"])
        card.grid(row=0, column=column, sticky="ew",
                  padx=(0, px(8)) if column == 0 else (px(8), 0))
        inner = tk.Frame(card, bg=COLORS["card_soft"])
        inner.pack(fill="x", padx=px(12), pady=px(10))
        top = tk.Frame(inner, bg=COLORS["card_soft"])
        top.pack(fill="x")
        tk.Label(top, text=title, bg=COLORS["card_soft"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(side="left")
        badge = Badge(top, state, bg=COLORS["card_soft"])
        badge.pack(side="right")
        if completed_at is not None:
            if remaining is not None and remaining >= 0:
                detail = f"{state} · {human_duration(remaining)} early"
            else:
                detail = f"{state} · {human_duration(abs(remaining or 0))} late"
        else:
            detail = (f"{human_duration(abs(remaining or 0))} remaining" if (remaining or 0) >= 0
                      else f"{human_duration(abs(remaining or 0))} overdue")
        tk.Label(inner, text=format_local(deadline), bg=COLORS["card_soft"],
                 fg=COLORS["text_soft"], font=FONTS["small"]).pack(
            anchor="w", pady=(px(5), px(2)))
        tk.Label(inner, text=detail, bg=COLORS["card_soft"], fg=color,
                 font=FONTS["tiny"]).pack(anchor="w")
        meter = Meter(inner, height=6, bg=COLORS["card_soft"])
        meter.pack(fill="x", pady=(px(7), 0))
        meter.set(100.0 if state in (MET, "Missed") else consumed, color)

    # --------------------------------------------------------------- actions
    def _add_note(self) -> None:
        self.clear_error()
        try:
            self.tickets.add_comment(
                self.ticket_id, self.note_text.get("1.0", "end-1c"), internal=True,
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        self._changed()

    def _edit(self) -> None:
        TicketDialog(
            self, self.tickets, self.sla, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _assign(self) -> None:
        if self.ticket is None:
            return
        AssignDialog(
            self, self.tickets, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _status(self) -> None:
        if self.ticket is None:
            return
        StatusDialog(
            self, self.tickets, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _delete(self) -> None:
        def confirm() -> None:
            try:
                self.tickets.delete_ticket(self.ticket_id)
            except Exception as exc:
                self.show_error(f"Could not delete ticket: {exc}")
                return
            if self.on_changed:
                self.on_changed()
            self.close()
        ConfirmDialog(
            self, "Delete ticket",
            f"Delete {self.ticket_id} and its comments? Audit and escalation history will be preserved.",
            confirm_label="Delete ticket", danger=True, on_confirm=confirm,
        )

    def _changed(self) -> None:
        if self.on_changed:
            self.on_changed()
        self._build()

