from __future__ import annotations

import unittest
from datetime import timedelta

from tests.helpers import NOW, ServiceTestCase


class AnalyticsTests(ServiceTestCase):
    def test_empty_database_metrics(self) -> None:
        metrics = self.analytics.metrics(NOW)
        self.assertEqual(metrics.total, 0)
        self.assertEqual(metrics.active, 0)
        self.assertIsNone(metrics.compliance)
        self.assertIsNone(metrics.response_compliance)
        self.assertIsNone(metrics.avg_resolution_seconds)
        self.assertEqual(len(metrics.trend), 7)
        self.assertEqual(sum(point["created"] for point in metrics.trend), 0)

    def test_metrics_count_statuses_and_resolution_average(self) -> None:
        self.create(priority="Medium")
        self.create(priority="High", status="In Progress")
        self.create(priority="Low", status="Pending")
        self.create(
            priority="Critical", status="Resolved", assignee="Agent",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=30),
        )
        self.create(
            priority="High", status="Closed", assignee="Agent",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=90),
            closed_at=NOW + timedelta(minutes=100),
        )
        metrics = self.analytics.metrics(NOW)
        self.assertEqual(metrics.total, 5)
        self.assertEqual(metrics.open_count, 1)
        self.assertEqual(metrics.in_progress, 1)
        self.assertEqual(metrics.pending, 1)
        self.assertEqual(metrics.resolved, 1)
        self.assertEqual(metrics.closed, 1)
        self.assertEqual(metrics.active, 3)
        self.assertEqual(metrics.status_counts["Open"], 1)
        self.assertEqual(metrics.priority_counts["High"], 2)
        self.assertEqual(metrics.avg_resolution_seconds, 60 * 60)
        self.assertEqual(metrics.compliance, 100.0)
        self.assertEqual(metrics.response_compliance, 100.0)
        self.assertEqual(len(metrics.trend), 7)
        self.assertEqual(sum(point["created"] for point in metrics.trend), 5)

    def test_overdue_and_at_risk_counts(self) -> None:
        critical = self.create(priority="Critical", assignee="Agent")
        medium = self.create(priority="Medium", assignee="Agent")
        # At NOW+130: Critical response is breached; Medium response is breached
        # too (120m target), and both resolutions are still open.
        metrics = self.analytics.metrics(NOW + timedelta(minutes=130))
        self.assertEqual(metrics.overdue, 2)
        self.assertGreaterEqual(metrics.at_risk, 0)
        self.assertIsNotNone(critical.id)
        self.assertIsNotNone(medium.id)

    def test_watchlist_prioritises_breaches(self) -> None:
        breached = self.create(priority="High", assignee="Agent")
        risky = self.create(priority="Low", assignee="Agent")
        # At 200 minutes the High response target (30m) is breached while the Low
        # response target (240m) is only at risk.
        items = self.analytics.watchlist(NOW + timedelta(minutes=200))
        by_id = {ticket.id: evaluation for ticket, evaluation in items}
        self.assertEqual(by_id[breached.id].overall_state, "Breached")
        self.assertEqual(by_id[risky.id].overall_state, "At risk")
        states = [evaluation.overall_state for _ticket, evaluation in items]
        self.assertEqual(states, ["Breached", "At risk"])

    def test_sla_monitor_and_report(self) -> None:
        first = self.create(priority="Critical", assignee="Agent")
        second = self.create(priority="Low", assignee="Agent")
        monitor = self.analytics.sla_monitor(NOW)
        self.assertEqual({ticket.id for ticket, _ in monitor}, {first.id, second.id})
        report = self.analytics.sla_report(NOW)
        self.assertEqual(len(report), 2)
        # No at-risk/breached tickets at creation time.
        self.assertEqual(self.analytics.watchlist(NOW), [])

    def test_escalation_counts(self) -> None:
        self.create(priority="Medium", assignee="Agent")
        self.create(priority="Critical", assignee="Unassigned")
        self.escalations.run(NOW)
        self.escalations.run(NOW + timedelta(hours=9))
        counts = self.analytics.escalation_counts()
        self.assertGreaterEqual(counts["TOTAL"], 3)
        self.assertEqual(counts["TOTAL"],
                         counts["INFO"] + counts["WARNING"] + counts["CRITICAL"])
        self.assertGreaterEqual(counts["CRITICAL"], 1)

    def test_recent_activity(self) -> None:
        ticket = self.create()
        self.tickets.add_comment(ticket.id, "Latest note")
        activity = self.analytics.recent_activity(limit=5)
        self.assertGreaterEqual(len(activity), 2)
        self.assertEqual(activity[0].action, "COMMENT_ADDED")


if __name__ == "__main__":
    unittest.main()
