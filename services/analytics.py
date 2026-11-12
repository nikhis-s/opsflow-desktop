"""Database-derived operational metrics and dashboard data."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from database import Database
from models import (
    PRIORITIES,
    STATUSES,
    AuditEvent,
    DashboardMetrics,
    SLAReportRow,
    Status,
    Ticket,
    parse_timestamp,
    utc_now,
)
from services.audit_service import AuditService
from services.sla_engine import AT_RISK, BREACHED, SLAEngine


class AnalyticsService:
    def __init__(self, db: Database, sla: SLAEngine, audit: AuditService):
        self.db = db
        self.sla = sla
        self.audit = audit

    def all_tickets(self) -> list[Ticket]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
        return [Ticket.from_row(row) for row in rows]

    def metrics(self, now: datetime | None = None) -> DashboardMetrics:
        checked = now or utc_now()
        tickets = self.all_tickets()
        policies = self.sla.get_policies()
        evaluations = self.sla.evaluate_many(tickets, checked, policies)

        status_counts = dict.fromkeys(STATUSES, 0)
        priority_counts = dict.fromkeys(PRIORITIES, 0)
        for ticket in tickets:
            status_counts[ticket.status] = status_counts.get(ticket.status, 0) + 1
            priority_counts[ticket.priority] = priority_counts.get(ticket.priority, 0) + 1

        overdue = sum(
            1 for ticket in tickets
            if ticket.active and evaluations[ticket.id].is_overdue
        )
        at_risk = sum(
            1 for ticket in tickets
            if ticket.active and evaluations[ticket.id].is_at_risk
        )
        compliance, response_compliance, _, _ = self.sla.compliance(tickets)
        resolution_seconds = [
            ticket.resolution_seconds for ticket in tickets
            if ticket.resolution_seconds is not None
        ]
        average = (sum(resolution_seconds) / len(resolution_seconds)
                   if resolution_seconds else None)

        today = checked.astimezone().date()
        days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
        created_counts = Counter(
            parse_timestamp(ticket.created_at).astimezone().date() for ticket in tickets
        )
        resolved_counts = Counter(
            parse_timestamp(ticket.resolved_at).astimezone().date()
            for ticket in tickets if ticket.resolved_at is not None
        )
        trend = [
            {
                "date": day,
                "label": day.strftime("%a"),
                "created": created_counts.get(day, 0),
                "resolved": resolved_counts.get(day, 0),
            }
            for day in days
        ]

        return DashboardMetrics(
            total=len(tickets),
            open_count=status_counts.get(Status.OPEN.value, 0),
            in_progress=status_counts.get(Status.IN_PROGRESS.value, 0),
            pending=status_counts.get(Status.PENDING.value, 0),
            resolved=status_counts.get(Status.RESOLVED.value, 0),
            closed=status_counts.get(Status.CLOSED.value, 0),
            overdue=overdue,
            at_risk=at_risk,
            compliance=compliance,
            response_compliance=response_compliance,
            avg_resolution_seconds=average,
            status_counts=status_counts,
            priority_counts=priority_counts,
            trend=trend,
        )

    def recent_activity(self, limit: int = 8) -> list[AuditEvent]:
        return self.audit.recent(limit)

    def watchlist(
        self, now: datetime | None = None, limit: int = 8
    ) -> list[tuple[Ticket, Any]]:
        checked = now or utc_now()
        tickets = [ticket for ticket in self.all_tickets() if ticket.active]
        policies = self.sla.get_policies()
        evaluations = self.sla.evaluate_many(tickets, checked, policies)
        items = [
            (ticket, evaluations[ticket.id]) for ticket in tickets
            if evaluations[ticket.id].overall_state in (BREACHED, AT_RISK)
        ]
        rank = {BREACHED: 0, AT_RISK: 1}
        items.sort(key=lambda pair: (
            rank.get(pair[1].overall_state, 2),
            pair[1].resolution.deadline,
        ))
        return items[:limit]

    def sla_monitor(self, now: datetime | None = None) -> list[tuple[Ticket, Any]]:
        checked = now or utc_now()
        tickets = [ticket for ticket in self.all_tickets() if ticket.active]
        policies = self.sla.get_policies()
        evaluations = self.sla.evaluate_many(tickets, checked, policies)
        rank = {BREACHED: 0, AT_RISK: 1}
        items = [(ticket, evaluations[ticket.id]) for ticket in tickets]
        items.sort(key=lambda pair: (
            rank.get(pair[1].overall_state, 2),
            pair[1].resolution.deadline,
            pair[1].response.deadline,
        ))
        return items

    def sla_report(self, now: datetime | None = None) -> list[SLAReportRow]:
        return self.sla.report(self.all_tickets(), now)

    def escalation_counts(self) -> dict[str, int]:
        with self.db.read() as conn:
            counts = {"WARNING": 0, "CRITICAL": 0, "INFO": 0}
            for row in conn.execute(
                "SELECT level, COUNT(*) AS n FROM escalation_events GROUP BY level"
            ):
                counts[row["level"]] = int(row["n"])
            counts["TOTAL"] = int(conn.execute(
                "SELECT COUNT(*) FROM escalation_events"
            ).fetchone()[0])
        return counts
