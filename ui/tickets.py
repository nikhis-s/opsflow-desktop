"""Ticket queue: search, filters, sorting, CRUD actions and CSV exchange."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from models import (
    PRIORITIES,
    STATUSES,
    Ticket,
    format_local,
    truncate,
)
from services.csv_service import CSVFormatError
from ui.components import (
    Card,
    DataTable,
    Page,
    ScrollableFrame,
    SectionHeader,
    flat_button,
    ticket_row_tags,
)
from ui.dialogs import (
    AssignDialog,
    CommentDialog,
    ConfirmDialog,
    ImportSummaryDialog,
    StatusDialog,
    TicketDialog,
)
from ui.theme import COLORS, FONTS, px

SORT_OPTIONS = {
    "Newest first": ("created_at", True),
    "Oldest first": ("created_at", False),
    "Deadline soonest": ("resolution_deadline", False),
    "Priority high → low": ("priority", False),
    "Recently updated": ("updated_at", True),
    "Ticket ID": ("id", False),
}


class TicketsPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self._search_job: str | None = None
        self._last_tickets: list[Ticket] = []

        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=px(26), pady=px(20))

        header = SectionHeader(
            outer, "Ticket queue",
            "Search, filter and manage every request from intake to resolution.",
        )
        header.pack(fill="x", pady=(0, px(14)))
        flat_button(header.actions, "Import CSV", self.import_csv, "secondary").pack(
            side="right", padx=(px(8), 0))
        flat_button(header.actions, "Export", self.export_filtered, "secondary").pack(
            side="right", padx=(px(8), 0))
        flat_button(header.actions, "New ticket", self.open_create, "primary").pack(
            side="right")

        filters = Card(outer, padding=(14, 10), bg=COLORS["surface"])
        filters.pack(fill="x", pady=(0, px(12)))
        filter_grid = filters.body
        filter_grid.grid_columnconfigure(0, weight=3)
        filter_grid.grid_columnconfigure(1, weight=1)
        filter_grid.grid_columnconfigure(2, weight=1)
        filter_grid.grid_columnconfigure(3, weight=2)
        filter_grid.grid_columnconfigure(4, weight=1)
        filter_grid.grid_columnconfigure(5, weight=0)

        labels = ["SEARCH", "PRIORITY", "STATUS", "ASSIGNEE", "SORT"]
        for column, label in enumerate(labels):
            tk.Label(filter_grid, text=label, bg=COLORS["surface"], fg=COLORS["subtle"],
                     font=FONTS["micro"], anchor="w").grid(
                row=0, column=column, sticky="ew", padx=(0, px(8)), pady=(0, px(5)))

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(filter_grid, textvariable=self.search_var,
                                      style="Search.TEntry")
        self.search_entry.grid(row=1, column=0, sticky="ew", padx=(0, px(8)))
        self.search_entry.bind("<KeyRelease>", self._schedule_search)
        self.search_entry.bind("<Return>", lambda _event: self.refresh())

        self.priority_var = tk.StringVar(value="All priorities")
        self.priority_combo = ttk.Combobox(
            filter_grid, textvariable=self.priority_var,
            values=["All priorities", *PRIORITIES], state="readonly",
        )
        self.priority_combo.grid(row=1, column=1, sticky="ew", padx=(0, px(8)))
        self.priority_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.status_var = tk.StringVar(value="All statuses")
        self.status_combo = ttk.Combobox(
            filter_grid, textvariable=self.status_var,
            values=["All statuses", *STATUSES], state="readonly",
        )
        self.status_combo.grid(row=1, column=2, sticky="ew", padx=(0, px(8)))
        self.status_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.assignee_var = tk.StringVar(value="All assignees")
        self.assignee_combo = ttk.Combobox(
            filter_grid, textvariable=self.assignee_var, state="readonly",
        )
        self.assignee_combo.grid(row=1, column=3, sticky="ew", padx=(0, px(8)))
        self.assignee_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        self.sort_var = tk.StringVar(value="Newest first")
        self.sort_combo = ttk.Combobox(
            filter_grid, textvariable=self.sort_var,
            values=list(SORT_OPTIONS.keys()), state="readonly",
        )
        self.sort_combo.grid(row=1, column=4, sticky="ew", padx=(0, px(8)))
        self.sort_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())

        flat_button(filter_grid, "Clear", self.clear_filters, "ghost").grid(
            row=1, column=5, sticky="e")

        table_card = Card(outer, padding=(2, 2))
        table_card.pack(fill="both", expand=True)
        self.table = DataTable(
            table_card.body,
            [
                {"key": "id", "label": "TICKET", "width": 80},
                {"key": "title", "label": "TITLE", "width": 230, "stretch": True,
                 "minwidth": 150},
                {"key": "requester", "label": "REQUESTER", "width": 112},
                {"key": "assignee", "label": "ASSIGNEE", "width": 105},
                {"key": "priority", "label": "PRIORITY", "width": 76},
                {"key": "status", "label": "STATUS", "width": 94},
                {"key": "created", "label": "CREATED", "width": 112},
                {"key": "deadline", "label": "RESOLUTION DUE", "width": 128},
                {"key": "sla", "label": "SLA", "width": 78},
            ],
            height=16,
            on_double_click=self._open_details,
            on_select=lambda _payload: self._update_action_state(),
            empty_title="No tickets match this view",
            empty_hint="Create a ticket or clear the active filters.",
        )
        self.table.pack(fill="both", expand=True, padx=1, pady=1)
        self.table.tree.bind("<Button-3>", self._context_menu)
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Open details", command=self.open_selected)
        self._menu.add_command(label="Edit ticket", command=self.edit_selected)
        self._menu.add_command(label="Assign", command=self.assign_selected)
        self._menu.add_command(label="Change status", command=self.status_selected)
        self._menu.add_command(label="Add internal note", command=self.comment_selected)
        self._menu.add_separator()
        self._menu.add_command(label="Delete ticket", command=self.delete_selected)

        footer = tk.Frame(outer, bg=COLORS["bg"])
        footer.pack(fill="x", pady=(px(10), 0))
        self.count_var = tk.StringVar(value="0 tickets")
        tk.Label(footer, textvariable=self.count_var, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left")

        self.action_buttons: list[ttk.Button] = []
        for label, command, kind in (
            ("Delete", self.delete_selected, "ghost"),
            ("Add note", self.comment_selected, "ghost"),
            ("Change status", self.status_selected, "ghost"),
            ("Assign", self.assign_selected, "ghost"),
            ("Edit", self.edit_selected, "secondary"),
            ("Open details", self.open_selected, "primary"),
        ):
            button = flat_button(footer, label, command, kind)
            button.pack(side="right", padx=(px(8), 0))
            self.action_buttons.append(button)
        self._update_action_state()

        self.schedule(350, self._update_action_state)

    # --------------------------------------------------------------- filters
    def _mapped_priority(self) -> str:
        value = self.priority_var.get()
        return "" if value == "All priorities" else value

    def _mapped_status(self) -> str:
        value = self.status_var.get()
        return "" if value == "All statuses" else value

    def _mapped_assignee(self) -> str:
        value = self.assignee_var.get()
        return "" if value == "All assignees" else value

    def _schedule_search(self, _event: tk.Event | None = None) -> None:
        if self._search_job:
            try:
                self.cancel_scheduled(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.schedule(260, self.refresh)

    def clear_filters(self) -> None:
        self.search_var.set("")
        self.priority_var.set("All priorities")
        self.status_var.set("All statuses")
        self.assignee_var.set("All assignees")
        self.sort_var.set("Newest first")
        self.refresh()

    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    # ---------------------------------------------------------------- refresh
    def on_show(self) -> None:
        assignees = ["All assignees", *self.app.services["tickets"].get_assignees()]
        self.assignee_combo.configure(values=assignees)
        if self.assignee_var.get() not in assignees:
            self.assignee_var.set("All assignees")
        self.refresh()

    def refresh(self) -> None:
        self._search_job = None
        tickets = self.app.services["tickets"]
        sort_field, descending = SORT_OPTIONS.get(
            self.sort_var.get(), ("created_at", True)
        )
        selected = self.table.selected_payload()
        try:
            items = tickets.list_tickets(
                search=self.search_var.get(),
                priority=self._mapped_priority(),
                status=self._mapped_status(),
                assignee=self._mapped_assignee(),
                sort=sort_field,
                descending=descending,
            )
        except Exception as exc:
            self.app.set_status(f"Could not load tickets: {exc}", "error")
            return
        self._last_tickets = items
        evaluations = self.app.services["sla"].evaluate_many(items)
        rows: list[tuple[Any, ...]] = []
        payloads: list[str] = []
        tags: list[list[str]] = []
        for index, ticket in enumerate(items):
            evaluation = evaluations[ticket.id]
            rows.append((
                ticket.id,
                truncate(ticket.title, 54),
                ticket.requester,
                ticket.assignee,
                ticket.priority,
                ticket.status,
                format_local(ticket.created_at, "%d %b · %H:%M"),
                format_local(ticket.resolution_deadline, "%d %b · %H:%M"),
                evaluation.overall_state,
            ))
            payloads.append(ticket.id)
            tags.append(ticket_row_tags(index, ticket.priority, evaluation.overall_state))
        self.table.set_rows(rows, payloads, tags)
        if selected and selected in payloads:
            self.table.select_payload(selected)
        self.count_var.set(
            f"{len(items)} ticket{'s' if len(items) != 1 else ''}"
            + (" · filtered view" if self._filters_active() else " · full queue")
        )
        self._update_action_state()

    def _filters_active(self) -> bool:
        return bool(
            self.search_var.get().strip()
            or self._mapped_priority()
            or self._mapped_status()
            or self._mapped_assignee()
        )

    def _selected_ticket(self) -> Ticket | None:
        ticket_id = self.table.selected_payload()
        if not ticket_id:
            self.app.set_status("Select a ticket first.", "warning")
            return None
        try:
            return self.app.services["tickets"].get_ticket(ticket_id)
        except Exception as exc:
            self.app.set_status(str(exc), "error")
            return None

    def _update_action_state(self) -> None:
        state = "normal" if self.table.selected_payload() else "disabled"
        for button in getattr(self, "action_buttons", []):
            try:
                button.state(["!disabled"] if state == "normal" else ["disabled"])
            except tk.TclError:
                pass

    def _context_menu(self, event: tk.Event) -> None:
        item = self.table.tree.identify_row(event.y)
        if item:
            self.table.tree.selection_set(item)
            self.table.tree.focus(item)
            self._update_action_state()
            self._menu.tk_popup(event.x_root, event.y_root)

    # ---------------------------------------------------------------- actions
    def open_create(self) -> None:
        TicketDialog(
            self, self.app.services["tickets"], self.app.services["sla"],
            on_saved=self._created,
        )

    def _created(self, ticket: Ticket) -> None:
        self.app.set_status(f"Ticket {ticket.id} created.", "success")
        self.clear_filters()
        self.app.services["escalations"].run()
        self.refresh()
        self.table.select_payload(ticket.id)
        self._update_action_state()
        self.app.notify_data_changed()

    def _open_details(self, ticket_id: str) -> None:
        self.app.open_ticket_details(ticket_id, on_changed=self._after_change)

    def open_selected(self) -> None:
        ticket_id = self.table.selected_payload()
        if ticket_id:
            self._open_details(ticket_id)
        else:
            self.app.set_status("Select a ticket to open.", "warning")

    def edit_selected(self) -> None:
        ticket = self._selected_ticket()
        if not ticket:
            return
        TicketDialog(
            self, self.app.services["tickets"], self.app.services["sla"],
            ticket=ticket, on_saved=lambda _ticket: self._after_change(),
        )

    def assign_selected(self) -> None:
        ticket = self._selected_ticket()
        if not ticket:
            return
        AssignDialog(
            self, self.app.services["tickets"], ticket,
            on_saved=lambda _ticket: self._after_change(),
        )

    def status_selected(self) -> None:
        ticket = self._selected_ticket()
        if not ticket:
            return
        StatusDialog(
            self, self.app.services["tickets"], ticket,
            on_saved=lambda _ticket: self._after_change(),
        )

    def comment_selected(self) -> None:
        ticket = self._selected_ticket()
        if not ticket:
            return
        CommentDialog(
            self, self.app.services["tickets"], ticket,
            on_saved=lambda _comment: self._after_change(),
        )

    def delete_selected(self) -> None:
        ticket = self._selected_ticket()
        if not ticket:
            return

        def confirm() -> None:
            try:
                self.app.services["tickets"].delete_ticket(ticket.id)
            except Exception as exc:
                messagebox.showerror("OpsFlow", f"Could not delete ticket: {exc}", parent=self)
                return
            self.app.set_status(f"Ticket {ticket.id} deleted. Audit history preserved.", "warning")
            self._after_change()

        ConfirmDialog(
            self, "Delete ticket",
            f"Delete {ticket.id} (“{truncate(ticket.title, 70)}”) and its comments? "
            "Audit and escalation history will be preserved.",
            confirm_label="Delete ticket", danger=True, on_confirm=confirm,
        )

    def _after_change(self) -> None:
        self.on_show()
        self.app.notify_data_changed()

    # ------------------------------------------------------------------- CSV
    def export_filtered(self) -> None:
        if not self._last_tickets:
            self.app.set_status("There are no visible tickets to export.", "warning")
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export filtered tickets",
            defaultextension=".csv",
            initialfile=f"opsflow-tickets-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            count = self.app.services["csv"].export_tickets(filename, self._last_tickets)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.app.set_status(f"Exported {count} filtered ticket(s) to {Path(filename).name}.", "success")

    def import_csv(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="Import tickets from CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            result = self.app.services["csv"].import_tickets(filename)
        except CSVFormatError as exc:
            messagebox.showerror("CSV import rejected", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("CSV import failed", str(exc), parent=self)
            return
        self.refresh()
        self.on_show()
        self.app.notify_data_changed()
        self.app.set_status(
            f"CSV import: {result.summary}.", "success" if not result.errors else "warning"
        )
        ImportSummaryDialog(self, Path(filename).name, result)
