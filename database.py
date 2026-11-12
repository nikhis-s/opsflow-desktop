"""SQLite persistence layer for OpsFlow."""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import APP_NAME, APP_VERSION, get_db_path
from models import DEFAULT_POLICIES, utc_now

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS tickets (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL CHECK(length(trim(title)) > 0),
    description         TEXT NOT NULL DEFAULT '',
    requester           TEXT NOT NULL CHECK(length(trim(requester)) > 0),
    assignee            TEXT NOT NULL DEFAULT 'Unassigned',
    category            TEXT NOT NULL DEFAULT 'General',
    priority            TEXT NOT NULL CHECK(priority IN ('Critical','High','Medium','Low')),
    status              TEXT NOT NULL CHECK(status IN ('Open','In Progress','Pending','Resolved','Closed')),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    first_response_at   TEXT,
    resolved_at         TEXT,
    closed_at           TEXT,
    response_deadline   TEXT NOT NULL,
    resolution_deadline TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,
    body        TEXT NOT NULL CHECK(length(trim(body)) > 0),
    is_internal INTEGER NOT NULL DEFAULT 1 CHECK(is_internal IN (0,1)),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sla_policies (
    priority           TEXT PRIMARY KEY CHECK(priority IN ('Critical','High','Medium','Low')),
    response_minutes   INTEGER NOT NULL CHECK(response_minutes > 0),
    resolution_minutes INTEGER NOT NULL CHECK(resolution_minutes > 0),
    at_risk_percent    INTEGER NOT NULL DEFAULT 80 CHECK(at_risk_percent BETWEEN 1 AND 99),
    updated_at         TEXT NOT NULL
);

-- Audit events deliberately keep ticket_id without a foreign key so history
-- survives a hard ticket delete (the log is append-only).
CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  TEXT,
    action     TEXT NOT NULL,
    details    TEXT NOT NULL DEFAULT '',
    actor      TEXT NOT NULL DEFAULT 'system',
    created_at TEXT NOT NULL
);

-- Escalation history is also retained when a ticket is removed.
CREATE TABLE IF NOT EXISTS escalation_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       TEXT NOT NULL,
    escalation_type TEXT NOT NULL,
    level           TEXT NOT NULL CHECK(level IN ('INFO','WARNING','CRITICAL')),
    reason          TEXT NOT NULL,
    details         TEXT NOT NULL DEFAULT '',
    dedupe_key      TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee);
CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_resolution_deadline ON tickets(resolution_deadline);
CREATE INDEX IF NOT EXISTS idx_tickets_response_deadline ON tickets(response_deadline);
CREATE INDEX IF NOT EXISTS idx_tickets_status_deadline
    ON tickets(status, resolution_deadline);
CREATE INDEX IF NOT EXISTS idx_comments_ticket ON ticket_comments(ticket_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_ticket ON audit_events(ticket_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action);
CREATE INDEX IF NOT EXISTS idx_escalations_ticket ON escalation_events(ticket_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_escalations_created ON escalation_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_escalations_level ON escalation_events(level);
"""

REQUIRED_TABLES = {
    "tickets",
    "ticket_comments",
    "sla_policies",
    "audit_events",
    "escalation_events",
}

REQUIRED_COLUMNS = {
    "tickets": {
        "id", "title", "description", "requester", "assignee", "category",
        "priority", "status", "created_at", "updated_at", "first_response_at",
        "resolved_at", "closed_at", "response_deadline", "resolution_deadline",
    },
    "ticket_comments": {"id", "ticket_id", "author", "body", "is_internal", "created_at"},
    "sla_policies": {"priority", "response_minutes", "resolution_minutes",
                     "at_risk_percent", "updated_at"},
    "audit_events": {"id", "ticket_id", "action", "details", "actor", "created_at"},
    "escalation_events": {"id", "ticket_id", "escalation_type", "level", "reason",
                          "details", "dedupe_key", "created_at"},
}


class DatabaseError(RuntimeError):
    """Raised when OpsFlow cannot safely prepare its database."""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else get_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.path.parent / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.last_backup: Path | None = None

    # ------------------------------------------------------------------ setup
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=20, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 20000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        existed = self.path.exists() and self.path.stat().st_size > 0
        current_version = 0
        existing_tables: set[str] = set()

        if existed:
            probe = None
            try:
                probe = sqlite3.connect(str(self.path), timeout=10)
                current_version = int(probe.execute("PRAGMA user_version").fetchone()[0])
                existing_tables = {
                    row[0] for row in probe.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            except sqlite3.DatabaseError as exc:
                if probe is not None:
                    probe.close()
                    probe = None
                backup = self.backup_database("unreadable")
                raise DatabaseError(
                    "The existing OpsFlow database could not be read. "
                    f"A safety backup was written to {backup}. Original error: {exc}"
                ) from exc
            finally:
                if probe is not None:
                    probe.close()

            if current_version > SCHEMA_VERSION:
                raise DatabaseError(
                    f"The database at {self.path} uses schema v{current_version}, "
                    f"which is newer than this OpsFlow build (v{SCHEMA_VERSION}). "
                    "Install a newer OpsFlow build or restore a backup."
                )
            if existing_tables - REQUIRED_TABLES - {"sqlite_sequence"} and not (
                existing_tables & REQUIRED_TABLES
            ):
                backup = self.backup_database(f"v{current_version}-unrecognized")
                raise DatabaseError(
                    "The file at the OpsFlow data path is an unrecognized SQLite "
                    f"database. It was preserved at {backup}."
                )
            if current_version < SCHEMA_VERSION and existing_tables:
                self.last_backup = self.backup_database(f"v{current_version}-pre-migration")
                logger.info("Database backed up before migration: %s", self.last_backup)

        try:
            conn = self.connect()
            try:
                conn.executescript(SCHEMA_V1)
                now = utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
                for priority, (response, resolution, warn) in DEFAULT_POLICIES.items():
                    conn.execute(
                        """INSERT OR IGNORE INTO sla_policies
                           (priority, response_minutes, resolution_minutes,
                            at_risk_percent, updated_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (priority, response, resolution, warn, now),
                    )
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                self._validate_schema(conn)
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    self.last_backup = self.backup_database("integrity-failure")
                    raise DatabaseError(
                        f"SQLite integrity check failed: {integrity}. "
                        f"Backup: {self.last_backup}"
                    )
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"Could not initialize the OpsFlow database: {exc}") from exc

        logger.info("Database ready at %s (schema v%s)", self.path, SCHEMA_VERSION)

    def _validate_schema(self, conn: sqlite3.Connection) -> None:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise DatabaseError(f"Database is missing required tables: {', '.join(sorted(missing))}")
        for table, required in REQUIRED_COLUMNS.items():
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            absent = required - columns
            if absent:
                raise DatabaseError(
                    f"Database table '{table}' is missing columns: {', '.join(sorted(absent))}"
                )

    def backup_database(self, label: str = "manual") -> Path:
        safe_label = "".join(ch for ch in label if ch.isalnum() or ch in "-_") or "manual"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.backup_dir / f"opsflow-backup-{safe_label}-{stamp}.db"
        if not self.path.exists():
            raise DatabaseError("There is no database file to back up.")
        try:
            source = sqlite3.connect(str(self.path), timeout=10)
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
        except sqlite3.DatabaseError:
            import shutil
            shutil.copy2(self.path, destination)
        self.last_backup = destination
        logger.info("Database backup written to %s", destination)
        return destination

    # ------------------------------------------------------------------ info
    @property
    def schema_version(self) -> int:
        if not self.path.exists():
            return 0
        with self.read() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def size_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    def counts(self) -> dict[str, int]:
        with self.read() as conn:
            return {
                "tickets": conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
                "comments": conn.execute("SELECT COUNT(*) FROM ticket_comments").fetchone()[0],
                "audit_events": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
                "escalations": conn.execute("SELECT COUNT(*) FROM escalation_events").fetchone()[0],
            }

    def health(self) -> str:
        try:
            with self.read() as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            return "ok" if integrity == "ok" else integrity
        except sqlite3.DatabaseError as exc:
            return str(exc)

    def app_identity(self) -> dict[str, str]:
        return {"app": APP_NAME, "version": APP_VERSION, "database": str(self.path)}
