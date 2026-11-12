from __future__ import annotations

import unittest
from datetime import timedelta

from services.ticket_service import DuplicateTicketError, NotFoundError, ValidationError
from tests.helpers import NOW, ServiceTestCase


class TicketCrudTests(ServiceTestCase):
    def test_create_ticket_generates_id_and_sla_deadlines(self) -> None:
        ticket = self.create(priority="Critical")
        self.assertTrue(ticket.id.startswith("TKT-"))
        self.assertEqual(ticket.status, "Open")
        self.assertEqual(ticket.response_deadline - ticket.created_at,
                         timedelta(minutes=15))
        self.assertEqual(ticket.resolution_deadline - ticket.created_at,
                         timedelta(minutes=120))
        self.assertIn("TICKET_CREATED", self.audit_actions(ticket.id))
        self.assertEqual(len(self.audit.for_ticket(ticket.id)), 1)

    def test_update_assign_status_priority_and_comment(self) -> None:
        ticket = self.create(priority="High")
        updated = self.tickets.update_ticket(
            ticket.id,
            {
                "title": "Updated incident title",
                "description": "More detail",
                "assignee": "Alex Chen",
                "priority": "Critical",
                "status": "In Progress",
            },
            actor="editor",
        )
        self.assertEqual(updated.title, "Updated incident title")
        self.assertEqual(updated.assignee, "Alex Chen")
        self.assertEqual(updated.priority, "Critical")
        self.assertEqual(updated.status, "In Progress")
        self.assertIsNotNone(updated.first_response_at)
        self.assertEqual(updated.response_deadline - updated.created_at,
                         timedelta(minutes=15))
        self.assertEqual(updated.resolution_deadline - updated.created_at,
                         timedelta(minutes=120))
        actions = self.audit_actions(ticket.id)
        for expected in ("TITLE_CHANGED", "DESCRIPTION_CHANGED", "REASSIGNED",
                         "PRIORITY_CHANGED", "STATUS_CHANGED", "SLA_RECALCULATED"):
            self.assertIn(expected, actions)

        comment = self.tickets.add_comment(
            ticket.id, "Investigating the authentication logs.", author="editor"
        )
        self.assertEqual(comment.author, "editor")
        self.assertEqual(comment.ticket_id, ticket.id)
        self.assertIn("COMMENT_ADDED", self.audit_actions(ticket.id))
        self.assertGreaterEqual(len(self.tickets.get_comments(ticket.id)), 1)

    def test_resolution_and_reopen_stamps(self) -> None:
        ticket = self.create(priority="Medium")
        resolved = self.tickets.update_ticket(ticket.id, {"status": "Resolved"})
        self.assertIsNotNone(resolved.resolved_at)
        self.assertIsNotNone(resolved.first_response_at)
        reopened = self.tickets.update_ticket(ticket.id, {"status": "In Progress"})
        self.assertIsNone(reopened.resolved_at)
        self.assertIsNone(reopened.closed_at)
        self.assertIsNotNone(reopened.first_response_at)
        statuses = [
            event.details for event in self.audit.for_ticket(ticket.id)
            if event.action == "STATUS_CHANGED"
        ]
        self.assertIn("Resolved → In Progress", statuses)

    def test_change_status_with_note_creates_comment(self) -> None:
        ticket = self.create()
        updated = self.tickets.change_status(
            ticket.id, "Pending", note="Waiting on the requester.", actor="agent"
        )
        self.assertEqual(updated.status, "Pending")
        comments = self.tickets.get_comments(ticket.id)
        self.assertEqual(comments[-1].body, "Waiting on the requester.")
        self.assertEqual(comments[-1].author, "agent")

    def test_search_filter_and_sort(self) -> None:
        first = self.create(
            title="VPN authentication failure", requester="Jordan Lee",
            assignee="Network Queue", priority="Low", created_at=NOW - timedelta(hours=3),
        )
        second = self.create(
            title="Laptop battery swelling", requester="Priya Sharma",
            assignee="Hardware Queue", priority="Critical",
            created_at=NOW - timedelta(hours=2),
        )
        third = self.create(
            title="Billing portal access", requester="Sam Ortiz",
            assignee="Applications", priority="High", status="In Progress",
            created_at=NOW - timedelta(hours=1),
        )

        self.assertEqual([t.id for t in self.tickets.list_tickets(search="VPN")], [first.id])
        self.assertEqual([t.id for t in self.tickets.list_tickets(search="Priya")], [second.id])
        self.assertEqual([t.id for t in self.tickets.list_tickets(search=third.id)], [third.id])
        self.assertEqual(
            [t.id for t in self.tickets.list_tickets(priority="Critical")], [second.id]
        )
        self.assertEqual(
            [t.id for t in self.tickets.list_tickets(status="In Progress")], [third.id]
        )
        self.assertEqual(
            [t.id for t in self.tickets.list_tickets(assignee="Network Queue")], [first.id]
        )
        priority_sorted = self.tickets.list_tickets(sort="priority", descending=False)
        self.assertEqual(priority_sorted[0].priority, "Critical")
        oldest = self.tickets.list_tickets(sort="created_at", descending=False)
        self.assertEqual(oldest[0].id, first.id)
        deadline_sorted = self.tickets.list_tickets(
            sort="resolution_deadline", descending=False
        )
        self.assertEqual(deadline_sorted[0].id, second.id)

    def test_delete_removes_comments_but_preserves_audit(self) -> None:
        ticket = self.create()
        self.tickets.add_comment(ticket.id, "A note that should cascade.")
        self.tickets.delete_ticket(ticket.id)
        with self.assertRaises(NotFoundError):
            self.tickets.get_ticket(ticket.id)
        with self.db.read() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM ticket_comments WHERE ticket_id = ?", (ticket.id,)
            ).fetchone()[0]
        self.assertEqual(remaining, 0)
        self.assertIn("TICKET_DELETED", self.audit_actions(ticket.id))

    def test_validation_and_duplicate_ids(self) -> None:
        with self.assertRaises(ValidationError):
            self.create(title="")
        with self.assertRaises(ValidationError):
            self.create(priority="Urgent")
        with self.assertRaises(ValidationError):
            self.create(status="Waiting")
        ticket = self.create()
        with self.assertRaises(DuplicateTicketError):
            self.create(ticket_id=ticket.id)
        with self.assertRaises(ValidationError):
            self.create(ticket_id="bad id with spaces")
        with self.assertRaises(ValidationError):
            self.create(
                response_deadline=NOW + timedelta(hours=5),
                resolution_deadline=NOW + timedelta(hours=1),
            )

    def test_comment_validation(self) -> None:
        ticket = self.create()
        with self.assertRaises(ValidationError):
            self.tickets.add_comment(ticket.id, "   ")

    def test_persistence_across_service_instances(self) -> None:
        ticket = self.create(title="Persistent ticket")
        from database import Database
        from services.audit_service import AuditService
        from services.sla_engine import SLAEngine
        from services.ticket_service import TicketService

        fresh_db = Database(self.db_path)
        fresh_db.initialize()
        audit = AuditService(fresh_db)
        sla = SLAEngine(fresh_db, audit)
        tickets = TicketService(fresh_db, sla, audit)
        loaded = tickets.get_ticket(ticket.id)
        self.assertEqual(loaded.title, "Persistent ticket")
        self.assertEqual(len(audit.for_ticket(ticket.id)), 1)


if __name__ == "__main__":
    unittest.main()
