from __future__ import annotations

import unittest
from datetime import timedelta

from services.sla_engine import (
    AT_RISK, BREACHED, MET, MISSED, ON_TRACK, calculate_deadlines,
)
from tests.helpers import NOW, ServiceTestCase


class DeadlineCalculationTests(ServiceTestCase):
    def test_calculate_deadlines(self) -> None:
        response, resolution = calculate_deadlines(NOW, 15, 120)
        self.assertEqual(response - NOW, timedelta(minutes=15))
        self.assertEqual(resolution - NOW, timedelta(minutes=120))

    def test_calculate_deadlines_rejects_non_positive_targets(self) -> None:
        with self.assertRaises(ValueError):
            calculate_deadlines(NOW, 0, 120)
        with self.assertRaises(ValueError):
            calculate_deadlines(NOW, 15, -1)

    def test_default_policies_are_seeded(self) -> None:
        policies = self.sla.get_policies()
        self.assertEqual(set(policies), {"Critical", "High", "Medium", "Low"})
        critical = policies["Critical"]
        self.assertEqual(critical.response_minutes, 15)
        self.assertEqual(critical.resolution_minutes, 120)
        self.assertEqual(critical.at_risk_percent, 80)

    def test_deadlines_for_uses_policy(self) -> None:
        response, resolution = self.sla.deadlines_for("High", NOW)
        self.assertEqual(response - NOW, timedelta(minutes=30))
        self.assertEqual(resolution - NOW, timedelta(minutes=240))

    def test_deadlines_for_unknown_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.sla.deadlines_for("Urgent", NOW)


class EvaluationTests(ServiceTestCase):
    def _critical(self, **overrides):
        return self.create(
            priority="Critical",
            assignee="Agent",
            first_response_at=overrides.pop("first_response_at", None),
            resolved_at=overrides.pop("resolved_at", None),
            status=overrides.pop("status", "Open"),
            **overrides,
        )

    def test_on_track_evaluation(self) -> None:
        ticket = self._critical()
        evaluation = self.sla.evaluate(ticket, NOW)
        self.assertEqual(evaluation.response.state, ON_TRACK)
        self.assertEqual(evaluation.resolution.state, ON_TRACK)
        self.assertEqual(evaluation.overall_state, ON_TRACK)
        self.assertTrue(evaluation.is_compliant)
        self.assertFalse(evaluation.is_overdue)

    def test_at_risk_threshold(self) -> None:
        ticket = self._critical()
        # Critical response target is 15 minutes and the warning threshold is 80% (12m).
        evaluation = self.sla.evaluate(ticket, NOW + timedelta(minutes=13))
        self.assertEqual(evaluation.response.state, AT_RISK)
        self.assertEqual(evaluation.overall_state, AT_RISK)
        self.assertTrue(evaluation.is_at_risk)
        self.assertFalse(evaluation.is_overdue)

    def test_breached_after_deadline(self) -> None:
        ticket = self._critical()
        evaluation = self.sla.evaluate(ticket, NOW + timedelta(minutes=16))
        self.assertEqual(evaluation.response.state, BREACHED)
        self.assertTrue(evaluation.response.is_breached)
        self.assertTrue(evaluation.is_overdue)
        self.assertEqual(evaluation.overall_state, BREACHED)

    def test_met_and_missed_resolution(self) -> None:
        met = self.create(
            priority="Critical",
            status="Resolved",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=30),
        )
        met_evaluation = self.sla.evaluate(met, NOW + timedelta(hours=1))
        self.assertEqual(met_evaluation.response.state, MET)
        self.assertEqual(met_evaluation.resolution.state, MET)
        self.assertEqual(met_evaluation.overall_state, MET)

        missed = self.create(
            priority="Critical",
            status="Resolved",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=200),
        )
        missed_evaluation = self.sla.evaluate(missed, NOW + timedelta(hours=4))
        self.assertEqual(missed_evaluation.resolution.state, MISSED)
        self.assertEqual(missed_evaluation.overall_state, MISSED)
        self.assertTrue(missed_evaluation.resolution.is_failed)

    def test_overdue_and_at_risk_helpers_ignore_closed_tickets(self) -> None:
        ticket = self.create(
            priority="Critical", status="Closed", assignee="Agent",
            first_response_at=NOW + timedelta(minutes=1),
            resolved_at=NOW + timedelta(minutes=2),
        )
        self.assertFalse(self.sla.is_overdue(ticket, NOW + timedelta(days=5)))
        self.assertFalse(self.sla.is_at_risk(ticket, NOW + timedelta(days=5)))

    def test_compliance_percentages(self) -> None:
        self.create(
            priority="Critical", status="Resolved", assignee="Agent",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=30),
        )
        self.create(
            priority="Critical", status="Resolved", assignee="Agent",
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=200),
        )
        resolution, response, completed, responded = self.sla.compliance(
            self.analytics.all_tickets()
        )
        self.assertEqual(completed, 2)
        self.assertEqual(responded, 2)
        self.assertEqual(response, 100.0)
        self.assertAlmostEqual(resolution, 50.0)

    def test_report_includes_every_ticket(self) -> None:
        first = self.create(priority="Low")
        second = self.create(priority="High", status="Resolved",
                             first_response_at=NOW + timedelta(minutes=5),
                             resolved_at=NOW + timedelta(minutes=60))
        rows = self.sla.report([first, second], NOW)
        self.assertEqual(len(rows), 2)
        by_id = {row.ticket.id: row for row in rows}
        self.assertIn(by_id[first.id].overall_state, (ON_TRACK, AT_RISK, BREACHED))
        self.assertIsNotNone(by_id[second.id].resolution_remaining)


class PolicyManagementTests(ServiceTestCase):
    def test_update_policy_persists_and_audits(self) -> None:
        self.sla.update_policies({"Medium": (10, 60, 75)}, actor="tester")
        policy = self.sla.get_policy("Medium")
        self.assertEqual(policy.response_minutes, 10)
        self.assertEqual(policy.resolution_minutes, 60)
        self.assertEqual(policy.at_risk_percent, 75)
        self.assertEqual(policy.updated_at.tzinfo is not None, True)
        events = self.audit.list_events(action="SLA_POLICY_UPDATED")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].actor, "tester")
        self.assertIsNone(events[0].ticket_id)

    def test_update_policy_accepts_mapping_values(self) -> None:
        self.sla.update_policies(
            {"Low": {"response_minutes": 30, "resolution_minutes": 120,
                     "at_risk_percent": 50}}
        )
        policy = self.sla.get_policy("Low")
        self.assertEqual((policy.response_minutes, policy.resolution_minutes,
                          policy.at_risk_percent), (30, 120, 50))

    def test_update_policy_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.sla.update_policies({"Urgent": (10, 20, 80)})
        with self.assertRaises(ValueError):
            self.sla.update_policies({"Medium": (0, 20, 80)})
        with self.assertRaises(ValueError):
            self.sla.update_policies({"Medium": (30, 20, 80)})
        with self.assertRaises(ValueError):
            self.sla.update_policies({"Medium": (10, 20, 0)})
        with self.assertRaises(ValueError):
            self.sla.update_policies({"Medium": (10, 20, 100)})
        # Failed updates must leave defaults untouched.
        self.assertEqual(self.sla.get_policy("Medium").response_minutes, 120)

    def test_reset_defaults(self) -> None:
        self.sla.update_policies({"Medium": (10, 60, 75)})
        self.sla.reset_defaults(actor="tester")
        policy = self.sla.get_policy("Medium")
        self.assertEqual((policy.response_minutes, policy.resolution_minutes,
                          policy.at_risk_percent), (120, 480, 80))

    def test_recalculate_active_deadlines(self) -> None:
        active = self.create(priority="Medium", created_at=NOW)
        done = self.create(
            priority="Medium", status="Resolved", created_at=NOW,
            first_response_at=NOW + timedelta(minutes=5),
            resolved_at=NOW + timedelta(minutes=30),
        )
        self.sla.update_policies({"Medium": (10, 60, 75)})
        changed = self.tickets.recalculate_active_deadlines(actor="tester")
        self.assertEqual(changed, 1)
        refreshed = self.tickets.get_ticket(active.id)
        self.assertEqual(refreshed.response_deadline - refreshed.created_at,
                         timedelta(minutes=10))
        self.assertEqual(refreshed.resolution_deadline - refreshed.created_at,
                         timedelta(minutes=60))
        untouched = self.tickets.get_ticket(done.id)
        self.assertEqual(untouched.resolution_deadline - untouched.created_at,
                         timedelta(minutes=480))
        self.assertIn("SLA_RECALCULATED", self.audit_actions(active.id))
        self.assertNotIn("SLA_RECALCULATED", self.audit_actions(done.id))
        # A second pass is a no-op.
        self.assertEqual(self.tickets.recalculate_active_deadlines(), 0)


if __name__ == "__main__":
    unittest.main()
