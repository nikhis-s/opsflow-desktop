"""SLA policy configuration, live monitoring and compliance reporting."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from models import (
    DEFAULT_POLICIES, PRIORITIES, duration_minutes, format_local, human_duration,
    truncate,
)
from ui.components import (
    Badge, Card, DataTable, KpiCard, Page, ScrollableFrame, SectionHeader,
    flat_button, ticket_row_tags,
)
from ui.theme import COLORS, FONTS, SLA_COLORS, px


class SLAPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self.policy_vars: dict[str, dict[str, tk.StringVar]] = {}
        self._monitor_items: list[tuple[Any, Any]] = []
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=px(26), pady=px(20))

        header = SectionHeader(
            outer, "SLA center",
            "Configure deterministic response and resolution targets, then monitor live risk.",
        )
        header.pack(fill="x", pady=(0, px(16)))
        flat_button(header.actions, "Export SLA report", self.export_report,
                    "secondary").pack(side="right", padx=(px(8), 0))
        flat_button(header.actions, "Run SLA scan", self.run_scan, "primary").pack(
            side="right")

        kpis = tk.Frame(outer, bg=COLORS["bg"])
        kpis.pack(fill="x", pady=(0, px(16)))
        for column in range(4):
            kpis.grid_columnconfigure(column, weight=1, uniform="sla-kpi")
        self.kpi_response = KpiCard(kpis, "Response compliance", COLORS["accent"], "↺",
                                    "First-response target")
        self.kpi_resolution = KpiCard(kpis, "Resolution compliance", COLORS["green"], "✓",
                                      "Resolution target")
        self.kpi_risk = KpiCard(kpis, "At risk now", COLORS["amber"], "▲",
                                "Active warning window")
        self.kpi_breach = KpiCard(kpis, "Breached now", COLORS["red"], "!",
                                  "Active past deadline")
        for index, card in enumerate(
            (self.kpi_response, self.kpi_resolution, self.kpi_risk, self.kpi_breach)
        ):
            card.grid(row=0, column=index, sticky="nsew",
                      padx=(0 if index == 0 else px(6), 0))

        policy_card = Card(outer, padding=(18, 15))
        policy_card.pack(fill="x", pady=(0, px(16)))
        policy_header = tk.Frame(policy_card.body, bg=COLORS["card"])
        policy_header.pack(fill="x", pady=(0, px(10)))
        policy_text = tk.Frame(policy_header, bg=COLORS["card"])
        policy_text.pack(side="left", fill="x", expand=True)
        tk.Label(policy_text, text="SLA policies", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x")
        tk.Label(
            policy_text,
            text="Targets start at ticket creation. Saving a policy recalculates active tickets and writes an audit event.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["tiny"], anchor="w",
        ).pack(fill="x", pady=(px(2), 0))
        flat_button(policy_header, "Reset defaults", self.stage_defaults, "ghost").pack(
            side="right", padx=(0, px(8)))
        flat_button(policy_header, "Recalculate active", self.recalculate_active,
                    "secondary").pack(side="right", padx=(0, px(8)))
        flat_button(policy_header, "Save policies", self.save_policies, "primary").pack(
            side="right", padx=(0, px(8)))

        grid = tk.Frame(policy_card.body, bg=COLORS["card"])
        grid.pack(fill="x")
        for column, weight in enumerate((2, 2, 2, 2, 2)):
            grid.grid_columnconfigure(column, weight=weight, uniform="policy")
        headings = ["PRIORITY", "RESPONSE TARGET", "RESOLUTION TARGET",
                    "AT-RISK WARNING", "LAST UPDATED"]
        for column, label in enumerate(headings):
            tk.Label(grid, text=label, bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["micro"], anchor="w").grid(
                row=0, column=column, sticky="ew", padx=(0, px(10)), pady=(0, px(6)))

        for row_index, priority in enumerate(PRIORITIES, start=1):
            tk.Frame(grid, bg=COLORS["border_soft"], height=px(1)).grid(
                row=row_index * 2 - 1, column=0, columnspan=5, sticky="ew", pady=px(4))
            badge = Badge(grid, priority, bg=COLORS["card"])
            badge.set_priority(priority)
            badge.grid(row=row_index * 2, column=0, sticky="w", padx=(0, px(10)), pady=px(7))
            values = {
                "response": tk.StringVar(),
                "resolution": tk.StringVar(),
                "warn": tk.StringVar(),
            }
            self.policy_vars[priority] = values
            response_box = tk.Frame(grid, bg=COLORS["card"])
            response_box.grid(row=row_index * 2, column=1, sticky="w", padx=(0, px(10)))
            ttk.Entry(response_box, textvariable=values["response"], width=8).pack(side="left")
            tk.Label(response_box, text="min", bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"]).pack(side="left", padx=(px(5), 0))
            resolution_box = tk.Frame(grid, bg=COLORS["card"])
            resolution_box.grid(row=row_index * 2, column=2, sticky="w", padx=(0, px(10)))
            ttk.Entry(resolution_box, textvariable=values["resolution"], width=8).pack(side="left")
            tk.Label(resolution_box, text="min", bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"]).pack(side="left", padx=(px(5), 0))
            warn_box = tk.Frame(grid, bg=COLORS["card"])
            warn_box.grid(row=row_index * 2, column=3, sticky="w", padx=(0, px(10)))
            ttk.Entry(warn_box, textvariable=values["warn"], width=7).pack(side="left")
            tk.Label(warn_box, text="% consumed", bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"]).pack(side="left", padx=(px(5), 0))
            updated = tk.Label(grid, textvariable=tk.StringVar(), bg=COLORS["card"],
                               fg=COLORS["muted"], font=FONTS["tiny"], anchor="w")
            updated.grid(row=row_index * 2, column=4, sticky="w")
            values["updated_label"] = updated  # type: ignore[assignment]

        self.policy_message_var = tk.StringVar(value="")
        self.policy_message = tk.Label(
            policy_card.body, textvariable=self.policy_message_var, bg=COLORS["card"],
            fg=COLORS["green"], font=FONTS["small"], anchor="w",
        )
        self.policy_message.pack(fill="x", pady=(px(10), 0))

        monitor_card = Card(outer, padding=(18, 15))
        monitor_card.pack(fill="both", expand=True)
        monitor_header = tk.Frame(monitor_card.body, bg=COLORS["card"])
        monitor_header.pack(fill="x", pady=(0, px(10)))
        monitor_text = tk.Frame(monitor_header, bg=COLORS["card"])
        monitor_text.pack(side="left", fill="x", expand=True)
        tk.Label(monitor_text, text="Active SLA monitor", bg=COLORS["card"],
                 fg=COLORS["text"], font=FONTS["h2"], anchor="w").pack(fill="x")
        tk.Label(monitor_text, text="Only unresolved tickets have a live deadline clock.",
                 bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["tiny"],
                 anchor="w").pack(fill="x", pady=(px(2), 0))
        self.state_var = tk.StringVar(value="All active")
        state_combo = ttk.Combobox(
            monitor_header, textvariable=self.state_var, state="readonly",
            values=["All active", "At risk", "Breached", "On track"], width=15,
        )
        state_combo.pack(side="right")
        state_combo.bind("<<ComboboxSelected>>", lambda _event: self._render_monitor())
        self.monitor_count_var = tk.StringVar(value="")
        tk.Label(monitor_header, textvariable=self.monitor_count_var, bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="right", padx=(0, px(12)))

        self.monitor_table = DataTable(
            monitor_card.body,
            [
                {"key": "id", "label": "TICKET", "width": 82},
                {"key": "title", "label": "TITLE", "width": 225, "stretch": True,
                 "minwidth": 150},
                {"key": "priority", "label": "PRIORITY", "width": 76},
                {"key": "response_due", "label": "RESPONSE DUE", "width": 116},
                {"key": "response", "label": "RESPONSE", "width": 78},
                {"key": "resolution_due", "label": "RESOLUTION DUE", "width": 122},
                {"key": "resolution", "label": "RESOLUTION", "width": 82},
                {"key": "overall", "label": "OVERALL", "width": 80},
            ],
            height=8,
            on_double_click=self._open_ticket,
            empty_title="No active tickets",
            empty_hint="Resolved and closed tickets leave the live SLA monitor.",
        )
        self.monitor_table.pack(fill="both", expand=True)

        tk.Label(
            outer,
            text="Compliance basis: response compliance uses the first-response timestamp; "
                 "resolution compliance uses the resolved timestamp. Breached means the deadline "
                 "has passed with no completion timestamp.",
            bg=COLORS["bg"], fg=COLORS["subtle"], font=FONTS["tiny"],
            justify="left", wraplength=px(1000),
        ).pack(fill="x", pady=(px(10), px(2)))

    # ---------------------------------------------------------------- policies
    def _load_policy_values(self) -> None:
        policies = self.app.services["sla"].get_policies()
        for priority, values in self.policy_vars.items():
            policy = policies.get(priority)
            if not policy:
                continue
            values["response"].set(str(policy.response_minutes))
            values["resolution"].set(str(policy.resolution_minutes))
            values["warn"].set(str(policy.at_risk_percent))
            label = values.get("updated_label")
            if isinstance(label, tk.Label):
                label.configure(text=format_local(policy.updated_at, "%d %b %H:%M"))

    def save_policies(self) -> None:
        updates: dict[str, tuple[int, int, int]] = {}
        try:
            for priority, values in self.policy_vars.items():
                updates[priority] = (
                    int(values["response"].get().strip()),
                    int(values["resolution"].get().strip()),
                    int(values["warn"].get().strip()),
                )
        except ValueError:
            self._policy_error("All targets and thresholds must be whole numbers.")
            return
        try:
            self.app.services["sla"].update_policies(updates)
        except ValueError as exc:
            self._policy_error(str(exc))
            return
        changed = self.app.services["tickets"].recalculate_active_deadlines()
        self._load_policy_values()
        self.app.services["escalations"].run()
        self.refresh()
        message = f"SLA policies saved. {changed} active ticket(s) recalculated."
        self.policy_message.configure(fg=COLORS["green"])
        self.policy_message_var.set(message)
        self.app.set_status(message, "success")
        self.app.notify_data_changed()

    def stage_defaults(self) -> None:
        for priority, (response, resolution, warn) in DEFAULT_POLICIES.items():
            values = self.policy_vars[priority]
            values["response"].set(str(response))
            values["resolution"].set(str(resolution))
            values["warn"].set(str(warn))
        self.policy_message.configure(fg=COLORS["amber"])
        self.policy_message_var.set("Default targets staged. Click Save policies to apply and audit them.")

    def recalculate_active(self) -> None:
        changed = self.app.services["tickets"].recalculate_active_deadlines()
        self.refresh()
        self.policy_message.configure(fg=COLORS["accent"])
        self.policy_message_var.set(f"Recalculated deadlines for {changed} active ticket(s).")
        self.app.set_status(f"Recalculated {changed} active ticket deadline(s).", "success")
        self.app.notify_data_changed()

    def _policy_error(self, message: str) -> None:
        self.policy_message.configure(fg=COLORS["red"])
        self.policy_message_var.set(message)
        self.app.set_status(message, "error")

    # ----------------------------------------------------------------- monitor
    def on_show(self) -> None:
        self._load_policy_values()
        self.refresh()

    def refresh(self) -> None:
        analytics = self.app.services["analytics"]
        sla = self.app.services["sla"]
        tickets = analytics.all_tickets()
        resolution_pct, response_pct, completed, responded = sla.compliance(tickets)
        evaluations = sla.evaluate_many(tickets)
        active = [(ticket, evaluations[ticket.id]) for ticket in tickets if ticket.active]
        risk_count = sum(1 for _ticket, ev in active if ev.overall_state == "At risk")
        breach_count = sum(1 for _ticket, ev in active if ev.overall_state == "Breached")
        self.kpi_response.set(
            f"{response_pct:.0f}%" if response_pct is not None else "—",
            f"{responded} ticket(s) with a response stamp",
        )
        self.kpi_resolution.set(
            f"{resolution_pct:.0f}%" if resolution_pct is not None else "—",
            f"{completed} completed ticket(s)",
        )
        self.kpi_risk.set(risk_count, "Inside the at-risk warning window")
        self.kpi_breach.set(breach_count, "Past a response or resolution deadline")
        self._monitor_items = analytics.sla_monitor()
        self._render_monitor()

    def _render_monitor(self) -> None:
        state = self.state_var.get()
        items = self._monitor_items
        if state == "At risk":
            items = [(ticket, evaluation) for ticket, evaluation in items
                     if evaluation.overall_state == "At risk"]
        elif state == "Breached":
            items = [(ticket, evaluation) for ticket, evaluation in items
                     if evaluation.overall_state == "Breached"]
        elif state == "On track":
            items = [(ticket, evaluation) for ticket, evaluation in items
                     if evaluation.overall_state in ("On track", "Met")]
        rows = []
        payloads = []
        tags = []
        for index, (ticket, evaluation) in enumerate(items):
            rows.append((
                ticket.id,
                truncate(ticket.title, 50),
                ticket.priority,
                format_local(ticket.response_deadline, "%d %b · %H:%M"),
                evaluation.response.state,
                format_local(ticket.resolution_deadline, "%d %b · %H:%M"),
                evaluation.resolution.state,
                evaluation.overall_state,
            ))
            payloads.append(ticket.id)
            tags.append(ticket_row_tags(index, ticket.priority, evaluation.overall_state))
        self.monitor_table.set_rows(rows, payloads, tags)
        self.monitor_count_var.set(f"{len(items)} active ticket(s)")

    def _open_ticket(self, ticket_id: str) -> None:
        self.app.open_ticket_details(ticket_id, on_changed=self.refresh)

    # ----------------------------------------------------------------- export
    def export_report(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export SLA report",
            defaultextension=".csv",
            initialfile=f"opsflow-sla-report-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            count = self.app.services["csv"].export_sla_report(filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.app.set_status(f"Exported SLA report ({count} rows) to {Path(filename).name}.", "success")

    def run_scan(self) -> None:
        events = self.app.run_escalation_scan()
        self.refresh()
        if not events:
            self.app.set_status("SLA scan complete · no new escalations.", "success")
