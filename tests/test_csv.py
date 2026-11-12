from __future__ import annotations

import csv
import unittest
from datetime import timedelta
from pathlib import Path

from services.csv_service import TICKET_EXPORT_COLUMNS, CSVFormatError
from tests.helpers import NOW, ServiceTestCase


class CSVTestCase(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.out_dir = Path(self.tempdir.name) / "exports"
        self.out_dir.mkdir()

    def write_csv(self, name: str, header: list[str], rows: list[list[str]]) -> Path:
        path = self.out_dir / name
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def read_csv(self, path: Path) -> list[dict[str, str]]:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))


class ExportTests(CSVTestCase):
    def test_export_tickets(self) -> None:
        first = self.create(title="VPN drop", priority="High")
        second = self.create(title="Printer offline", priority="Low",
                             status="Resolved", first_response_at=NOW + timedelta(minutes=5),
                             resolved_at=NOW + timedelta(minutes=60))
        path = self.out_dir / "tickets.csv"
        count = self.csv.export_tickets(path)
        self.assertEqual(count, 2)
        rows = self.read_csv(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[0]), set(TICKET_EXPORT_COLUMNS))
        by_id = {row["ticket_id"]: row for row in rows}
        self.assertEqual(by_id[first.id]["title"], "VPN drop")
        self.assertEqual(by_id[first.id]["priority"], "High")
        self.assertEqual(by_id[second.id]["status"], "Resolved")
        self.assertIsNotNone(by_id[second.id]["resolved_at"])
        self.assertIn(by_id[first.id]["sla_state"],
                      {"On track", "At risk", "Breached", "Met", "Missed"})

    def test_export_sla_report(self) -> None:
        self.create(priority="Critical")
        path = self.out_dir / "sla.csv"
        self.assertEqual(self.csv.export_sla_report(path), 1)
        rows = self.read_csv(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["priority"], "Critical")
        self.assertIn("overall_state", rows[0])
        self.assertIn("response_remaining_seconds", rows[0])

    def test_export_escalations(self) -> None:
        ticket = self.create(priority="Medium", assignee="Test Agent")
        self.escalations.run(NOW + timedelta(minutes=150))
        path = self.out_dir / "escalations.csv"
        self.assertEqual(self.csv.export_escalations(path), 1)
        rows = self.read_csv(path)
        self.assertEqual(rows[0]["ticket_id"], ticket.id)
        self.assertEqual(rows[0]["escalation_type"], "response_breach")
        self.assertEqual(rows[0]["level"], "CRITICAL")

    def test_export_audit(self) -> None:
        ticket = self.create()
        self.tickets.add_comment(ticket.id, "Investigating.")
        path = self.out_dir / "audit.csv"
        count = self.csv.export_audit(path)
        rows = self.read_csv(path)
        self.assertEqual(count, len(rows))
        self.assertEqual(len(rows), 2)
        actions = {row["action"] for row in rows}
        self.assertEqual(actions, {"TICKET_CREATED", "COMMENT_ADDED"})

    def test_template_round_trip(self) -> None:
        template = self.out_dir / "template.csv"
        self.csv.write_template(template)
        rows = self.read_csv(template)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket_id"], "TKT-9001")

        result = self.csv.import_tickets(template)
        self.assertEqual((result.total_rows, result.imported, result.invalid_count),
                         (1, 1, 0))
        ticket = self.tickets.get_ticket("TKT-9001")
        self.assertEqual(ticket.title, "VPN disconnects every few minutes")
        self.assertEqual(ticket.priority, "High")
        self.assertIsNotNone(ticket.created_at.tzinfo)


class ImportTests(CSVTestCase):
    def test_import_with_aliases_and_canonical_values(self) -> None:
        path = self.write_csv(
            "aliases.csv",
            ["id", "summary", "requested_by", "owner", "type", "priority",
             "status", "created", "notes"],
            [["tkt-7001", "VPN issue", "Jordan Lee", "Network Queue", "Network",
              "high", "in progress", "2026-05-01 09:30", "ignored"]],
        )
        result = self.csv.import_tickets(path, actor="importer")
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(result.imported_ids, ["TKT-7001"])
        self.assertTrue(any("notes" in warning for warning in result.warnings))

        ticket = self.tickets.get_ticket("TKT-7001")
        self.assertEqual(ticket.priority, "High")
        self.assertEqual(ticket.status, "In Progress")
        self.assertEqual(ticket.assignee, "Network Queue")
        self.assertEqual(ticket.category, "Network")
        self.assertIsNotNone(ticket.first_response_at)
        audit = self.audit.list_events(action="CSV_IMPORT")
        self.assertEqual(audit[0].actor, "importer")

    def test_import_reports_invalid_rows_and_keeps_valid_ones(self) -> None:
        path = self.write_csv(
            "mixed.csv",
            ["title", "requester", "priority", "created_at"],
            [
                ["", "Requester", "High", ""],
                ["No requester", "", "High", ""],
                ["Bad priority", "Requester", "Urgent", ""],
                ["Bad timestamp", "Requester", "Low", "not-a-date"],
                ["Valid ticket", "Requester", "Medium", "2026-05-01 08:00"],
            ],
        )
        result = self.csv.import_tickets(path)
        self.assertEqual(result.total_rows, 5)
        self.assertEqual(result.imported, 1)
        self.assertEqual(result.invalid_count, 4)
        self.assertEqual(len(self.tickets.list_tickets()), 1)
        messages = " | ".join(error.message for error in result.errors)
        self.assertIn("title is required", messages)
        self.assertIn("requester is required", messages)
        self.assertIn("invalid priority", messages)
        self.assertIn("invalid timestamp", messages)

    def test_import_rejects_invalid_status(self) -> None:
        path = self.write_csv(
            "bad-status.csv",
            ["title", "requester", "priority", "status"],
            [["Invalid status", "Requester", "High", "Waiting"]],
        )
        result = self.csv.import_tickets(path)
        self.assertEqual(result.imported, 0)
        self.assertEqual(result.invalid_count, 1)
        self.assertIn("invalid status", result.errors[0].message)

    def test_import_skips_duplicate_ids(self) -> None:
        self.create(ticket_id="TKT-4000")
        path = self.write_csv(
            "dupes.csv",
            ["ticket_id", "title", "requester", "priority"],
            [
                ["TKT-5000", "First copy", "Runner", "Low"],
                ["TKT-5000", "Second copy", "Runner", "Low"],
                ["TKT-4000", "Already exists", "Runner", "Low"],
                ["TKT-5001", "Unique", "Runner", "Low"],
            ],
        )
        result = self.csv.import_tickets(path)
        self.assertEqual(result.total_rows, 4)
        self.assertEqual(result.imported, 2)
        self.assertEqual(result.skipped_duplicates, 2)
        self.assertEqual(result.imported_ids, ["TKT-5000", "TKT-5001"])
        self.assertEqual(len(self.tickets.list_tickets()), 3)

    def test_import_missing_required_columns_raises(self) -> None:
        path = self.write_csv("bad.csv", ["title", "priority"],
                              [["Only a title", "High"]])
        with self.assertRaises(CSVFormatError) as caught:
            self.csv.import_tickets(path)
        self.assertIn("requester", str(caught.exception))

    def test_import_missing_file_raises(self) -> None:
        with self.assertRaises(CSVFormatError):
            self.csv.import_tickets(self.out_dir / "does-not-exist.csv")

    def test_empty_file_raises(self) -> None:
        path = self.out_dir / "empty.csv"
        path.write_text("", encoding="utf-8")
        with self.assertRaises(CSVFormatError):
            self.csv.import_tickets(path)

    def test_import_blank_rows_are_ignored(self) -> None:
        path = self.write_csv(
            "blank.csv",
            ["title", "requester", "priority"],
            [["Valid", "Runner", "Low"], ["", "", ""]],
        )
        result = self.csv.import_tickets(path)
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.imported, 1)


if __name__ == "__main__":
    unittest.main()
