"""Searchable audit trail for every recorded ticket operation."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from models import AuditEvent, format_local, parse_user_timestamp
from ui.components import (
    Card, DataTable, Page, ScrollableFrame, SectionHeader, audit_tag,
    bind_scroll_handoff, flat_button,
)
from ui.theme import COLORS, FONTS, px


class AuditPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self._events: list[AuditEvent] = []
        self._search_job: str | None = None
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=px(26), pady=px(20))

        header = SectionHeader(
            outer, "Audit trail",
            "Immutable history of ticket creation, field changes, notes, SLA events and escalations.",
        )
        header.pack(fill="x", pady=(0, px(14)))
        flat_button(header.actions, "Export audit CSV", self.export_audit,
                    "secondary").pack(side="right")

        filters = Card(outer, padding=(14, 10), bg=COLORS["surface"])
        filters.pack(fill="x", pady=(0, px(12)))
        grid = filters.body
        weights = (4, 3, 2, 2, 2, 0)
        for column, weight in enumerate(weights):
            grid.grid_columnconfigure(column, weight=weight)
        labels = ["SEARCH", "ACTION", "TICKET ID", "FROM", "TO"]
        for column, label in enumerate(labels):
            tk.Label(grid, text=label, bg=COLORS["surface"], fg=COLORS["subtle"],
                     font=FONTS["micro"], anchor="w").grid(
                row=0, column=column, sticky="ew", padx=(0, px(8)), pady=(0, px(5)))

        self.search_var = tk.StringVar()
        search = ttk.Entry(grid, textvariable=self.search_var, style="Search.TEntry")
        search.grid(row=1, column=0, sticky="ew", padx=(0, px(8)))
        search.bind("<KeyRelease>", self._schedule_search)
        search.bind("<Return>", lambda _event: self.refresh())

        self.action_var = tk.StringVar(value="All actions")
        self.action_combo = ttk.Combobox(grid, textvariable=self.action_var,
                                         state="readonly")
        self.action_combo.grid(row=1, column=1, sticky="ew", padx=(0, px(8)))
        self.action_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.ticket_var = tk.StringVar()
        ticket_entry = ttk.Entry(grid, textvariable=self.ticket_var)
        ticket_entry.grid(row=1, column=2, sticky="ew", padx=(0, px(8)))
        ticket_entry.bind("<Return>", lambda _event: self.refresh())

        self.from_var = tk.StringVar()
        from_entry = ttk.Entry(grid, textvariable=self.from_var)
        from_entry.grid(row=1, column=3, sticky="ew", padx=(0, px(8)))
        from_entry.bind("<Return>", lambda _event: self.refresh())
        self.to_var = tk.StringVar()
        to_entry = ttk.Entry(grid, textvariable=self.to_var)
        to_entry.grid(row=1, column=4, sticky="ew", padx=(0, px(8)))
        to_entry.bind("<Return>", lambda _event: self.refresh())

        buttons = tk.Frame(grid, bg=COLORS["surface"])
        buttons.grid(row=1, column=5, sticky="e")
        flat_button(buttons, "Apply", self.refresh, "secondary").pack(side="left")
        flat_button(buttons, "Clear", self.clear_filters, "ghost").pack(
            side="left", padx=(px(6), 0))
        self.filter_note = tk.StringVar(value="Dates use your local timezone · YYYY-MM-DD")
        tk.Label(filters.body, textvariable=self.filter_note, bg=COLORS["surface"],
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").grid(
            row=2, column=0, columnspan=6, sticky="ew", pady=(px(6), 0))

        table_card = Card(outer, padding=(2, 2))
        table_card.pack(fill="both", expand=True)
        self.table = DataTable(
            table_card.body,
            [
                {"key": "time", "label": "RECORDED", "width": 134},
                {"key": "ticket", "label": "TICKET", "width": 90},
                {"key": "action", "label": "ACTION", "width": 156},
                {"key": "details", "label": "DETAILS", "width": 550, "stretch": True,
                 "minwidth": 300},
                {"key": "actor", "label": "ACTOR", "width": 118},
            ],
            height=16,
            on_select=self._show_event,
            on_double_click=self._open_ticket,
            empty_title="No audit events match",
            empty_hint="Change the filters or perform a ticket operation.",
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=1)

        detail_card = Card(outer, padding=(14, 10), bg=COLORS["card_soft"],
                           border=COLORS["border_soft"])
        detail_card.pack(fill="x", pady=(px(10), 0))
        self.detail_text = tk.Text(
            detail_card.body, height=4, wrap="word", bg=COLORS["card_soft"],
            fg=COLORS["text_soft"], relief="flat", bd=0, padx=0, pady=0,
            font=FONTS["small"], highlightthickness=0,
        )
        self.detail_text.pack(fill="x")
        bind_scroll_handoff(self.detail_text)
        self.detail_text.insert("1.0", "Select an audit event to inspect its full details.")
        self.detail_text.configure(state="disabled", fg=COLORS["muted"])

        bottom = tk.Frame(outer, bg=COLORS["bg"])
        bottom.pack(fill="x", pady=(px(8), 0))
        self.count_var = tk.StringVar(value="0 events")
        tk.Label(bottom, textvariable=self.count_var, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left")
        self.total_var = tk.StringVar(value="")
        tk.Label(bottom, textvariable=self.total_var, bg=COLORS["bg"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(side="left", padx=(px(12), 0))

    # --------------------------------------------------------------- filters
    def on_show(self) -> None:
        actions = ["All actions"] + self.app.services["audit"].actions()
        self.action_combo.configure(values=actions)
        if self.action_var.get() not in actions:
            self.action_var.set("All actions")
        self.refresh()

    def _schedule_search(self, _event: tk.Event | None = None) -> None:
        if self._search_job:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(260, self.refresh)

    def _parse_dates(self) -> tuple[datetime | None, datetime | None]:
        from_value = self.from_var.get().strip()
        to_value = self.to_var.get().strip()
        try:
            date_from = parse_user_timestamp(from_value + " 00:00:00") if from_value else None
            date_to = parse_user_timestamp(to_value + " 23:59:59") if to_value else None
        except ValueError as exc:
            raise ValueError(
                "Dates must use YYYY-MM-DD (for example 2026-05-01)."
            ) from exc
        if date_from and date_to and date_from > date_to:
            raise ValueError("The FROM date must be earlier than or equal to the TO date.")
        return date_from, date_to

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.action_var.set("All actions")
        self.ticket_var.set("")
        self.from_var.set("")
        self.to_var.set("")
        self.refresh()

    def refresh(self) -> None:
        self._search_job = None
        try:
            date_from, date_to = self._parse_dates()
        except ValueError as exc:
            self.filter_note.set(str(exc))
            self.app.set_status(str(exc), "error")
            return
        action = "" if self.action_var.get() == "All actions" else self.action_var.get()
        try:
            events = self.app.services["audit"].list_events(
                search=self.search_var.get(),
                action=action,
                ticket_id=self.ticket_var.get().strip(),
                date_from=date_from,
                date_to=date_to,
                limit=1000,
            )
            total = self.app.services["audit"].count()
        except Exception as exc:
            self.app.set_status(f"Could not load audit history: {exc}", "error")
            return
        self._events = events
        rows = []
        payloads = []
        tags = []
        for index, event in enumerate(events):
            rows.append((
                format_local(event.created_at, "%d %b %Y · %H:%M"),
                event.ticket_id or "—",
                event.action,
                event.details,
                event.actor,
            ))
            payloads.append(event)
            tone = audit_tag(event.action)
            tags.append([
                "row_even" if index % 2 else "row_odd",
                *( [tone] if tone else [] ),
            ])
        self.table.set_rows(rows, payloads, tags)
        self.count_var.set(f"{len(events)} event(s) shown")
        self.total_var.set(f"{total} total audit event(s) in database")
        self.filter_note.set("Dates use your local timezone · YYYY-MM-DD")

    def _show_event(self, event: AuditEvent | None) -> None:
        self.detail_text.configure(state="normal", fg=COLORS["text_soft"])
        self.detail_text.delete("1.0", "end")
        if not event:
            self.detail_text.insert("1.0", "Select an audit event to inspect its full details.")
            self.detail_text.configure(state="disabled", fg=COLORS["muted"])
            return
        self.detail_text.insert(
            "1.0",
            f"Event #{event.id} · {event.action} · {format_local(event.created_at)}\n"
            f"Ticket: {event.ticket_id or 'system-wide'} · Actor: {event.actor}\n"
            f"{event.details}",
        )
        self.detail_text.configure(state="disabled")
        self.detail_text.see("1.0")

    def _open_ticket(self, event: AuditEvent) -> None:
        if event.ticket_id:
            self.app.open_ticket_details(event.ticket_id, on_changed=self.refresh)

    def export_audit(self) -> None:
        if not self._events:
            self.app.set_status("There are no filtered audit events to export.", "warning")
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export audit events",
            defaultextension=".csv",
            initialfile=f"opsflow-audit-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            count = self.app.services["csv"].export_audit(filename, self._events)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.app.set_status(
            f"Exported {count} audit event(s) to {Path(filename).name}.", "success"
        )
