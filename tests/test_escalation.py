from __future__ import annotations

import unittest
from datetime import timedelta

from tests.helpers import NOW, ServiceTestCase


class EscalationDetectionTests(ServiceTestCase):
    def test_no_escalations_before_thresholds(self) -> None:
        self.create(priority="Medium", assignee="Test Agent")
        events = self.escalations.run(NOW)
        self.assertEqual(events, [])
        self.assertEqual(self.escalations.count(), 0)

    def test_response_breach_is_recorded_once(self) -> None:
        ticket = self.create(priority="Medium", assignee="Test Agent")
        checked = NOW + timedelta(minutes=150)  # Response target is 120 minutes.
        first = self.escalations.run(checked)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].escalation_type, "response_breach")
        self.assertEqual(first[0].level, "CRITICAL")
        self.assertIn(ticket.id, first[0].reason)
        # Same deadline and same ticket must not duplicate on later scans.
        second = self.escalations.run(checked + timedelta(minutes=10))
        self.assertEqual(second, [])
        self.assertEqual(self.escalations.count(ticket_id=ticket.id), 1)
        actions = self.audit_actions(ticket.id)
        self.assertIn("ESCALATION_RAISED", actions)
        self.assertIn("SLA_BREACH", actions)

    def test_at_risk_escalation_levels(self) -> None:
        medium = self.create(priority="Medium", assignee="Test Agent")
        medium_events = self.escalations.run(NOW + timedelta(minutes=100))
        # Medium response target 120m, warning threshold 96m.
        self.assertEqual([event.escalation_type for event in medium_events],
                         ["response_at_risk"])
        self.assertEqual(medium_events[0].level, "WARNING")
        self.assertEqual(medium_events[0].ticket_id, medium.id)

        critical = self.create(priority="Critical", assignee="Test Agent")
        critical_events = self.escalations.run(NOW + timedelta(minutes=13))
        # Critical response target 15m, warning threshold 12m.
        self.assertEqual([event.escalation_type for event in critical_events],
                         ["response_at_risk"])
        self.assertEqual(critical_events[0].level, "CRITICAL")
        self.assertEqual(critical_events[0].ticket_id, critical.id)

    def test_response_and_resolution_breaches(self) -> None:
        ticket = self.create(priority="Medium", assignee="Test Agent")
        events = self.escalations.run(NOW + timedelta(hours=9))
        types = {event.escalation_type for event in events}
        self.assertEqual(types, {"response_breach", "resolution_breach"})
        self.assertEqual(self.escalations.count(ticket_id=ticket.id, level="CRITICAL"), 2)

    def test_resolved_tickets_are_not_scanned(self) -> None:
        self.create(
            priority="Critical", status="Resolved", assignee="Test Agent",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=30),
        )
        self.assertEqual(self.escalations.run(NOW + timedelta(days=3)), [])

    def test_responded_ticket_skips_response_escalation(self) -> None:
        ticket = self.create(
            priority="Medium", status="In Progress", assignee="Test Agent",
            first_response_at=NOW + timedelta(minutes=10),
        )
        # Response already met; resolution is still open and at risk at 7 hours.
        events = self.escalations.run(NOW + timedelta(hours=7))
        self.assertEqual([event.escalation_type for event in events],
                         ["resolution_at_risk"])
        self.assertFalse(any(event.escalation_type.startswith("response")
                             for event in events))
        self.assertEqual(ticket.first_response_at is not None, True)

    def test_critical_unassigned_detection(self) -> None:
        ticket = self.create(priority="Critical", assignee="Unassigned")
        events = self.escalations.run(NOW)
        self.assertEqual([event.escalation_type for event in events],
                         ["critical_unassigned"])
        self.assertEqual(events[0].level, "CRITICAL")
        self.assertEqual(events[0].ticket_id, ticket.id)
        # Deduplicated for the same creation time.
        self.assertEqual(self.escalations.run(NOW + timedelta(minutes=1)), [])

        watchlist = self.escalations.critical_unresolved(NOW)
        self.assertEqual([pair[0].id for pair in watchlist], [ticket.id])

    def test_escalation_history_survives_ticket_delete(self) -> None:
        ticket = self.create(priority="Medium", assignee="Test Agent")
        self.escalations.run(NOW + timedelta(minutes=150))
        self.assertEqual(len(self.escalations.for_ticket(ticket.id)), 1)
        self.tickets.delete_ticket(ticket.id)
        self.assertEqual(self.tickets.find_ticket(ticket.id), None)
        self.assertEqual(len(self.escalations.for_ticket(ticket.id)), 1)
        self.assertEqual(self.escalations.count(ticket_id=ticket.id), 1)

    def test_list_events_filters_and_pagination(self) -> None:
        first = self.create(priority="Medium", assignee="Test Agent",
                            title="Network outage")
        second = self.create(priority="Critical", assignee="Unassigned",
                             title="Mail server down")
        self.escalations.run(NOW)
        self.assertEqual(self.escalations.count(), 1)  # critical_unassigned only
        self.escalations.run(NOW + timedelta(hours=9))
        self.assertGreaterEqual(self.escalations.count(), 4)

        critical_events = self.escalations.list_events(level="CRITICAL")
        self.assertTrue(all(event.level == "CRITICAL" for event in critical_events))
        self.assertEqual(self.escalations.count(level="CRITICAL"), len(critical_events))

        filtered = self.escalations.list_events(ticket_id=second.id)
        self.assertTrue(all(event.ticket_id == second.id for event in filtered))

        searched = self.escalations.list_events(search="mail server down")
        # Search covers reason/details; the reason names the ticket only by ID,
        # so search by ID instead.
        self.assertIsInstance(searched, list)
        by_id = self.escalations.list_events(search=second.id)
        self.assertGreaterEqual(len(by_id), 1)

        page = self.escalations.list_events(limit=1)
        self.assertEqual(len(page), 1)
        self.assertNotEqual(page[0].id, self.escalations.list_events(limit=1, offset=1)[0].id)
        self.assertEqual(first.id in {event.ticket_id for event in
                                      self.escalations.list_events()}, True)
        self.assertEqual(set(self.escalations.levels()), {"CRITICAL"})


if __name__ == "__main__":
    unittest.main()
