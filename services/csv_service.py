"""CSV import validation and report export using the standard library csv module."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import DEFAULT_ACTOR
from database import Database
from models import (
    ImportResult, ImportRowError, PRIORITIES, STATUSES, Ticket, format_local,
    parse_user_timestamp, to_iso, utc_now,
)
from services.analytics import AnalyticsService
from services.audit_service import AuditService
from services.escalation_engine import EscalationEngine
from services.sla_engine import SLAEngine
from services.ticket_service import DuplicateTicketError, TicketService, ValidationError

TICKET_EXPORT_COLUMNS = [
    "ticket_id", "title", "description", "requester", "assignee", "category",
    "priority", "status", "created_at", "updated_at", "first_response_at",
    "resolved_at", "closed_at", "response_deadline", "resolution_deadline",
    "sla_state",
]

IMPORT_ALIASES = {
    "id": "ticket_id",
    "ticket": "ticket_id",
    "ticketid": "ticket_id",
    "summary": "title",
    "subject": "title",
    "requested_by": "requester",
    "requestor": "requester",
    "owner": "assignee",
    "assigned_to": "assignee",
    "type": "category",
    "created": "created_at",
    "updated": "updated_at",
    "response_due": "response_deadline",
    "resolution_due": "resolution_deadline",
    "first_response": "first_response_at",
    "resolved": "resolved_at",
    "closed": "closed_at",
}

IMPORT_FIELDS = {
    "ticket_id", "title", "description", "requester", "assignee", "category",
    "priority", "status", "created_at", "updated_at", "first_response_at",
    "resolved_at", "closed_at", "response_deadline", "resolution_deadline",
}
REQUIRED_IMPORT_FIELDS = {"title", "requester", "priority"}


class CSVFormatError(ValueError):
    pass


class _RowValidationError(Exception):
    """Internal signal used while validating a single CSV row."""

    def __init__(self, row_number: int, message: str, raw: dict[str, str]):
        super().__init__(message)
        self.row_number = row_number
        self.message = message
        self.raw = raw


def _normalize_header(header: str) -> str:
    key = (header or "").strip().lower().replace(" ", "_").replace("-", "_")
    return IMPORT_ALIASES.get(key, key)


def _canonical_choice(value: str, choices: Iterable[str]) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    lower_map = {choice.lower(): choice for choice in choices}
    compact_map = {choice.lower().replace(" ", "").replace("-", ""): choice for choice in choices}
    return lower_map.get(cleaned.lower()) or compact_map.get(
        cleaned.lower().replace(" ", "").replace("-", "")
    )


class CSVService:
    def __init__(
        self,
        db: Database,
        tickets: TicketService,
        sla: SLAEngine,
        escalations: EscalationEngine,
        audit: AuditService,
        analytics: AnalyticsService,
    ):
        self.db = db
        self.tickets = tickets
        self.sla = sla
        self.escalations = escalations
        self.audit = audit
        self.analytics = analytics

    # ---------------------------------------------------------------- exports
    def export_tickets(self, path: str | Path, tickets: list[Ticket] | None = None) -> int:
        items = tickets if tickets is not None else self.tickets.list_tickets(sort="id", descending=False)
        evaluations = self.sla.evaluate_many(items)
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=TICKET_EXPORT_COLUMNS)
            writer.writeheader()
            for ticket in items:
                writer.writerow({
                    "ticket_id": ticket.id,
                    "title": ticket.title,
                    "description": ticket.description,
                    "requester": ticket.requester,
                    "assignee": ticket.assignee,
                    "category": ticket.category,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "created_at": to_iso(ticket.created_at),
                    "updated_at": to_iso(ticket.updated_at),
                    "first_response_at": to_iso(ticket.first_response_at),
                    "resolved_at": to_iso(ticket.resolved_at),
                    "closed_at": to_iso(ticket.closed_at),
                    "response_deadline": to_iso(ticket.response_deadline),
                    "resolution_deadline": to_iso(ticket.resolution_deadline),
                    "sla_state": evaluations[ticket.id].overall_state,
                })
        return len(items)

    def export_sla_report(self, path: str | Path) -> int:
        rows = self.analytics.sla_report()
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            fieldnames = [
                "ticket_id", "title", "priority", "status", "assignee",
                "created_at", "response_deadline", "response_state",
                "resolution_deadline", "resolution_state", "overall_state",
                "response_remaining_seconds", "resolution_remaining_seconds",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "ticket_id": row.ticket.id,
                    "title": row.ticket.title,
                    "priority": row.ticket.priority,
                    "status": row.ticket.status,
                    "assignee": row.ticket.assignee,
                    "created_at": to_iso(row.ticket.created_at),
                    "response_deadline": to_iso(row.ticket.response_deadline),
                    "response_state": row.response_state,
                    "resolution_deadline": to_iso(row.ticket.resolution_deadline),
                    "resolution_state": row.resolution_state,
                    "overall_state": row.overall_state,
                    "response_remaining_seconds": row.response_remaining,
                    "resolution_remaining_seconds": row.resolution_remaining,
                })
        return len(rows)

    def export_escalations(self, path: str | Path) -> int:
        events = self.escalations.list_events(limit=100000)
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            fieldnames = ["id", "ticket_id", "level", "escalation_type",
                          "reason", "details", "created_at"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in events:
                writer.writerow({
                    "id": event.id,
                    "ticket_id": event.ticket_id,
                    "level": event.level,
                    "escalation_type": event.escalation_type,
                    "reason": event.reason,
                    "details": event.details,
                    "created_at": to_iso(event.created_at),
                })
        return len(events)

    def export_audit(self, path: str | Path, events: list[Any] | None = None) -> int:
        items = events if events is not None else self.audit.list_events(limit=100000)
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            fieldnames = ["id", "created_at", "ticket_id", "action", "details", "actor"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for event in items:
                writer.writerow({
                    "id": event.id,
                    "created_at": to_iso(event.created_at),
                    "ticket_id": event.ticket_id or "",
                    "action": event.action,
                    "details": event.details,
                    "actor": event.actor,
                })
        return len(items)

    def write_template(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "ticket_id", "title", "description", "requester", "assignee",
                    "category", "priority", "status", "created_at",
                    "response_deadline", "resolution_deadline",
                ],
            )
            writer.writeheader()
            writer.writerow({
                "ticket_id": "TKT-9001",
                "title": "VPN disconnects every few minutes",
                "description": "Remote access drops during calls.",
                "requester": "Jordan Lee",
                "assignee": "Network Queue",
                "category": "Network",
                "priority": "High",
                "status": "Open",
                "created_at": "2026-05-01 09:30",
                "response_deadline": "",
                "resolution_deadline": "",
            })

    # ----------------------------------------------------------------- import
    def import_tickets(self, path: str | Path, actor: str | None = None) -> ImportResult:
        path = Path(path)
        if not path.exists():
            raise CSVFormatError(f"CSV file not found: {path}")
        result = ImportResult()
        prepared: list[tuple[int, dict[str, Any]]] = []
        seen_ids: set[str] = set()

        try:
            try:
                handle = open(path, "r", newline="", encoding="utf-8-sig")
                sample = handle.read(2048)
                handle.seek(0)
                delimiter = ","
                if sample:
                    try:
                        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
                    except csv.Error:
                        delimiter = ","
            except UnicodeDecodeError:
                handle = open(path, "r", newline="", encoding="cp1252")
                delimiter = ","
            with handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                if not reader.fieldnames:
                    raise CSVFormatError("The CSV file has no header row.")
                header_map: dict[str, str] = {}
                unknown: list[str] = []
                for original in reader.fieldnames:
                    normalized = _normalize_header(original)
                    if normalized in IMPORT_FIELDS:
                        header_map[normalized] = original
                    elif original and original.strip():
                        unknown.append(original.strip())
                missing = REQUIRED_IMPORT_FIELDS - set(header_map)
                if missing:
                    raise CSVFormatError(
                        "Missing required column(s): " + ", ".join(sorted(missing))
                        + ". Required: title, requester, priority."
                    )
                if unknown:
                    result.warnings.append(
                        "Ignored unrecognized column(s): " + ", ".join(unknown)
                    )

                for raw_row in reader:
                    row_number = reader.line_num
                    if not any((value or "").strip() for value in raw_row.values()):
                        continue
                    result.total_rows += 1
                    record = {
                        field: (raw_row.get(original) or "").strip()
                        for field, original in header_map.items()
                    }
                    try:
                        prepared_row = self._validate_import_row(
                            record, row_number, seen_ids, result
                        )
                        if prepared_row is not None:
                            prepared.append((row_number, prepared_row))
                    except _RowValidationError as exc:
                        result.errors.append(
                            ImportRowError(exc.row_number, exc.message, exc.raw)
                        )
        except CSVFormatError:
            raise
        except OSError as exc:
            raise CSVFormatError(f"Could not read the CSV file: {exc}") from exc

        for row_number, data in prepared:
            try:
                ticket = self.tickets.create_ticket(
                    title=data["title"],
                    description=data.get("description", ""),
                    requester=data["requester"],
                    assignee=data.get("assignee", "Unassigned"),
                    category=data.get("category", "General"),
                    priority=data["priority"],
                    status=data.get("status", "Open"),
                    created_at=data.get("created_at"),
                    ticket_id=data.get("ticket_id") or None,
                    first_response_at=data.get("first_response_at"),
                    resolved_at=data.get("resolved_at"),
                    closed_at=data.get("closed_at"),
                    response_deadline=data.get("response_deadline"),
                    resolution_deadline=data.get("resolution_deadline"),
                    actor=actor or DEFAULT_ACTOR,
                )
                result.imported += 1
                result.imported_ids.append(ticket.id)
                if data.get("status") in ("Resolved", "Closed") and not data.get("resolved_at"):
                    result.warnings.append(
                        f"Row {row_number}: completed status without resolved_at; "
                        "creation time used as resolution time."
                    )
            except DuplicateTicketError:
                result.skipped_duplicates += 1
            except (ValidationError, ValueError) as exc:
                result.errors.append(ImportRowError(row_number, str(exc), data))
            except Exception as exc:  # pragma: no cover - defensive database boundary
                result.errors.append(ImportRowError(row_number, f"Database error: {exc}", data))

        self.audit.log(
            None, "CSV_IMPORT",
            f"Imported {result.imported} ticket(s) from {path.name}; "
            f"{result.skipped_duplicates} duplicate(s), {result.invalid_count} rejected row(s).",
            actor or DEFAULT_ACTOR,
        )
        return result

    def _validate_import_row(
        self,
        record: dict[str, str],
        row_number: int,
        seen_ids: set[str],
        result: ImportResult,
    ) -> dict[str, Any] | None:
        title = record.get("title", "").strip()
        requester = record.get("requester", "").strip()
        if not title:
            raise _RowValidationError(row_number, "title is required", record)
        if not requester:
            raise _RowValidationError(row_number, "requester is required", record)

        priority = _canonical_choice(record.get("priority", ""), PRIORITIES)
        if priority is None:
            raise _RowValidationError(
                row_number,
                f"invalid priority '{record.get('priority', '')}' "
                f"(expected Critical, High, Medium or Low)",
                record,
            )
        raw_status = record.get("status", "").strip()
        status = _canonical_choice(raw_status, STATUSES)
        if status is None:
            if raw_status:
                raise _RowValidationError(
                    row_number,
                    f"invalid status '{raw_status}' "
                    "(expected Open, In Progress, Pending, Resolved or Closed)",
                    record,
                )
            status = "Open"

        ticket_id = record.get("ticket_id", "").strip()
        if ticket_id:
            ticket_id = ticket_id.upper()
            if ticket_id in seen_ids or self.tickets.ticket_exists(ticket_id):
                result.skipped_duplicates += 1
                return None
            seen_ids.add(ticket_id)

        data: dict[str, Any] = {
            "ticket_id": ticket_id,
            "title": title,
            "description": record.get("description", ""),
            "requester": requester,
            "assignee": record.get("assignee", "") or "Unassigned",
            "category": record.get("category", "") or "General",
            "priority": priority,
            "status": status,
        }
        timestamp_fields = [
            "created_at", "first_response_at", "resolved_at", "closed_at",
            "response_deadline", "resolution_deadline",
        ]
        for field in timestamp_fields:
            raw = record.get(field, "").strip()
            if not raw:
                continue
            try:
                data[field] = parse_user_timestamp(raw)
            except ValueError:
                raise _RowValidationError(
                    row_number,
                    f"{field}: invalid timestamp '{raw}' "
                    "(use ISO/date, e.g. 2026-05-01 14:30)",
                    record,
                ) from None
        return data
