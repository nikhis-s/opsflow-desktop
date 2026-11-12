"""Escalation watchlist and immutable internal escalation history."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from models import EscalationEvent, format_local, human_duration, truncate
from ui.components import (
    Card, DataTable, KpiCard, Page, ScrollableFrame, SectionHeader,
    flat_button,
)
from ui.theme import COLORS, FONTS, SLA_COLORS


class EscalationsPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self._search_job: str | None = None
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=26, pady=20)

        header = SectionHeader(
            outer, "Escalation desk",
            "Deterministic SLA alerts, critical ticket watch and recorded escalation history.",
        )
        header.pack(fill="x", pady=(0, 12))
        flat_button(header.actions, "Export history", self.export_history,
                    "secondary").pack(side="right", padx=(8, 0))
        flat_button(header.actions, "Run escalation scan", self.run_scan, "primary").pack(
            side="right")

        banner = tk.Frame(outer, bg=COLORS["card"], highlightthickness=1,
                          highlightbackground=COLORS["amber_deep"])
        banner.pack(fill="x", pady=(0, 16))
        tk.Label(banner, text="INTERNAL ONLY", bg=COLORS["card"], fg=COLORS["amber"],
                 font=FONTS["tiny"]).pack(side="left", padx=(14, 10), pady=10)
        tk.Label(
            banner,
            text="OpsFlow records escalations inside this application. It does not send emails, pages or "
                 "external notifications, and never claims a person was contacted.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"],
        ).pack(side="left", fill="x", expand=True, pady=10)

        kpis = tk.Frame(outer, bg=COLORS["bg"])
        kpis.pack(fill="x", pady=(0, 16))
        for column in range(4):
            kpis.grid_columnconfigure(column, weight=1, uniform="esc-kpi")
        self.kpi_total = KpiCard(kpis, "Recorded escalations", COLORS["blue"], "▲",
                                 "All-time internal events")
        self.kpi_critical = KpiCard(kpis, "Critical events", COLORS["red"], "!",
                                   "Breaches and critical flags")
        self.kpi_warning = KpiCard(kpis, "Warnings", COLORS["amber"], "◷",
                                   "Approaching deadlines")
        self.kpi_watch = KpiCard(kpis, "Critical unresolved", COLORS["purple"], "◆",
                                "Live watchlist")
        for index, card in enumerate(
            (self.kpi_total, self.kpi_critical, self.kpi_warning, self.kpi_watch)
        ):
            card.grid(row=0, column=index, sticky="nsew",
                      padx=(0 if index == 0 else 6, 0))

        watch_card = Card(outer, padding=(18, 15))
        watch_card.pack(fill="x", pady=(0, 16))
        watch_header = tk.Frame(watch_card.body, bg=COLORS["card"])
        watch_header.pack(fill="x", pady=(0, 8))
        watch_text = tk.Frame(watch_header, bg=COLORS["card"])
        watch_text.pack(side="left", fill="x", expand=True)
        tk.Label(watch_text, text="Critical unresolved watchlist", bg=COLORS["card"],
                 fg=COLORS["text"], font=FONTS["h2"], anchor="w").pack(fill="x")
        tk.Label(
            watch_text,
            text="Every critical-priority ticket still unresolved, ordered by resolution deadline.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["tiny"], anchor="w",
        ).pack(fill="x", pady=(2, 0))
        self.watch_count = tk.StringVar(value="")
        tk.Label(watch_header, textvariable=self.watch_count, bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="right")
        self.watch_table = DataTable(
            watch_card.body,
            [
                {"key": "id", "label": "TICKET", "width": 82},
                {"key": "title", "label": "TITLE", "width": 280, "stretch": True,
                 "minwidth": 170},
                {"key": "assignee", "label": "ASSIGNEE", "width": 120},
                {"key": "status", "label": "STATUS", "width": 94},
                {"key": "response", "label": "RESPONSE SLA", "width": 104},
                {"key": "resolution", "label": "RESOLUTION SLA", "width": 112},
                {"key": "remaining", "label": "TIME LEFT", "width": 90},
            ],
            height=4,
            on_double_click=self._open_ticket,
            empty_title="No critical unresolved tickets",
            empty_hint="Critical requests that are still open will appear here.",
        )
        self.watch_table.pack(fill="both", expand=True)

        history_card = Card(outer, padding=(18, 15))
        history_card.pack(fill="both", expand=True)
        history_header = tk.Frame(history_card.body, bg=COLORS["card"])
        history_header.pack(fill="x", pady=(0, 10))
        history_text = tk.Frame(history_header, bg=COLORS["card"])
        history_text.pack(side="left", fill="x", expand=True)
        tk.Label(history_text, text="Escalation history", bg=COLORS["card"],
                 fg=COLORS["text"], font=FONTS["h2"], anchor="w").pack(fill="x")
        tk.Label(
            history_text,
            text="Each reason is deterministic. Duplicate alerts for the same deadline are suppressed.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["tiny"], anchor="w",
        ).pack(fill="x", pady=(2, 0))
        self.level_var = tk.StringVar(value="All levels")
        self.level_combo = ttk.Combobox(
            history_header, textvariable=self.level_var, state="readonly", width=14,
            values=["All levels", "CRITICAL", "WARNING", "INFO"],
        )
        self.level_combo.pack(side="right", padx=(8, 0))
        self.level_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_history())

        filter_row = tk.Frame(history_card.body, bg=COLORS["card"])
        filter_row.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        search = ttk.Entry(filter_row, textvariable=self.search_var, style="Search.TEntry")
        search.pack(side="left", fill="x", expand=True)
        search.bind("<KeyRelease>", self._schedule_search)
        flat_button(filter_row, "Clear", self._clear_search, "ghost").pack(
            side="right", padx=(8, 0))
        self.history_count = tk.StringVar(value="")
        tk.Label(filter_row, textvariable=self.history_count, bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="right", padx=(0, 10))

        self.history_table = DataTable(
            history_card.body,
            [
                {"key": "time", "label": "RECORDED", "width": 126},
                {"key": "ticket", "label": "TICKET", "width": 84},
                {"key": "level", "label": "LEVEL", "width": 84},
                {"key": "kind", "label": "TYPE", "width": 142},
                {"key": "reason", "label": "REASON", "width": 420, "stretch": True,
                 "minwidth": 240},
            ],
            height=8,
            on_select=self._show_event,
            empty_title="No escalation events recorded",
            empty_hint="Run an SLA scan or wait for the scheduled scan.",
        )
        self.history_table.pack(fill="both", expand=True)

        detail_frame = tk.Frame(history_card.body, bg=COLORS["card_soft"],
                                highlightthickness=1,
                                highlightbackground=COLORS["border_soft"])
        detail_frame.pack(fill="x", pady=(10, 0))
        self.detail_text = tk.Text(
            detail_frame, height=4, wrap="word", bg=COLORS["card_soft"],
            fg=COLORS["text_soft"], relief="flat", bd=0, padx=12, pady=9,
            font=FONTS["small"], highlightthickness=0,
        )
        self.detail_text.pack(fill="x")
        self.detail_text.insert("1.0", "Select an escalation to view its full recorded reason and context.")
        self.detail_text.configure(state="disabled", fg=COLORS["muted"])

    # ---------------------------------------------------------------- refresh
    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.refresh_watchlist()
        self.refresh_history()
        counts = self.app.services["analytics"].escalation_counts()
        self.kpi_total.set(counts.get("TOTAL", 0), "All recorded internal events")
        self.kpi_critical.set(counts.get("CRITICAL", 0), "Breach and critical-priority flags")
        self.kpi_warning.set(counts.get("WARNING", 0), "Deadline warning events")
        self.kpi_watch.set(len(self.app.services["escalations"].critical_unresolved()),
                           "Active critical tickets")

    def refresh_watchlist(self) -> None:
        items = self.app.services["escalations"].critical_unresolved()
        rows = []
        payloads = []
        tags = []
        for index, (ticket, evaluation) in enumerate(items):
            rows.append((
                ticket.id,
                truncate(ticket.title, 55),
                ticket.assignee,
                ticket.status,
                evaluation.response.state,
                evaluation.resolution.state,
                human_duration(abs(evaluation.resolution.remaining_seconds or 0))
                + (" left" if (evaluation.resolution.remaining_seconds or 0) >= 0 else " over"),
            ))
            payloads.append(ticket.id)
            tags.append([
                "row_even" if index % 2 else "row_odd",
                "sla_breach" if evaluation.overall_state in ("Breached", "Missed")
                else "sla_risk" if evaluation.overall_state == "At risk" else "sla_met",
            ])
        self.watch_table.set_rows(rows, payloads, tags)
        self.watch_count.set(f"{len(items)} ticket(s)")

    def refresh_history(self) -> None:
        level = "" if self.level_var.get() == "All levels" else self.level_var.get()
        events = self.app.services["escalations"].list_events(
            search=self.search_var.get(), level=level, limit=500,
        )
        rows = []
        payloads = []
        tags = []
        for index, event in enumerate(events):
            rows.append((
                format_local(event.created_at, "%d %b · %H:%M"),
                event.ticket_id,
                event.level,
                event.escalation_type.replace("_", " ").title(),
                event.reason,
            ))
            payloads.append(event)
            tone = "danger" if event.level == "CRITICAL" else (
                "warning" if event.level == "WARNING" else ""
            )
            tags.append([
                "row_even" if index % 2 else "row_odd",
                *( [tone] if tone else [] ),
            ])
        self.history_table.set_rows(rows, payloads, tags)
        self.history_count.set(f"{len(events)} event(s)")

    def _schedule_search(self, _event: tk.Event | None = None) -> None:
        if self._search_job:
            try:
                self.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.after(260, self.refresh_history)

    def _clear_search(self) -> None:
        self.search_var.set("")
        self.level_var.set("All levels")
        self.refresh_history()

    def _show_event(self, event: EscalationEvent | None) -> None:
        self.detail_text.configure(state="normal", fg=COLORS["text_soft"])
        self.detail_text.delete("1.0", "end")
        if event is None:
            self.detail_text.insert("1.0", "Select an escalation to view its full recorded reason and context.")
            self.detail_text.configure(state="disabled", fg=COLORS["muted"])
            return
        self.detail_text.insert(
            "1.0",
            f"{event.reason}\n{event.details}\n"
            f"Level: {event.level} · Type: {event.escalation_type} · "
            f"Recorded {format_local(event.created_at)} · Ticket {event.ticket_id}",
        )
        self.detail_text.configure(state="disabled")
        self.detail_text.see("1.0")

    def _open_ticket(self, ticket_id: str) -> None:
        self.app.open_ticket_details(ticket_id, on_changed=self.refresh)

    # ---------------------------------------------------------------- actions
    def run_scan(self) -> None:
        events = self.app.run_escalation_scan()
        self.refresh()
        if events:
            self.app.set_status(
                f"Escalation scan recorded {len(events)} new event(s).", "warning"
            )
        else:
            self.app.set_status("Escalation scan complete · no new events.", "success")

    def export_history(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export escalation history",
            defaultextension=".csv",
            initialfile=f"opsflow-escalations-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            count = self.app.services["csv"].export_escalations(filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.app.set_status(
            f"Exported {count} escalation event(s) to {Path(filename).name}.", "success"
        )
