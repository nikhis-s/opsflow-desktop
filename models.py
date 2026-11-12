"""Domain models and shared time/formatting helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Status(str, Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    PENDING = "Pending"
    RESOLVED = "Resolved"
    CLOSED = "Closed"


PRIORITIES: tuple[str, ...] = tuple(p.value for p in Priority)
STATUSES: tuple[str, ...] = tuple(s.value for s in Status)
ACTIVE_STATUSES: tuple[str, ...] = (
    Status.OPEN.value,
    Status.IN_PROGRESS.value,
    Status.PENDING.value,
)
TERMINAL_STATUSES: tuple[str, ...] = (Status.RESOLVED.value, Status.CLOSED.value)
PRIORITY_RANK = {Priority.CRITICAL.value: 0, Priority.HIGH.value: 1,
                 Priority.MEDIUM.value: 2, Priority.LOW.value: 3}
STATUS_RANK = {s.value: i for i, s in enumerate(Status)}

DEFAULT_POLICIES: dict[str, tuple[int, int, int]] = {
    # priority: (response minutes, resolution minutes, warning at % consumed)
    Priority.CRITICAL.value: (15, 120, 80),
    Priority.HIGH.value: (30, 240, 80),
    Priority.MEDIUM.value: (120, 480, 80),
    Priority.LOW.value: (240, 1440, 80),
}

CATEGORIES = (
    "Access & Identity",
    "Hardware",
    "Network",
    "Software",
    "Security",
    "Billing",
    "General",
)

TICKET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return to_iso(parse_timestamp(value))
    return ensure_aware(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: str | datetime) -> datetime:
    """Parse an ISO timestamp. Naive values are treated as UTC."""
    if isinstance(value, datetime):
        return ensure_aware(value)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_user_timestamp(value: str | date | datetime) -> datetime:
    """Parse a friendly import/UI timestamp, interpreting naive values as local time."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.astimezone().astimezone(timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        raise ValueError("empty timestamp")
    candidates = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    )
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt in candidates:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.astimezone().astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError("expected ISO/date timestamp, e.g. 2026-05-01 14:30")


def format_local(value: str | datetime | None, fmt: str = "%d %b %Y · %H:%M") -> str:
    if value is None:
        return "—"
    try:
        return parse_timestamp(value).astimezone().strftime(fmt)
    except (ValueError, TypeError):
        return str(value)


def format_local_short(value: str | datetime | None) -> str:
    return format_local(value, "%d %b %H:%M")


def human_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    total = int(abs(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{total}s"


def duration_minutes(minutes: int) -> str:
    if minutes >= 1440 and minutes % 1440 == 0:
        return f"{minutes // 1440} day" + ("s" if minutes // 1440 != 1 else "")
    if minutes >= 60:
        hours, mins = divmod(minutes, 60)
        return f"{hours}h" + (f" {mins}m" if mins else "")
    return f"{minutes}m"


def truncate(text: str, length: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


def is_active_status(status: str) -> bool:
    return status in ACTIVE_STATUSES


@dataclass(frozen=True)
class Ticket:
    id: str
    title: str
    description: str
    requester: str
    assignee: str
    category: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    response_deadline: datetime
    resolution_deadline: datetime
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Ticket":
        return cls(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            requester=row["requester"],
            assignee=row["assignee"],
            category=row["category"],
            priority=row["priority"],
            status=row["status"],
            created_at=parse_timestamp(row["created_at"]),
            updated_at=parse_timestamp(row["updated_at"]),
            response_deadline=parse_timestamp(row["response_deadline"]),
            resolution_deadline=parse_timestamp(row["resolution_deadline"]),
            first_response_at=(parse_timestamp(row["first_response_at"])
                               if row["first_response_at"] else None),
            resolved_at=(parse_timestamp(row["resolved_at"])
                         if row["resolved_at"] else None),
            closed_at=(parse_timestamp(row["closed_at"])
                       if row["closed_at"] else None),
        )

    @property
    def active(self) -> bool:
        return is_active_status(self.status)

    @property
    def resolution_seconds(self) -> int | None:
        if not self.resolved_at:
            return None
        return max(0, int((self.resolved_at - self.created_at).total_seconds()))


@dataclass(frozen=True)
class SLAPolicy:
    priority: str
    response_minutes: int
    resolution_minutes: int
    at_risk_percent: int
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SLAPolicy":
        return cls(
            priority=row["priority"],
            response_minutes=int(row["response_minutes"]),
            resolution_minutes=int(row["resolution_minutes"]),
            at_risk_percent=int(row["at_risk_percent"]),
            updated_at=parse_timestamp(row["updated_at"]),
        )


@dataclass(frozen=True)
class TicketComment:
    id: int
    ticket_id: str
    author: str
    body: str
    is_internal: bool
    created_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "TicketComment":
        return cls(
            id=int(row["id"]),
            ticket_id=row["ticket_id"],
            author=row["author"],
            body=row["body"],
            is_internal=bool(row["is_internal"]),
            created_at=parse_timestamp(row["created_at"]),
        )


@dataclass(frozen=True)
class AuditEvent:
    id: int
    ticket_id: str | None
    action: str
    details: str
    actor: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AuditEvent":
        return cls(
            id=int(row["id"]),
            ticket_id=row["ticket_id"],
            action=row["action"],
            details=row["details"] or "",
            actor=row["actor"],
            created_at=parse_timestamp(row["created_at"]),
        )


@dataclass(frozen=True)
class EscalationEvent:
    id: int
    ticket_id: str
    escalation_type: str
    level: str
    reason: str
    details: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "EscalationEvent":
        return cls(
            id=int(row["id"]),
            ticket_id=row["ticket_id"],
            escalation_type=row["escalation_type"],
            level=row["level"],
            reason=row["reason"],
            details=row["details"] or "",
            created_at=parse_timestamp(row["created_at"]),
        )


@dataclass
class ImportRowError:
    row_number: int
    message: str
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportResult:
    total_rows: int = 0
    imported: int = 0
    skipped_duplicates: int = 0
    errors: list[ImportRowError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    imported_ids: list[str] = field(default_factory=list)

    @property
    def invalid_count(self) -> int:
        return len(self.errors)

    @property
    def summary(self) -> str:
        parts = [f"{self.imported} imported"]
        if self.skipped_duplicates:
            parts.append(f"{self.skipped_duplicates} duplicate(s) skipped")
        if self.errors:
            parts.append(f"{len(self.errors)} row(s) rejected")
        return ", ".join(parts)


@dataclass
class DashboardMetrics:
    total: int = 0
    open_count: int = 0
    in_progress: int = 0
    pending: int = 0
    resolved: int = 0
    closed: int = 0
    overdue: int = 0
    at_risk: int = 0
    compliance: float | None = None
    response_compliance: float | None = None
    avg_resolution_seconds: float | None = None
    status_counts: dict[str, int] = field(default_factory=dict)
    priority_counts: dict[str, int] = field(default_factory=dict)
    trend: list[dict[str, Any]] = field(default_factory=list)

    @property
    def active(self) -> int:
        return self.open_count + self.in_progress + self.pending


@dataclass(frozen=True)
class SLAReportRow:
    ticket: Ticket
    response_state: str
    resolution_state: str
    overall_state: str
    response_remaining: int | None
    resolution_remaining: int | None


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
