"""Deterministic, internal-only escalation detection and history."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from database import Database
from models import (
    ACTIVE_STATUSES,
    EscalationEvent,
    Priority,
    Ticket,
    format_local,
    human_duration,
    to_iso,
    utc_now,
)
from services.audit_service import AuditService
from services.sla_engine import (
    AT_RISK,
    BREACHED,
    SLAEngine,
    SLAEvaluation,
)


class EscalationEngine:
    """Detects SLA risk/breaches and records them internally.

    OpsFlow never sends external notifications or claims that a person was
    contacted. Every escalation is an auditable, in-app event.
    """

    def __init__(self, db: Database, sla: SLAEngine, audit: AuditService):
        self.db = db
        self.sla = sla
        self.audit = audit

    def _active_tickets(self) -> list[Ticket]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT * FROM tickets WHERE status IN ({placeholders}) "
                "ORDER BY resolution_deadline ASC",
                ACTIVE_STATUSES,
            ).fetchall()
        return [Ticket.from_row(row) for row in rows]

    def run(self, now: datetime | None = None, actor: str | None = None) -> list[EscalationEvent]:
        checked = now or utc_now()
        tickets = self._active_tickets()
        policies = self.sla.get_policies()
        evaluations = self.sla.evaluate_many(tickets, checked, policies)
        created: list[EscalationEvent] = []

        with self.db.transaction() as conn:
            for ticket in tickets:
                evaluation = evaluations[ticket.id]
                created.extend(self._ticket_events(conn, ticket, evaluation, checked, actor))
        return created

    def _ticket_events(
        self,
        conn: sqlite3.Connection,
        ticket: Ticket,
        evaluation: SLAEvaluation,
        now: datetime,
        actor: str | None,
    ) -> list[EscalationEvent]:
        events: list[EscalationEvent] = []

        if ticket.first_response_at is None:
            if evaluation.response.state == BREACHED:
                overdue = abs(evaluation.response.remaining_seconds or 0)
                events.extend(self._insert(
                    conn, ticket, "response_breach", "CRITICAL",
                    f"Response SLA breached for {ticket.priority} priority ticket {ticket.id}.",
                    f"Response was due {format_local(ticket.response_deadline)} and is "
                    f"{human_duration(overdue)} overdue. Status: {ticket.status}.",
                    f"{ticket.id}|response_breach|{to_iso(ticket.response_deadline)}",
                    now, actor,
                ))
            elif evaluation.response.state == AT_RISK:
                level = "CRITICAL" if ticket.priority == Priority.CRITICAL.value else "WARNING"
                events.extend(self._insert(
                    conn, ticket, "response_at_risk", level,
                    f"Response deadline approaching for {ticket.priority} priority ticket {ticket.id}.",
                    f"Response is due {format_local(ticket.response_deadline)} · "
                    f"{human_duration(evaluation.response.remaining_seconds)} remaining. "
                    f"Status: {ticket.status}.",
                    f"{ticket.id}|response_at_risk|{to_iso(ticket.response_deadline)}",
                    now, actor,
                ))

        if ticket.resolved_at is None:
            if evaluation.resolution.state == BREACHED:
                overdue = abs(evaluation.resolution.remaining_seconds or 0)
                events.extend(self._insert(
                    conn, ticket, "resolution_breach", "CRITICAL",
                    f"Resolution SLA breached for {ticket.priority} priority ticket {ticket.id}.",
                    f"Resolution was due {format_local(ticket.resolution_deadline)} and is "
                    f"{human_duration(overdue)} overdue. Status: {ticket.status}; "
                    f"assignee: {ticket.assignee}.",
                    f"{ticket.id}|resolution_breach|{to_iso(ticket.resolution_deadline)}",
                    now, actor,
                ))
            elif evaluation.resolution.state == AT_RISK:
                level = "CRITICAL" if ticket.priority == Priority.CRITICAL.value else "WARNING"
                events.extend(self._insert(
                    conn, ticket, "resolution_at_risk", level,
                    f"Resolution deadline approaching for {ticket.priority} priority ticket {ticket.id}.",
                    f"Resolution is due {format_local(ticket.resolution_deadline)} · "
                    f"{human_duration(evaluation.resolution.remaining_seconds)} remaining. "
                    f"Status: {ticket.status}; assignee: {ticket.assignee}.",
                    f"{ticket.id}|resolution_at_risk|{to_iso(ticket.resolution_deadline)}",
                    now, actor,
                ))

        # A critical, unassigned, unresolved ticket is an operationally distinct
        # escalation even before its deadlines are at risk.
        if (ticket.priority == Priority.CRITICAL.value
                and ticket.assignee.strip().lower() in ("", "unassigned")):
            events.extend(self._insert(
                conn, ticket, "critical_unassigned", "CRITICAL",
                f"Critical priority ticket {ticket.id} is unresolved and unassigned.",
                "Assign an owner immediately. This escalation is recorded internally; "
                "no external notification has been sent.",
                f"{ticket.id}|critical_unassigned|{to_iso(ticket.created_at)}",
                now, actor,
            ))
        return events

    def _insert(
        self,
        conn: sqlite3.Connection,
        ticket: Ticket,
        escalation_type: str,
        level: str,
        reason: str,
        details: str,
        dedupe_key: str,
        now: datetime,
        actor: str | None,
    ) -> list[EscalationEvent]:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO escalation_events
               (ticket_id, escalation_type, level, reason, details, dedupe_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ticket.id, escalation_type, level, reason, details, dedupe_key, to_iso(now)),
        )
        if cursor.rowcount == 0:
            return []
        event_id = int(cursor.lastrowid or 0)
        self.audit.record(
            conn, ticket.id, "ESCALATION_RAISED",
            f"[{level}] {reason} {details}",
            actor or "SLA Engine", now,
        )
        if escalation_type.endswith("_breach"):
            self.audit.record(
                conn, ticket.id, "SLA_BREACH",
                f"{escalation_type.replace('_', ' ').title()} · {details}",
                actor or "SLA Engine", now,
            )
        return [EscalationEvent(
            id=event_id,
            ticket_id=ticket.id,
            escalation_type=escalation_type,
            level=level,
            reason=reason,
            details=details,
            created_at=checked_aware(now),
        )]

    def critical_unresolved(
        self, now: datetime | None = None
    ) -> list[tuple[Ticket, SLAEvaluation]]:
        checked = now or utc_now()
        policies = self.sla.get_policies()
        tickets = [t for t in self._active_tickets()
                   if t.priority == Priority.CRITICAL.value]
        evaluations = self.sla.evaluate_many(tickets, checked, policies)
        result = [(ticket, evaluations[ticket.id]) for ticket in tickets]
        result.sort(key=lambda pair: pair[1].resolution.deadline)
        return result

    # ------------------------------------------------------------------ reads
    def list_events(
        self,
        search: str = "",
        level: str = "",
        ticket_id: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> list[EscalationEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(ticket_id) LIKE ? OR lower(escalation_type) LIKE ? "
                "OR lower(reason) LIKE ? OR lower(details) LIKE ?)"
            )
            params.extend([needle] * 4)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if ticket_id:
            clauses.append("ticket_id = ?")
            params.append(ticket_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([max(1, int(limit)), max(0, int(offset))])
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT * FROM escalation_events {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [EscalationEvent.from_row(row) for row in rows]

    def count(self, search: str = "", level: str = "", ticket_id: str = "") -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(ticket_id) LIKE ? OR lower(escalation_type) LIKE ? "
                "OR lower(reason) LIKE ? OR lower(details) LIKE ?)"
            )
            params.extend([needle] * 4)
        if level:
            clauses.append("level = ?")
            params.append(level)
        if ticket_id:
            clauses.append("ticket_id = ?")
            params.append(ticket_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.read() as conn:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM escalation_events {where}", params
            ).fetchone()[0])

    def levels(self) -> list[str]:
        with self.db.read() as conn:
            return [row[0] for row in conn.execute(
                "SELECT DISTINCT level FROM escalation_events ORDER BY level"
            )]

    def for_ticket(self, ticket_id: str) -> list[EscalationEvent]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM escalation_events WHERE ticket_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (ticket_id,),
            ).fetchall()
        return [EscalationEvent.from_row(row) for row in rows]


def checked_aware(value: datetime) -> datetime:
    """Small local helper to keep escalation event models timezone-aware."""
    from models import ensure_aware
    return ensure_aware(value)
