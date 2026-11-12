"""Append-only audit trail operations."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from config import DEFAULT_ACTOR
from database import Database
from models import AuditEvent, to_iso, utc_now


class AuditService:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        conn: sqlite3.Connection,
        ticket_id: str | None,
        action: str,
        details: str = "",
        actor: str | None = None,
        created_at: datetime | None = None,
    ) -> int:
        cursor = conn.execute(
            """INSERT INTO audit_events
               (ticket_id, action, details, actor, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (ticket_id, action, details, actor or DEFAULT_ACTOR,
             to_iso(created_at or utc_now())),
        )
        return int(cursor.lastrowid)

    def log(
        self,
        ticket_id: str | None,
        action: str,
        details: str = "",
        actor: str | None = None,
    ) -> None:
        with self.db.transaction() as conn:
            self.record(conn, ticket_id, action, details, actor)

    def list_events(
        self,
        search: str = "",
        action: str = "",
        ticket_id: str = "",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[AuditEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(ticket_id) LIKE ? OR lower(action) LIKE ? "
                "OR lower(details) LIKE ? OR lower(actor) LIKE ?)"
            )
            params.extend([needle] * 4)
        if action.strip():
            clauses.append("action = ?")
            params.append(action.strip())
        if ticket_id.strip():
            clauses.append("ticket_id = ?")
            params.append(ticket_id.strip())
        if date_from:
            clauses.append("created_at >= ?")
            params.append(to_iso(date_from))
        if date_to:
            clauses.append("created_at <= ?")
            params.append(to_iso(date_to))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM audit_events {where} "
            "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        )
        params.extend([max(1, int(limit)), max(0, int(offset))])
        with self.db.read() as conn:
            return [AuditEvent.from_row(row) for row in conn.execute(sql, params)]

    def count(
        self,
        search: str = "",
        action: str = "",
        ticket_id: str = "",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        # Reuse the filtering SQL shape without duplicating the date logic in UI.
        clauses: list[str] = []
        params: list[Any] = []
        if search.strip():
            needle = f"%{search.strip().lower()}%"
            clauses.append(
                "(lower(ticket_id) LIKE ? OR lower(action) LIKE ? "
                "OR lower(details) LIKE ? OR lower(actor) LIKE ?)"
            )
            params.extend([needle] * 4)
        if action.strip():
            clauses.append("action = ?")
            params.append(action.strip())
        if ticket_id.strip():
            clauses.append("ticket_id = ?")
            params.append(ticket_id.strip())
        if date_from:
            clauses.append("created_at >= ?")
            params.append(to_iso(date_from))
        if date_to:
            clauses.append("created_at <= ?")
            params.append(to_iso(date_to))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.db.read() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM audit_events {where}", params).fetchone()[0])

    def actions(self) -> list[str]:
        with self.db.read() as conn:
            return [
                row[0] for row in conn.execute(
                    "SELECT DISTINCT action FROM audit_events ORDER BY action"
                )
            ]

    def recent(self, limit: int = 8) -> list[AuditEvent]:
        with self.db.read() as conn:
            return [
                AuditEvent.from_row(row) for row in conn.execute(
                    "SELECT * FROM audit_events ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                )
            ]

    def for_ticket(self, ticket_id: str, limit: int = 100) -> list[AuditEvent]:
        with self.db.read() as conn:
            return [
                AuditEvent.from_row(row) for row in conn.execute(
                    """SELECT * FROM audit_events WHERE ticket_id = ?
                       ORDER BY created_at DESC, id DESC LIMIT ?""",
                    (ticket_id, limit),
                )
            ]
