"""Shared test fixtures for OpsFlow."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import Database
from services.analytics import AnalyticsService
from services.audit_service import AuditService
from services.csv_service import CSVService
from services.escalation_engine import EscalationEngine
from services.sla_engine import SLAEngine
from services.ticket_service import TicketService

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
ACTOR = "test.operator"


class ServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="opsflow-test-")
        self.db_path = Path(self.tempdir.name) / "opsflow-test.db"
        self.db = Database(self.db_path)
        self.db.initialize()
        self.audit = AuditService(self.db)
        self.sla = SLAEngine(self.db, self.audit)
        self.tickets = TicketService(self.db, self.sla, self.audit)
        self.escalations = EscalationEngine(self.db, self.sla, self.audit)
        self.analytics = AnalyticsService(self.db, self.sla, self.audit)
        self.csv = CSVService(self.db, self.tickets, self.sla, self.escalations,
                              self.audit, self.analytics)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def create(self, **overrides):
        values = {
            "title": "Example incident",
            "description": "A test incident.",
            "requester": "Test Requester",
            "assignee": "Test Agent",
            "category": "Software",
            "priority": "Medium",
            "status": "Open",
            "created_at": NOW,
            "actor": ACTOR,
        }
        values.update(overrides)
        return self.tickets.create_ticket(**values)

    def audit_actions(self, ticket_id: str) -> list[str]:
        return [event.action for event in self.audit.for_ticket(ticket_id, limit=500)]
