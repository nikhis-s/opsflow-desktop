"""Deterministic SLA calculations and policy management, independent of the GUI."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import DEFAULT_ACTOR
from database import Database
from models import (
    DEFAULT_POLICIES,
    PRIORITIES,
    SLAPolicy,
    Ticket,
    ensure_aware,
    to_iso,
    utc_now,
)
from services.audit_service import AuditService

ON_TRACK = "On track"
AT_RISK = "At risk"
BREACHED = "Breached"
MET = "Met"
MISSED = "Missed"


@dataclass(frozen=True)
class DeadlineEvaluation:
    deadline: datetime
    state: str
    remaining_seconds: int | None
    consumed_percent: float

    @property
    def is_breached(self) -> bool:
        return self.state == BREACHED

    @property
    def is_at_risk(self) -> bool:
        return self.state == AT_RISK

    @property
    def is_complete(self) -> bool:
        return self.state in (MET, MISSED)

    @property
    def is_failed(self) -> bool:
        return self.state in (BREACHED, MISSED)


@dataclass(frozen=True)
class SLAEvaluation:
    ticket_id: str
    priority: str
    response: DeadlineEvaluation
    resolution: DeadlineEvaluation
    overall_state: str
    checked_at: datetime

    @property
    def is_overdue(self) -> bool:
        return self.response.is_breached or self.resolution.is_breached

    @property
    def is_at_risk(self) -> bool:
        return self.overall_state == AT_RISK

    @property
    def is_compliant(self) -> bool:
        return self.overall_state in (MET, ON_TRACK)


def calculate_deadlines(
    created_at: datetime,
    response_minutes: int,
    resolution_minutes: int,
) -> tuple[datetime, datetime]:
    if response_minutes <= 0 or resolution_minutes <= 0:
        raise ValueError("SLA target minutes must be positive.")
    created = ensure_aware(created_at)
    return (
        created + timedelta(minutes=int(response_minutes)),
        created + timedelta(minutes=int(resolution_minutes)),
    )


def _evaluate_deadline(
    created_at: datetime,
    deadline: datetime,
    now: datetime,
    at_risk_percent: int,
    completed_at: datetime | None,
) -> DeadlineEvaluation:
    created = ensure_aware(created_at)
    deadline = ensure_aware(deadline)
    now = ensure_aware(now)
    total = max(1.0, (deadline - created).total_seconds())

    if completed_at is not None:
        completed = ensure_aware(completed_at)
        remaining = int((deadline - completed).total_seconds())
        state = MET if completed <= deadline else MISSED
        consumed = ((completed - created).total_seconds() / total) * 100.0
        return DeadlineEvaluation(
            deadline=deadline,
            state=state,
            remaining_seconds=remaining,
            consumed_percent=max(0.0, consumed),
        )

    remaining = int((deadline - now).total_seconds())
    consumed = ((now - created).total_seconds() / total) * 100.0
    if now > deadline:
        state = BREACHED
    else:
        warn_at = created + timedelta(
            seconds=total * (max(1, min(99, at_risk_percent)) / 100.0)
        )
        state = AT_RISK if now >= warn_at else ON_TRACK
    return DeadlineEvaluation(
        deadline=deadline,
        state=state,
        remaining_seconds=remaining,
        consumed_percent=max(0.0, consumed),
    )


class SLAEngine:
    def __init__(self, db: Database, audit: AuditService | None = None):
        self.db = db
        self.audit = audit

    def get_policies(self) -> dict[str, SLAPolicy]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM sla_policies ORDER BY "
                "CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 "
                "WHEN 'Medium' THEN 2 ELSE 3 END"
            ).fetchall()
        return {row["priority"]: SLAPolicy.from_row(row) for row in rows}

    def get_policy(self, priority: str) -> SLAPolicy:
        policies = self.get_policies()
        if priority not in policies:
            raise ValueError(f"No SLA policy configured for priority '{priority}'.")
        return policies[priority]

    def deadlines_for(
        self,
        priority: str,
        created_at: datetime,
        policies: Mapping[str, SLAPolicy] | None = None,
    ) -> tuple[datetime, datetime]:
        policy = (policies or self.get_policies()).get(priority)
        if policy is None:
            raise ValueError(f"No SLA policy configured for priority '{priority}'.")
        return calculate_deadlines(
            created_at, policy.response_minutes, policy.resolution_minutes
        )

    def evaluate(
        self,
        ticket: Ticket,
        now: datetime | None = None,
        policies: Mapping[str, SLAPolicy] | None = None,
    ) -> SLAEvaluation:
        now = ensure_aware(now or utc_now())
        policy = (policies or self.get_policies()).get(ticket.priority)
        if policy is None:
            raise ValueError(f"No SLA policy configured for priority '{ticket.priority}'.")
        response = _evaluate_deadline(
            ticket.created_at, ticket.response_deadline, now,
            policy.at_risk_percent, ticket.first_response_at,
        )
        resolution = _evaluate_deadline(
            ticket.created_at, ticket.resolution_deadline, now,
            policy.at_risk_percent, ticket.resolved_at,
        )
        if resolution.state == MISSED or response.state == MISSED:
            overall = MISSED
        elif resolution.state == BREACHED or response.state == BREACHED:
            overall = BREACHED
        elif resolution.state == AT_RISK or response.state == AT_RISK:
            overall = AT_RISK
        elif resolution.state == MET and response.state in (MET, ON_TRACK):
            overall = MET
        else:
            overall = ON_TRACK
        return SLAEvaluation(
            ticket_id=ticket.id,
            priority=ticket.priority,
            response=response,
            resolution=resolution,
            overall_state=overall,
            checked_at=now,
        )

    def evaluate_many(
        self,
        tickets: Iterable[Ticket],
        now: datetime | None = None,
        policies: Mapping[str, SLAPolicy] | None = None,
    ) -> dict[str, SLAEvaluation]:
        checked = ensure_aware(now or utc_now())
        policy_map = policies if policies is not None else self.get_policies()
        return {
            ticket.id: self.evaluate(ticket, checked, policy_map)
            for ticket in tickets
        }

    def is_overdue(self, ticket: Ticket, now: datetime | None = None,
                   policies: Mapping[str, SLAPolicy] | None = None) -> bool:
        if not ticket.active:
            return False
        return self.evaluate(ticket, now, policies).is_overdue

    def is_at_risk(self, ticket: Ticket, now: datetime | None = None,
                   policies: Mapping[str, SLAPolicy] | None = None) -> bool:
        if not ticket.active:
            return False
        evaluation = self.evaluate(ticket, now, policies)
        return evaluation.is_at_risk

    def compliance(self, tickets: Iterable[Ticket]) -> tuple[float | None, float | None, int, int]:
        """Return resolution %, response %, completed count, responded count."""
        items = list(tickets)
        completed = [t for t in items if t.resolved_at is not None]
        responded = [t for t in items if t.first_response_at is not None]
        resolution_met = sum(
            1 for t in completed if t.resolved_at and t.resolved_at <= t.resolution_deadline
        )
        response_met = sum(
            1 for t in responded if t.first_response_at and t.first_response_at <= t.response_deadline
        )
        res_pct = (resolution_met / len(completed) * 100.0) if completed else None
        resp_pct = (response_met / len(responded) * 100.0) if responded else None
        return res_pct, resp_pct, len(completed), len(responded)

    def update_policies(
        self,
        updates: Mapping[str, tuple[int, int, int] | Mapping[str, int]],
        actor: str | None = None,
    ) -> None:
        normalized: dict[str, tuple[int, int, int]] = {}
        for priority, values in updates.items():
            if priority not in PRIORITIES:
                raise ValueError(f"Unknown priority '{priority}'.")
            if isinstance(values, Mapping):
                response = int(values["response_minutes"])
                resolution = int(values["resolution_minutes"])
                warn = int(values.get("at_risk_percent", 80))
            else:
                response, resolution, warn = (int(v) for v in values)
            if response <= 0 or resolution <= 0:
                raise ValueError("Response and resolution targets must be positive minutes.")
            if resolution < response:
                raise ValueError(
                    f"{priority}: resolution target must be greater than or equal to response target."
                )
            if not 1 <= warn <= 99:
                raise ValueError("At-risk threshold must be between 1 and 99 percent.")
            normalized[priority] = (response, resolution, warn)

        if not normalized:
            return

        now = utc_now()
        with self.db.transaction() as conn:
            old_rows = {
                row["priority"]: row for row in conn.execute(
                    "SELECT * FROM sla_policies"
                )
            }
            for priority, (response, resolution, warn) in normalized.items():
                conn.execute(
                    """INSERT INTO sla_policies
                       (priority, response_minutes, resolution_minutes,
                        at_risk_percent, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(priority) DO UPDATE SET
                         response_minutes = excluded.response_minutes,
                         resolution_minutes = excluded.resolution_minutes,
                         at_risk_percent = excluded.at_risk_percent,
                         updated_at = excluded.updated_at""",
                    (priority, response, resolution, warn, to_iso(now)),
                )
                old = old_rows.get(priority)
                old_text = (
                    f"{old['response_minutes']}m/{old['resolution_minutes']}m @{old['at_risk_percent']}%"
                    if old else "none"
                )
                if self.audit:
                    self.audit.record(
                        conn, None, "SLA_POLICY_UPDATED",
                        f"{priority}: {old_text} → {response}m/{resolution}m @{warn}%",
                        actor or DEFAULT_ACTOR, now,
                    )

    def reset_defaults(self, actor: str | None = None) -> None:
        self.update_policies(DEFAULT_POLICIES, actor)

    def report(self, tickets: Iterable[Ticket], now: datetime | None = None):
        items = list(tickets)
        policies = self.get_policies()
        evaluations = self.evaluate_many(items, now, policies)
        from models import SLAReportRow
        rows: list[SLAReportRow] = []
        for ticket in items:
            evaluation = evaluations[ticket.id]
            rows.append(SLAReportRow(
                ticket=ticket,
                response_state=evaluation.response.state,
                resolution_state=evaluation.resolution.state,
                overall_state=evaluation.overall_state,
                response_remaining=evaluation.response.remaining_seconds,
                resolution_remaining=evaluation.resolution.remaining_seconds,
            ))
        return rows
