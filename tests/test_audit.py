from __future__ import annotations

import unittest
from datetime import timedelta

from tests.helpers import NOW, ServiceTestCase


class AuditTrailTests(ServiceTestCase):
    def test_log_and_record_append_events(self) -> None:
        ticket = self.create(title="Audit target")
        self.audit.log(ticket.id, "MANUAL_NOTE", "Checked by operator", "auditor")
        events = self.audit.for_ticket(ticket.id)
        self.assertEqual([event.action for event in events],
                         ["MANUAL_NOTE", "TICKET_CREATED"])
        self.assertEqual(events[0].actor, "auditor")
        self.assertTrue(all(event.created_at.tzinfo is not None for event in events))

    def test_default_actor_and_missing_details(self) -> None:
        event_id = None
        with self.db.transaction() as conn:
            event_id = self.audit.record(conn, None, "SYSTEM_EVENT")
        self.assertIsInstance(event_id, int)
        events = self.audit.list_events(action="SYSTEM_EVENT")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].details, "")
        self.assertTrue(events[0].actor)
        self.assertIsNone(events[0].ticket_id)

    def test_filters_search_action_ticket_and_dates(self) -> None:
        first = self.create(title="Network outage")
        second = self.create(title="Billing issue")
        self.tickets.assign_ticket(second.id, "Alex Chen", actor="router")

        self.assertEqual(len(self.audit.list_events(ticket_id=first.id)),
                         len(self.audit.for_ticket(first.id)))
        assigned = self.audit.list_events(action="REASSIGNED")
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0].ticket_id, second.id)

        searched = self.audit.list_events(search="alex chen")
        self.assertTrue(searched)
        self.assertTrue(all("alex chen" in (
            f"{event.ticket_id} {event.action} {event.details} {event.actor}".lower()
        ) for event in searched))

        recent = self.audit.list_events(date_from=NOW - timedelta(days=1))
        old = self.audit.list_events(date_to=NOW - timedelta(days=30))
        self.assertGreater(len(recent), 0)
        self.assertEqual(old, [])
        self.assertEqual(self.audit.count(ticket_id=second.id),
                         len(self.audit.for_ticket(second.id)))

    def test_actions_recent_and_pagination(self) -> None:
        ticket = self.create()
        self.tickets.change_status(ticket.id, "In Progress")
        self.tickets.add_comment(ticket.id, "Working on it")
        actions = self.audit.actions()
        self.assertIn("TICKET_CREATED", actions)
        self.assertIn("STATUS_CHANGED", actions)
        self.assertIn("COMMENT_ADDED", actions)

        recent = self.audit.recent(limit=2)
        self.assertEqual(len(recent), 2)
        self.assertGreaterEqual(recent[0].id, recent[1].id)

        page_one = self.audit.list_events(limit=2, offset=0)
        page_two = self.audit.list_events(limit=2, offset=2)
        self.assertEqual(len(page_one), 2)
        self.assertTrue(page_two)
        self.assertTrue(set(event.id for event in page_one)
                        .isdisjoint(event.id for event in page_two))

    def test_audit_survives_ticket_delete(self) -> None:
        ticket = self.create()
        self.audit.log(ticket.id, "INVESTIGATION", "Cross-checked logs", "auditor")
        self.tickets.delete_ticket(ticket.id)
        actions = self.audit_actions(ticket.id)
        self.assertIn("TICKET_DELETED", actions)
        self.assertIn("INVESTIGATION", actions)
        self.assertIn("TICKET_CREATED", actions)


if __name__ == "__main__":
    unittest.main()
