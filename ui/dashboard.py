"""Operations dashboard with live KPIs, native charts and recent activity."""
from __future__ import annotations

import tkinter as tk
from typing import Any

from models import format_local, format_local_short, human_duration, truncate, utc_now
from ui.components import (
    Badge, Card, DataTable, KpiCard, Page, ScrollableFrame, SectionHeader,
    flat_button, ticket_row_tags,
)
from ui.theme import COLORS, FONTS, PRIORITY_COLORS, SLA_COLORS, STATUS_COLORS, mix, px


class DonutChart(tk.Canvas):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=COLORS["card"], highlightthickness=0, height=px(210))
        self.data: dict[str, int] = {}
        self.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, data: dict[str, int]) -> None:
        self.data = data
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < px(140) or height < px(90):
            return
        total = sum(self.data.values())
        ring = max(px(12), px(18))
        radius = max(px(34), min(height * 0.32, width * 0.23))
        cx = min(radius + ring + px(22), width * 0.38)
        cy = height / 2
        if total == 0:
            self.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                             outline=COLORS["border"], width=ring)
        else:
            start = 90.0
            for status, count in self.data.items():
                if count <= 0:
                    continue
                extent = -(count / total) * 360
                self.create_arc(cx - radius, cy - radius, cx + radius, cy + radius,
                                start=start, extent=extent, style="arc",
                                outline=STATUS_COLORS.get(status, COLORS["muted"]),
                                width=ring)
                start += extent
        self.create_text(cx, cy - px(9), text=str(total), fill=COLORS["text"],
                         font=FONTS["kpi"])
        self.create_text(cx, cy + px(20), text="TICKETS", fill=COLORS["subtle"],
                         font=FONTS["micro"])

        spacing = px(27)
        legend_x = max(cx + radius + ring + px(28), width * 0.56)
        legend_x = min(legend_x, width - px(120))
        legend_y = max(px(16), (height - len(self.data) * spacing) // 2)
        for index, (status, count) in enumerate(self.data.items()):
            y = legend_y + index * spacing
            color = STATUS_COLORS.get(status, COLORS["muted"])
            self.create_oval(legend_x, y + px(3), legend_x + px(8), y + px(11),
                             fill=color, outline="")
            self.create_text(legend_x + px(16), y, text=status, anchor="nw",
                             fill=COLORS["muted"], font=FONTS["small"])
            self.create_text(width - px(14), y, text=str(count), anchor="ne",
                             fill=COLORS["text"], font=FONTS["small"])


class PriorityBars(tk.Canvas):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=COLORS["card"], highlightthickness=0, height=px(210))
        self.data: dict[str, int] = {}
        self.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, data: dict[str, int]) -> None:
        self.data = data
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < px(150) or height < px(90):
            return
        total = sum(self.data.values())
        if total == 0:
            self.create_text(width / 2, height / 2, text="No ticket data yet",
                             fill=COLORS["subtle"], font=FONTS["small"])
            return
        maximum = max(self.data.values()) or 1
        left = px(82)
        right = width - px(34)
        row_height = min(px(40), max(px(30), (height - px(24)) // max(1, len(self.data))))
        start_y = (height - row_height * len(self.data)) // 2
        for index, (priority, count) in enumerate(self.data.items()):
            y = start_y + index * row_height
            color = PRIORITY_COLORS.get(priority, COLORS["muted"])
            self.create_text(left - px(12), y + row_height / 2 - px(6), text=priority,
                             anchor="e", fill=COLORS["muted"], font=FONTS["small"])
            self.create_rectangle(left, y + px(9), right, y + px(23),
                                  fill=COLORS["card_soft"], outline="")
            bar_width = max(2, (count / maximum) * (right - left))
            if count:
                self.create_rectangle(left, y + px(9), left + bar_width, y + px(23),
                                      fill=color, outline="")
            self.create_text(right + px(8), y + row_height / 2 - px(6), text=str(count),
                             anchor="w", fill=COLORS["text_soft"], font=FONTS["small"])


class TrendChart(tk.Canvas):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=COLORS["card"], highlightthickness=0, height=px(210))
        self.points: list[dict[str, Any]] = []
        self.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, points: list[dict[str, Any]]) -> None:
        self.points = points
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < px(160) or height < px(100) or not self.points:
            return
        left, right = px(38), width - px(16)
        top, bottom = px(38), height - px(28)
        maximum = max(
            [1] + [int(point["created"]) for point in self.points]
            + [int(point["resolved"]) for point in self.points]
        )
        for step in range(5):
            y = top + (bottom - top) * step / 4
            self.create_line(left, y, right, y, fill=COLORS["grid"])
            self.create_text(left - px(7), y, text=str(round(maximum * (4 - step) / 4)),
                             anchor="e", fill=COLORS["subtle"], font=FONTS["micro"])
        count = len(self.points)
        x_positions = [
            left + (right - left) * (index / max(1, count - 1))
            for index in range(count)
        ]
        series = (
            ("created", COLORS["accent"], "Created"),
            ("resolved", COLORS["green"], "Resolved"),
        )
        for series_index, (key, color, label) in enumerate(series):
            coords: list[float] = []
            for index, point in enumerate(self.points):
                x = x_positions[index]
                value = int(point.get(key, 0))
                y = bottom - (value / maximum) * (bottom - top)
                coords.extend([x, y])
            if len(coords) >= 4:
                self.create_line(*coords, fill=color, width=max(2, px(2)), smooth=True)
            for index, point in enumerate(self.points):
                x = x_positions[index]
                value = int(point.get(key, 0))
                y = bottom - (value / maximum) * (bottom - top)
                dot = max(2, px(3))
                self.create_oval(x - dot, y - dot, x + dot, y + dot, fill=color, outline="")
            legend_x = right - px(160) + series_index * px(78)
            self.create_line(legend_x, px(14), legend_x + px(12), px(14),
                             fill=color, width=max(2, px(2)))
            self.create_text(legend_x + px(17), px(14), text=label, anchor="w",
                             fill=COLORS["subtle"], font=FONTS["micro"])
        for index, point in enumerate(self.points):
            self.create_text(x_positions[index], height - px(12), text=point["label"],
                             fill=COLORS["subtle"], font=FONTS["micro"])


class DashboardPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=px(26), pady=px(22))

        header = SectionHeader(
            outer, "Command center",
            "Live workload, SLA health and operational activity across the queue.",
        )
        header.pack(fill="x", pady=(0, px(18)))
        self.updated_var = tk.StringVar(value="Not refreshed")
        tk.Label(header.actions, textvariable=self.updated_var, bg=COLORS["bg"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left", padx=(0, px(12)))
        flat_button(header.actions, "Refresh dashboard", self.refresh,
                    "secondary").pack(side="left")

        kpis = tk.Frame(outer, bg=COLORS["bg"])
        kpis.pack(fill="x", pady=(0, px(16)))
        for column in range(4):
            kpis.grid_columnconfigure(column, weight=1, uniform="kpi")
        self.kpi_total = KpiCard(kpis, "Total tickets", COLORS["blue"], "▦", "All tickets")
        self.kpi_open = KpiCard(kpis, "Open", COLORS["accent"], "◌", "Awaiting response")
        self.kpi_progress = KpiCard(kpis, "In progress", COLORS["green"], "◐", "Actively worked")
        self.kpi_resolved = KpiCard(kpis, "Resolved", COLORS["green"], "✓", "Completed")
        self.kpi_overdue = KpiCard(kpis, "Overdue", COLORS["red"], "!", "Past a deadline")
        self.kpi_risk = KpiCard(kpis, "Approaching SLA", COLORS["amber"], "▲", "At-risk, not breached")
        self.kpi_compliance = KpiCard(kpis, "SLA compliance", COLORS["accent"], "%", "Resolution target")
        self.kpi_avg = KpiCard(kpis, "Avg resolution", COLORS["purple"], "◷", "Completed tickets")
        self._kpis = [
            self.kpi_total, self.kpi_open, self.kpi_progress, self.kpi_resolved,
            self.kpi_overdue, self.kpi_risk, self.kpi_compliance, self.kpi_avg,
        ]
        for index, card in enumerate(self._kpis):
            card.grid(row=index // 4, column=index % 4, sticky="nsew",
                      padx=(0 if index % 4 == 0 else px(6), 0),
                      pady=(0, px(7)) if index < 4 else (px(7), 0))

        charts = tk.Frame(outer, bg=COLORS["bg"])
        charts.pack(fill="x", pady=(0, px(16)))
        charts.grid_columnconfigure(0, weight=1, uniform="charts")
        charts.grid_columnconfigure(1, weight=1, uniform="charts")
        charts.grid_columnconfigure(2, weight=1, uniform="charts")
        status_card = Card(charts, padding=(16, 13))
        status_card.grid(row=0, column=0, sticky="nsew", padx=(0, px(6)))
        priority_card = Card(charts, padding=(16, 13))
        priority_card.grid(row=0, column=1, sticky="nsew", padx=px(6))
        trend_card = Card(charts, padding=(16, 13))
        trend_card.grid(row=0, column=2, sticky="nsew", padx=(px(6), 0))
        self._chart_header(status_card, "Ticket status", "Current queue mix")
        self._chart_header(priority_card, "Priority mix", "Open and completed")
        self._chart_header(trend_card, "7-day flow", "Created vs resolved")
        self.donut = DonutChart(status_card.body)
        self.donut.pack(fill="both", expand=True, pady=(px(6), 0))
        self.priority_bars = PriorityBars(priority_card.body)
        self.priority_bars.pack(fill="both", expand=True, pady=(px(6), 0))
        self.trend = TrendChart(trend_card.body)
        self.trend.pack(fill="both", expand=True, pady=(px(6), 0))

        bottom = tk.Frame(outer, bg=COLORS["bg"])
        bottom.pack(fill="both", expand=True)
        bottom.grid_columnconfigure(0, weight=3, uniform="bottom")
        bottom.grid_columnconfigure(1, weight=2, uniform="bottom")
        watch_card = Card(bottom, padding=(16, 14))
        watch_card.grid(row=0, column=0, sticky="nsew", padx=(0, px(8)))
        activity_card = Card(bottom, padding=(16, 14))
        activity_card.grid(row=0, column=1, sticky="nsew", padx=(px(8), 0))

        watch_header = self._chart_header(
            watch_card, "SLA watchlist", "Active tickets closest to a breach",
        )
        flat_button(watch_header, "Open SLA center", lambda: self.app.show_page("sla"),
                    "link").pack(side="right")
        self.watch_table = DataTable(
            watch_card.body,
            [
                {"key": "id", "label": "TICKET", "width": 88},
                {"key": "title", "label": "TITLE", "width": 250, "stretch": True},
                {"key": "priority", "label": "PRIORITY", "width": 88},
                {"key": "status", "label": "STATUS", "width": 95},
                {"key": "due", "label": "RESOLUTION DUE", "width": 145},
                {"key": "sla", "label": "SLA", "width": 86},
            ],
            height=6,
            on_double_click=self._open_ticket,
            empty_title="No SLA risk right now",
            empty_hint="At-risk and breached tickets will appear here.",
        )
        self.watch_table.pack(fill="both", expand=True, pady=(px(10), 0))

        activity_header = self._chart_header(
            activity_card, "Recent activity", "Latest audited ticket updates",
        )
        flat_button(activity_header, "Audit trail", lambda: self.app.show_page("audit"),
                    "link").pack(side="right")
        self.activity_container = tk.Frame(activity_card.body, bg=COLORS["card"])
        self.activity_container.pack(fill="both", expand=True, pady=(px(8), 0))

    @staticmethod
    def _chart_header(card: Card, title: str, subtitle: str) -> tk.Frame:
        row = tk.Frame(card.body, bg=COLORS["card"])
        row.pack(fill="x")
        text = tk.Frame(row, bg=COLORS["card"])
        text.pack(side="left")
        tk.Label(text, text=title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["semibold"], anchor="w").pack(fill="x")
        tk.Label(text, text=subtitle, bg=COLORS["card"], fg=COLORS["subtle"],
                 font=FONTS["tiny"], anchor="w").pack(fill="x", pady=(px(1), 0))
        return row

    def _open_ticket(self, ticket_id: str) -> None:
        self.app.open_ticket_details(ticket_id, on_changed=self.refresh)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        analytics = self.app.services["analytics"]
        metrics = analytics.metrics()
        self.kpi_total.set(
            metrics.total,
            f"{metrics.active} active · {metrics.closed} closed",
        )
        self.kpi_open.set(
            metrics.open_count,
            "Awaiting first response" if metrics.open_count else "Queue clear",
        )
        self.kpi_progress.set(
            metrics.in_progress,
            f"{metrics.pending} pending follow-up" if metrics.pending else "No pending follow-up",
        )
        self.kpi_resolved.set(
            metrics.resolved,
            "Status set to Resolved" if metrics.resolved else "No resolutions yet",
        )
        self.kpi_overdue.set(
            metrics.overdue,
            "Deadline breached" if metrics.overdue else "No active breaches",
        )
        self.kpi_risk.set(
            metrics.at_risk,
            "Inside warning window" if metrics.at_risk else "No approaching deadlines",
        )
        if metrics.compliance is None:
            self.kpi_compliance.set("—", "No completed tickets")
        else:
            self.kpi_compliance.set(
                f"{metrics.compliance:.0f}%",
                f"{metrics.resolved + metrics.closed} completed ticket(s)",
            )
        self.kpi_avg.set(
            human_duration(metrics.avg_resolution_seconds) if metrics.avg_resolution_seconds else "—",
            "From creation to resolution",
        )
        self.donut.set_data(metrics.status_counts)
        self.priority_bars.set_data(metrics.priority_counts)
        self.trend.set_data(metrics.trend)

        watchlist = analytics.watchlist(limit=12)
        rows = []
        payloads = []
        tags = []
        for index, (ticket, evaluation) in enumerate(watchlist):
            rows.append((
                ticket.id,
                truncate(ticket.title, 44),
                ticket.priority,
                ticket.status,
                format_local(evaluation.resolution.deadline, "%d %b · %H:%M"),
                evaluation.overall_state,
            ))
            payloads.append(ticket.id)
            tags.append(ticket_row_tags(index, ticket.priority, evaluation.overall_state))
        self.watch_table.set_rows(rows, payloads, tags)

        self._render_activity(analytics.recent_activity(7))
        self.updated_var.set(f"Updated {format_local(utc_now(), '%H:%M:%S')}")

    def _render_activity(self, events: list[Any]) -> None:
        for child in self.activity_container.winfo_children():
            child.destroy()
        if not events:
            tk.Label(self.activity_container, text="No activity recorded yet.",
                     bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["small"]).pack(anchor="w", pady=px(12))
            return
        action_labels = {
            "TICKET_CREATED": ("Created", COLORS["accent"]),
            "TICKET_DELETED": ("Deleted", COLORS["red"]),
            "COMMENT_ADDED": ("Note", COLORS["purple"]),
            "STATUS_CHANGED": ("Status", COLORS["blue"]),
            "PRIORITY_CHANGED": ("Priority", COLORS["amber"]),
            "ASSIGNED": ("Assigned", COLORS["green"]),
            "REASSIGNED": ("Reassigned", COLORS["green"]),
            "SLA_BREACH": ("SLA breach", COLORS["red"]),
            "ESCALATION_RAISED": ("Escalation", COLORS["red"]),
            "SLA_RECALCULATED": ("SLA recalculated", COLORS["amber"]),
            "SLA_POLICY_UPDATED": ("SLA policy", COLORS["green"]),
            "CSV_IMPORT": ("CSV import", COLORS["accent"]),
            "SLA_POLICY": ("SLA policy", COLORS["green"]),
        }
        for event in events:
            row = tk.Frame(self.activity_container, bg=COLORS["card"])
            row.pack(fill="x", pady=(0, px(9)))
            label, color = action_labels.get(
                event.action, (event.action.replace("_", " ").title(), COLORS["muted"]))
            tk.Frame(row, bg=color, width=px(3)).pack(side="left", fill="y", padx=(0, px(9)))
            body = tk.Frame(row, bg=COLORS["card"])
            body.pack(side="left", fill="x", expand=True)
            top = tk.Frame(body, bg=COLORS["card"])
            top.pack(fill="x")
            tk.Label(top, text=label, bg=COLORS["card"], fg=color,
                     font=FONTS["tiny"]).pack(side="left")
            if event.ticket_id:
                tk.Label(top, text=f"  {event.ticket_id}", bg=COLORS["card"],
                         fg=COLORS["text_soft"], font=FONTS["tiny"]).pack(side="left")
            tk.Label(top, text=format_local_short(event.created_at), bg=COLORS["card"],
                     fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="right")
            tk.Label(body, text=truncate(event.details, 100), bg=COLORS["card"],
                     fg=COLORS["muted"], font=FONTS["small"], anchor="w",
                     justify="left", wraplength=px(360)).pack(fill="x")
