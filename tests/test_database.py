from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from database import SCHEMA_VERSION, Database, DatabaseError
from models import utc_now


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="opsflow-db-test-")
        self.path = Path(self.tempdir.name) / "opsflow.db"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_initialize_creates_schema_and_defaults(self) -> None:
        db = Database(self.path)
        db.initialize()
        self.assertTrue(self.path.exists())
        self.assertEqual(db.schema_version, SCHEMA_VERSION)
        self.assertEqual(db.health(), "ok")
        self.assertIsNone(db.last_backup)
        self.assertEqual(db.counts(), {
            "tickets": 0, "comments": 0, "audit_events": 0, "escalations": 0,
        })
        self.assertGreater(db.size_bytes(), 0)
        with db.read() as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertTrue({"tickets", "ticket_comments", "sla_policies",
                             "audit_events", "escalation_events"} <= tables)
            indexes = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            )}
            self.assertIn("idx_tickets_status", indexes)
            self.assertIn("idx_escalations_ticket", indexes)
            policies = dict(conn.execute(
                "SELECT priority, response_minutes FROM sla_policies"
            ).fetchall())
            self.assertEqual(policies, {
                "Critical": 15, "High": 30, "Medium": 120, "Low": 240,
            })
            identity = db.app_identity()
            self.assertEqual(identity["app"], "OpsFlow")
            self.assertEqual(identity["database"], str(self.path))

    def test_initialize_is_idempotent(self) -> None:
        db = Database(self.path)
        db.initialize()
        db.initialize()
        with db.read() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sla_policies").fetchone()[0], 4
            )

    def test_backup_database_creates_usable_copy(self) -> None:
        db = Database(self.path)
        db.initialize()
        with db.transaction() as conn:
            conn.execute(
                """INSERT INTO audit_events (ticket_id, action, details, actor, created_at)
                   VALUES ('TKT-1', 'TICKET_CREATED', 'demo', 'tester', ?)""",
                (utc_now().isoformat(),),
            )
        backup = db.backup_database("unit-test")
        self.assertTrue(backup.exists())
        self.assertEqual(db.last_backup, backup)
        self.assertTrue(backup.name.startswith("opsflow-backup-unit-test-"))
        with closing(sqlite3.connect(str(backup))) as conn:
            count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual(count, 1)

    def test_migration_from_older_schema_creates_backup(self) -> None:
        db = Database(self.path)
        db.initialize()
        with closing(sqlite3.connect(str(self.path))) as conn:
            conn.execute("PRAGMA user_version = 0")
            conn.commit()
        reopened = Database(self.path)
        reopened.initialize()
        self.assertEqual(reopened.schema_version, SCHEMA_VERSION)
        backup = reopened.last_backup
        self.assertIsNotNone(backup)
        assert backup is not None
        self.assertTrue(backup.exists())
        self.assertIn("pre-migration", backup.name)

    def test_newer_schema_is_refused(self) -> None:
        db = Database(self.path)
        db.initialize()
        with closing(sqlite3.connect(str(self.path))) as conn:
            conn.execute("PRAGMA user_version = 99")
            conn.commit()
        with self.assertRaises(DatabaseError) as caught:
            Database(self.path).initialize()
        self.assertIn("newer than this OpsFlow build", str(caught.exception))

    def test_unrecognized_sqlite_file_is_preserved_and_refused(self) -> None:
        with closing(sqlite3.connect(str(self.path))) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO unrelated DEFAULT VALUES")
            conn.commit()
        db = Database(self.path)
        with self.assertRaises(DatabaseError) as caught:
            db.initialize()
        self.assertIn("unrecognized", str(caught.exception))
        backup = db.last_backup
        self.assertIsNotNone(backup)
        assert backup is not None
        self.assertTrue(backup.exists())
        with closing(sqlite3.connect(str(backup))) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM unrelated").fetchone()[0], 1
            )

    def test_unreadable_file_is_backed_up(self) -> None:
        self.path.write_bytes(b"this is definitely not a sqlite database\n" * 20)
        db = Database(self.path)
        with self.assertRaises(DatabaseError) as caught:
            db.initialize()
        self.assertIn("could not be read", str(caught.exception))
        backup = db.last_backup
        self.assertIsNotNone(backup)
        assert backup is not None
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), self.path.read_bytes())


class DatabaseTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="opsflow-db-test-")
        self.db = Database(Path(self.tempdir.name) / "opsflow.db")
        self.db.initialize()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_foreign_keys_are_enabled(self) -> None:
        with self.db.read() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                             "wal")

    def test_transaction_commits_and_rolls_back(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO audit_events (ticket_id, action, details, actor, created_at)
                   VALUES (NULL, 'UNIT_COMMIT', 'ok', 'tester', ?)""",
                (utc_now().isoformat(),),
            )
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as conn:
                conn.execute(
                    """INSERT INTO audit_events
                       (ticket_id, action, details, actor, created_at)
                       VALUES (NULL, 'UNIT_ROLLBACK', 'failed', 'tester', ?)""",
                    (utc_now().isoformat(),),
                )
                raise RuntimeError("rollback please")
        with self.db.read() as conn:
            actions = {row[0] for row in conn.execute("SELECT action FROM audit_events")}
        self.assertIn("UNIT_COMMIT", actions)
        self.assertNotIn("UNIT_ROLLBACK", actions)

    def test_foreign_key_cascade_removes_comments(self) -> None:
        now = utc_now().isoformat()
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO tickets (
                    id, title, description, requester, assignee, category, priority,
                    status, created_at, updated_at, response_deadline, resolution_deadline
                ) VALUES ('TKT-TEST', 'Title', '', 'Req', 'Agent', 'General', 'Low',
                          'Open', ?, ?, ?, ?)""",
                (now, now, now, now),
            )
            conn.execute(
                """INSERT INTO ticket_comments
                   (ticket_id, author, body, is_internal, created_at)
                   VALUES ('TKT-TEST', 'tester', 'hello', 1, ?)""",
                (now,),
            )
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM tickets WHERE id = 'TKT-TEST'")
        with self.db.read() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM ticket_comments").fetchone()[0], 0
            )

    def test_integrity_and_counts(self) -> None:
        self.assertEqual(self.db.health(), "ok")
        self.assertEqual(self.db.counts()["tickets"], 0)


if __name__ == "__main__":
    unittest.main()
