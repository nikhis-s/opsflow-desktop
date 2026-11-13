"""Create and edit a ticket, with a live SLA clock preview."""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from models import (
    PRIORITIES,
    STATUSES,
    Ticket,
    duration_minutes,
    format_local,
    utc_now,
)
from services.sla_engine import SLAEngine
from services.ticket_service import TicketService, ValidationError
from ui.components import flat_button
from ui.dialogs.base import BaseDialog, _field_label, _text_widget
from ui.theme import COLORS, FONTS, px


class TicketDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        sla: SLAEngine,
        ticket: Ticket | None = None,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.sla = sla
        self.ticket = ticket
        self.on_saved = on_saved
        self.created_at = ticket.created_at if ticket else None
        super().__init__(
            parent,
            "Edit ticket" if ticket else "Create ticket",
            (f"{ticket.id} · update details and SLA-affecting fields"
             if ticket else "Log a new request and start its SLA clock"),
            width=800, height=760, resizable=True,
        )
        self.set_min_size(720, 680)
        self._build()
        self._populate()
        self.update_sla_preview()

    def _build(self) -> None:
        self.body.grid_columnconfigure(0, weight=1, uniform="form")
        self.body.grid_columnconfigure(1, weight=1, uniform="form")
        self.body.grid_rowconfigure(4, weight=1)

        _field_label(self.body, "Title", True).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, px(5)))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(self.body, textvariable=self.title_var)
        self.title_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, px(14)))

        _field_label(self.body, "Requester", True).grid(
            row=2, column=0, sticky="ew", padx=(0, px(8)), pady=(0, px(5)))
        _field_label(self.body, "Assignee").grid(
            row=2, column=1, sticky="ew", padx=(px(8), 0), pady=(0, px(5)))
        self.requester_var = tk.StringVar()
        self.assignee_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self.requester_var).grid(
            row=3, column=0, sticky="ew", padx=(0, px(8)), pady=(0, px(12)))
        self.assignee_combo = ttk.Combobox(
            self.body, textvariable=self.assignee_var,
            values=["Unassigned", *self.tickets.get_assignees()], state="normal",
        )
        self.assignee_combo.grid(row=3, column=1, sticky="ew", padx=(px(8), 0),
                                 pady=(0, px(12)))

        _field_label(self.body, "Category").grid(
            row=4, column=0, sticky="ew", padx=(0, px(8)), pady=(0, px(5)))
        _field_label(self.body, "Priority", True).grid(
            row=4, column=1, sticky="ew", padx=(px(8), 0), pady=(0, px(5)))
        self.category_var = tk.StringVar()
        self.priority_var = tk.StringVar()
        self.category_combo = ttk.Combobox(
            self.body, textvariable=self.category_var,
            values=self.tickets.get_categories(), state="normal",
        )
        self.category_combo.grid(row=5, column=0, sticky="ew", padx=(0, px(8)),
                                 pady=(0, px(12)))
        self.priority_combo = ttk.Combobox(
            self.body, textvariable=self.priority_var, values=list(PRIORITIES),
            state="readonly",
        )
        self.priority_combo.grid(row=5, column=1, sticky="ew", padx=(px(8), 0),
                                 pady=(0, px(12)))
        self.priority_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_sla_preview())

        _field_label(self.body, "Status", True).grid(
            row=6, column=0, sticky="ew", padx=(0, px(8)), pady=(0, px(5)))
        _field_label(self.body, "Created (UTC clock start)").grid(
            row=6, column=1, sticky="ew", padx=(px(8), 0), pady=(0, px(5)))
        self.status_var = tk.StringVar()
        self.status_combo = ttk.Combobox(
            self.body, textvariable=self.status_var, values=list(STATUSES),
            state="readonly",
        )
        self.status_combo.grid(row=7, column=0, sticky="ew", padx=(0, px(8)),
                               pady=(0, px(14)))
        self.created_label = tk.Label(
            self.body, text="", bg=COLORS["card_soft"], fg=COLORS["text_soft"],
            font=FONTS["small"], anchor="w", padx=px(10), pady=px(9),
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        self.created_label.grid(row=7, column=1, sticky="ew", padx=(px(8), 0),
                                pady=(0, px(14)))

        _field_label(self.body, "Description").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(0, px(5)))
        self.description_text = _text_widget(self.body, height=6)
        self.description_text.grid(row=9, column=0, columnspan=2, sticky="nsew",
                                   pady=(0, px(14)))
        self.body.grid_rowconfigure(9, weight=1)

        preview = tk.Frame(self.body, bg=COLORS["card_soft"], highlightthickness=1,
                           highlightbackground=COLORS["border_soft"])
        preview.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, px(4)))
        inner = tk.Frame(preview, bg=COLORS["card_soft"])
        inner.pack(fill="x", padx=px(14), pady=px(11))
        tk.Label(inner, text="SLA CLOCK PREVIEW", bg=COLORS["card_soft"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(anchor="w")
        self.sla_preview_var = tk.StringVar()
        tk.Label(inner, textvariable=self.sla_preview_var, bg=COLORS["card_soft"],
                 fg=COLORS["text_soft"], font=FONTS["small"], anchor="w",
                 justify="left").pack(fill="x", pady=(px(4), 0))

        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(
            self.buttons, "Save changes" if self.ticket else "Create ticket",
            self.save, "primary",
        ).pack(side="right", padx=(0, px(8)))

    def _populate(self) -> None:
        ticket = self.ticket
        if ticket:
            self.title_var.set(ticket.title)
            self.requester_var.set(ticket.requester)
            self.assignee_var.set(ticket.assignee)
            self.category_var.set(ticket.category)
            self.priority_var.set(ticket.priority)
            self.status_var.set(ticket.status)
            self.description_text.insert("1.0", ticket.description)
            self.created_label.configure(text=format_local(ticket.created_at))
        else:
            self.assignee_var.set("Unassigned")
            self.category_var.set("General")
            self.priority_var.set("Medium")
            self.status_var.set("Open")
            self.created_label.configure(text="Set automatically on save")

    def update_sla_preview(self) -> None:
        priority = self.priority_var.get() or "Medium"
        try:
            policy = self.sla.get_policy(priority)
        except ValueError:
            return
        created = self.created_at or utc_now()
        response, resolution = self.sla.deadlines_for(priority, created)
        self.sla_preview_var.set(
            f"{priority}: respond within {duration_minutes(policy.response_minutes)} "
            f"(due {format_local(response)}) · resolve within "
            f"{duration_minutes(policy.resolution_minutes)} "
            f"(due {format_local(resolution)}). Warning at "
            f"{policy.at_risk_percent}% of each window."
        )
        self.created_label.configure(
            text=format_local(created) if self.ticket else "Set automatically on save"
        )

    def save(self) -> None:
        self.clear_error()
        title = self.title_var.get()
        description = self.description_text.get("1.0", "end-1c")
        requester = self.requester_var.get()
        assignee = self.assignee_var.get()
        category = self.category_var.get()
        priority = self.priority_var.get()
        status = self.status_var.get()
        try:
            if self.ticket:
                updated = self.tickets.update_ticket(
                    self.ticket.id,
                    {
                        "title": title,
                        "description": description,
                        "requester": requester,
                        "assignee": assignee,
                        "category": category,
                        "priority": priority,
                        "status": status,
                    },
                )
            else:
                updated = self.tickets.create_ticket(
                    title=title,
                    description=description,
                    requester=requester,
                    assignee=assignee,
                    category=category,
                    priority=priority,
                    status=status,
                )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.show_error(f"Could not save ticket: {exc}")
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()

