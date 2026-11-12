"""Ticket CRUD, assignment, status transitions, comments and audit integration."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from config import DEFAULT_ACTOR
from database import Database
from models import (
    ACTIVE_STATUSES,
    CATEGORIES,
    PRIORITIES,
    STATUSES,
    TICKET_ID_RE,
    Priority,
    Status,
    Ticket,
    TicketComment,
    ensure_aware,
    parse_timestamp,
    to_iso,
    truncate,
    utc_now,
)
from services.audit_service import AuditService
from services.sla_engine import SLAEngine

UNSET = object()


class ValidationError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


class DuplicateTicketError(ValidationError):
    pass


SORT_COLUMNS = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "resolution_deadline": "resolution_deadline",
    "response_deadline": "response_deadline",
    "priority": "CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 "
                "WHEN 'Medium' THEN 2 ELSE 3 END",
    "status": "CASE status WHEN 'Open' THEN 0 WHEN 'In Progress' THEN 1 "
              "WHEN 'Pending' THEN 2 WHEN 'Resolved' THEN 3 ELSE 4 END",
    "id": "id",
    "title": "lower(title)",
}


class TicketService:
    def __init__(self, db: Database, sla: SLAEngine, audit: AuditService):
        self.db = db
        self.sla = sla
        self.audit = audit

    # ------------------------------------------------------------------ reads
    def get_ticket(self, ticket_id: str) -> Ticket:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Ticket '{ticket_id}' was not found.")
        return Ticket.from_row(row)

    def find_ticket(self, ticket_id: str) -> Ticket | None:
        try:
            return self.get_ticket(ticket_id)
        except LookupError:
            return None

    def ticket_exists(self, ticket_id: str) -> bool:
        with self.db.read() as conn:
            return conn.execute(
                "SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone() is not None

    def list_tickets(
        self,
        search: str = "",
        priority: str = "",
        status: str = "",
        assignee: str = "",
        category: str = "",
        sort: str = "created_at",
        descending: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Ticket]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(id) LIKE ? OR lower(title) LIKE ? OR lower(requester) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if assignee:
            clauses.append("assignee = ?")
            params.append(assignee)
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_column = SORT_COLUMNS.get(sort, "created_at")
        direction = "DESC" if descending else "ASC"
        sql = f"SELECT * FROM tickets {where} ORDER BY {order_column} {direction}, id {direction}"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([max(1, int(limit)), max(0, int(offset))])
        with self.db.read() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [Ticket.from_row(row) for row in rows]

    def count(self, search: str = "", priority: str = "", status: str = "",
              assignee: str = "", category: str = "") -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(id) LIKE ? OR lower(title) LIKE ? OR lower(requester) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        for field, value in (("priority", priority), ("status", status),
                             ("assignee", assignee), ("category", category)):
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.read() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM tickets {where}", params).fetchone()[0])

    def get_assignees(self) -> list[str]:
        with self.db.read() as conn:
            values = [row[0] for row in conn.execute(
                "SELECT DISTINCT assignee FROM tickets "
                "WHERE assignee IS NOT NULL AND trim(assignee) <> '' ORDER BY assignee"
            )]
        return values

    def get_requesters(self) -> list[str]:
        with self.db.read() as conn:
            values = [row[0] for row in conn.execute(
                "SELECT DISTINCT requester FROM tickets ORDER BY requester"
            )]
        return values

    def get_categories(self) -> list[str]:
        with self.db.read() as conn:
            values = [row[0] for row in conn.execute(
                "SELECT DISTINCT category FROM tickets ORDER BY category"
            )]
        return sorted(set(CATEGORIES) | set(values))

    def get_comments(self, ticket_id: str) -> list[TicketComment]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM ticket_comments WHERE ticket_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (ticket_id,),
            ).fetchall()
        return [TicketComment.from_row(row) for row in rows]

    def get_audit(self, ticket_id: str) -> list[Any]:
        return self.audit.for_ticket(ticket_id)

    # ----------------------------------------------------------------- create
    def _next_ticket_id(self, conn: sqlite3.Connection) -> str:
        rows = conn.execute("SELECT id FROM tickets WHERE id LIKE 'TKT-%'").fetchall()
        highest = 0
        for row in rows:
            suffix = row[0][4:]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"TKT-{highest + 1:04d}"

    def create_ticket(
        self,
        title: str,
        description: str = "",
        requester: str = "",
        assignee: str = "Unassigned",
        category: str = "General",
        priority: str = Priority.MEDIUM.value,
        status: str = Status.OPEN.value,
        created_at: datetime | str | None = None,
        ticket_id: str | None = None,
        first_response_at: datetime | str | None = None,
        resolved_at: datetime | str | None = None,
        closed_at: datetime | str | None = None,
        response_deadline: datetime | str | None = None,
        resolution_deadline: datetime | str | None = None,
        actor: str | None = None,
    ) -> Ticket:
        title = self._required(title, "Title", 200)
        requester = self._required(requester, "Requester", 120)
        description = (description or "").strip()
        assignee = (assignee or "Unassigned").strip() or "Unassigned"
        category = (category or "General").strip() or "General"
        self._validate_priority(priority)
        self._validate_status(status)
        created = ensure_aware(parse_timestamp(created_at) if created_at else utc_now())
        if ticket_id:
            normalized_id = ticket_id.strip().upper()
            if not TICKET_ID_RE.match(normalized_id):
                raise ValidationError(
                    "Ticket ID must be 1-40 characters using letters, digits, hyphens or underscores."
                )
        else:
            normalized_id = None

        policies = self.sla.get_policies()
        calc_response, calc_resolution = self.sla.deadlines_for(priority, created, policies)
        response_dt = ensure_aware(parse_timestamp(response_deadline)) if response_deadline else calc_response
        resolution_dt = ensure_aware(parse_timestamp(resolution_deadline)) if resolution_deadline else calc_resolution
        if resolution_dt < response_dt:
            raise ValidationError("Resolution deadline cannot be earlier than the response deadline.")

        first_response = ensure_aware(parse_timestamp(first_response_at)) if first_response_at else None
        resolved = ensure_aware(parse_timestamp(resolved_at)) if resolved_at else None
        closed = ensure_aware(parse_timestamp(closed_at)) if closed_at else None
        if status in (Status.RESOLVED.value, Status.CLOSED.value):
            resolved = resolved or created
            if status == Status.CLOSED.value:
                closed = closed or created
        if status != Status.OPEN.value and first_response is None:
            first_response = resolved or closed or created

        now = utc_now()
        with self.db.transaction() as conn:
            if normalized_id is None:
                normalized_id = self._next_ticket_id(conn)
            if conn.execute("SELECT 1 FROM tickets WHERE id = ?", (normalized_id,)).fetchone():
                raise DuplicateTicketError(f"Ticket ID '{normalized_id}' already exists.")
            conn.execute(
                """INSERT INTO tickets (
                    id, title, description, requester, assignee, category, priority,
                    status, created_at, updated_at, first_response_at, resolved_at,
                    closed_at, response_deadline, resolution_deadline
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    normalized_id, title, description, requester, assignee, category,
                    priority, status, to_iso(created), to_iso(now),
                    to_iso(first_response), to_iso(resolved), to_iso(closed),
                    to_iso(response_dt), to_iso(resolution_dt),
                ),
            )
            self.audit.record(
                conn, normalized_id, "TICKET_CREATED",
                f"Created “{title}” · {priority} priority · {status} · requester {requester}",
                actor or DEFAULT_ACTOR, now,
            )
        return self.get_ticket(normalized_id)

    # ----------------------------------------------------------------- update
    def update_ticket(
        self,
        ticket_id: str,
        changes: dict[str, Any],
        actor: str | None = None,
    ) -> Ticket:
        allowed = {"title", "description", "requester", "assignee", "category",
                   "priority", "status"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValidationError(f"Unsupported ticket field(s): {', '.join(sorted(unknown))}")

        current = self.get_ticket(ticket_id)
        policies = self.sla.get_policies()
        clean: dict[str, Any] = {}
        for field, value in changes.items():
            if field == "title":
                value = self._required(value, "Title", 200)
            elif field == "requester":
                value = self._required(value, "Requester", 120)
            elif field == "description":
                value = (value or "").strip()
                if len(value) > 50000:
                    raise ValidationError("Description is too long (maximum 50,000 characters).")
            elif field == "assignee":
                value = (value or "Unassigned").strip() or "Unassigned"
            elif field == "category":
                value = (value or "General").strip() or "General"
            elif field == "priority":
                self._validate_priority(value)
            elif field == "status":
                self._validate_status(value)
            clean[field] = value

        actual = {
            key: value for key, value in clean.items()
            if getattr(current, key) != value
        }
        if not actual:
            return current

        now = utc_now()
        assignments: dict[str, Any] = {}
        extra_updates: dict[str, Any] = {}

        new_priority = actual.get("priority", current.priority)
        if "priority" in actual:
            new_response, new_resolution = self.sla.deadlines_for(
                new_priority, current.created_at, policies
            )
            if (new_response != current.response_deadline
                    or new_resolution != current.resolution_deadline):
                extra_updates["response_deadline"] = to_iso(new_response)
                extra_updates["resolution_deadline"] = to_iso(new_resolution)

        new_status = actual.get("status", current.status)
        if "status" in actual:
            if current.status == Status.OPEN.value and new_status != Status.OPEN.value:
                if current.first_response_at is None:
                    extra_updates["first_response_at"] = to_iso(now)
            if new_status == Status.RESOLVED.value and current.status != Status.RESOLVED.value:
                extra_updates["resolved_at"] = to_iso(now)
                extra_updates["closed_at"] = None
            elif new_status == Status.CLOSED.value:
                if current.resolved_at is None:
                    extra_updates["resolved_at"] = to_iso(now)
                if current.closed_at is None:
                    extra_updates["closed_at"] = to_iso(now)
            elif new_status in ACTIVE_STATUSES and current.status in (
                Status.RESOLVED.value, Status.CLOSED.value
            ):
                extra_updates["resolved_at"] = None
                extra_updates["closed_at"] = None

        for field, value in actual.items():
            assignments[field] = value
        assignments.update(extra_updates)
        assignments["updated_at"] = to_iso(now)

        set_clause = ", ".join(f"{field} = ?" for field in assignments)
        params = [*assignments.values(), ticket_id]
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE tickets SET {set_clause} WHERE id = ?", params)
            # Field-level audit records.
            if "title" in actual:
                self.audit.record(
                    conn, ticket_id, "TITLE_CHANGED",
                    f"{truncate(current.title, 80)} → {truncate(actual['title'], 80)}",
                    actor or DEFAULT_ACTOR, now,
                )
            if "description" in actual:
                self.audit.record(
                    conn, ticket_id, "DESCRIPTION_CHANGED",
                    f"Description updated ({len(actual['description'])} characters)",
                    actor or DEFAULT_ACTOR, now,
                )
            if "requester" in actual:
                self.audit.record(
                    conn, ticket_id, "REQUESTER_CHANGED",
                    f"{current.requester} → {actual['requester']}",
                    actor or DEFAULT_ACTOR, now,
                )
            if "assignee" in actual:
                action = "REASSIGNED" if current.assignee != "Unassigned" else "ASSIGNED"
                self.audit.record(
                    conn, ticket_id, action,
                    f"{current.assignee} → {actual['assignee']}",
                    actor or DEFAULT_ACTOR, now,
                )
            if "category" in actual:
                self.audit.record(
                    conn, ticket_id, "CATEGORY_CHANGED",
                    f"{current.category} → {actual['category']}",
                    actor or DEFAULT_ACTOR, now,
                )
            if "priority" in actual:
                self.audit.record(
                    conn, ticket_id, "PRIORITY_CHANGED",
                    f"{current.priority} → {actual['priority']}",
                    actor or DEFAULT_ACTOR, now,
                )
                if "response_deadline" in extra_updates:
                    self.audit.record(
                        conn, ticket_id, "SLA_RECALCULATED",
                        "Deadlines recalculated for new priority · "
                        f"response {to_iso(new_response)} · resolution {to_iso(new_resolution)}",
                        actor or DEFAULT_ACTOR, now,
                    )
            if "status" in actual:
                self.audit.record(
                    conn, ticket_id, "STATUS_CHANGED",
                    f"{current.status} → {actual['status']}",
                    actor or DEFAULT_ACTOR, now,
                )
        return self.get_ticket(ticket_id)

    def change_status(
        self, ticket_id: str, status: str, note: str = "", actor: str | None = None
    ) -> Ticket:
        updated = self.update_ticket(ticket_id, {"status": status}, actor)
        if note.strip():
            self.add_comment(ticket_id, note, author=actor, internal=True)
        return updated

    def assign_ticket(self, ticket_id: str, assignee: str, actor: str | None = None) -> Ticket:
        return self.update_ticket(ticket_id, {"assignee": assignee}, actor)

    # --------------------------------------------------------------- comments
    def add_comment(
        self,
        ticket_id: str,
        body: str,
        author: str | None = None,
        internal: bool = True,
    ) -> TicketComment:
        body = self._required(body, "Comment", 10000)
        self.get_ticket(ticket_id)  # validates the ticket exists before writing
        now = utc_now()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO ticket_comments
                   (ticket_id, author, body, is_internal, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (ticket_id, author or DEFAULT_ACTOR, body, 1 if internal else 0, to_iso(now)),
            )
            conn.execute(
                "UPDATE tickets SET updated_at = ? WHERE id = ?", (to_iso(now), ticket_id)
            )
            self.audit.record(
                conn, ticket_id, "COMMENT_ADDED",
                f"Internal note by {author or DEFAULT_ACTOR}: {truncate(body, 160)}",
                author or DEFAULT_ACTOR, now,
            )
            comment_id = int(cursor.lastrowid or 0)
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT * FROM ticket_comments WHERE id = ?", (comment_id,)
            ).fetchone()
        return TicketComment.from_row(row)

    # ----------------------------------------------------------------- delete
    def delete_ticket(self, ticket_id: str, actor: str | None = None) -> None:
        ticket = self.get_ticket(ticket_id)
        now = utc_now()
        with self.db.transaction() as conn:
            self.audit.record(
                conn, ticket_id, "TICKET_DELETED",
                f"Deleted “{ticket.title}” ({ticket.status}, {ticket.priority})",
                actor or DEFAULT_ACTOR, now,
            )
            conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))

    # --------------------------------------------------------- SLA recalc
    def recalculate_active_deadlines(
        self, priority: str | None = None, actor: str | None = None
    ) -> int:
        policies = self.sla.get_policies()
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        clauses = [f"status IN ({placeholders})"]
        params: list[Any] = list(ACTIVE_STATUSES)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        with self.db.read() as conn:
            rows = conn.execute(
                f"SELECT * FROM tickets WHERE {' AND '.join(clauses)}", params
            ).fetchall()
        changed = 0
        now = utc_now()
        for row in rows:
            ticket = Ticket.from_row(row)
            policy = policies.get(ticket.priority)
            if policy is None:
                continue
            new_response = ticket.created_at + timedelta(minutes=policy.response_minutes)
            new_resolution = ticket.created_at + timedelta(minutes=policy.resolution_minutes)
            if (new_response == ticket.response_deadline
                    and new_resolution == ticket.resolution_deadline):
                continue
            with self.db.transaction() as conn:
                conn.execute(
                    """UPDATE tickets SET response_deadline = ?, resolution_deadline = ?,
                       updated_at = ? WHERE id = ?""",
                    (to_iso(new_response), to_iso(new_resolution), to_iso(now), ticket.id),
                )
                self.audit.record(
                    conn, ticket.id, "SLA_RECALCULATED",
                    "Active ticket deadlines refreshed after SLA policy change · "
                    f"response {to_iso(new_response)} · resolution {to_iso(new_resolution)}",
                    actor or DEFAULT_ACTOR, now,
                )
            changed += 1
        return changed

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _required(value: str, label: str, max_length: int) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValidationError(f"{label} is required.")
        if len(cleaned) > max_length:
            raise ValidationError(f"{label} must be {max_length} characters or fewer.")
        return cleaned

    @staticmethod
    def _validate_priority(value: str) -> None:
        if value not in PRIORITIES:
            raise ValidationError(
                f"Invalid priority '{value}'. Choose from: {', '.join(PRIORITIES)}."
            )

    @staticmethod
    def _validate_status(value: str) -> None:
        if value not in STATUSES:
            raise ValidationError(
                f"Invalid status '{value}'. Choose from: {', '.join(STATUSES)}."
            )
