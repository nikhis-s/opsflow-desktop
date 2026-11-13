from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from database import Database
from models import utc_now
from tests.tkroot import GUI_TESTS_SUPPORTED, get_root, unavailable_reason

try:  # Tk is not available in every CI/headless environment.
    import tkinter as tk
except Exception:  # pragma: no cover - import guard
    tk = None  # type: ignore[assignment]


@unittest.skipIf(tk is None, "tkinter is not available")
@unittest.skipIf(not GUI_TESTS_SUPPORTED, "Tk GUI tests are not run on macOS CI runners")
class UISmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        root = get_root()
        if root is None:
            self.skipTest(f"Tk display unavailable: {unavailable_reason()}")
        self.root: tk.Tk = root
        self.tempdir = tempfile.TemporaryDirectory(prefix="opsflow-ui-test-")
        self.db = Database(Path(self.tempdir.name) / "opsflow-ui.db")
        self.db.initialize()
        from ui.app import OpsFlowApp

        self.app = OpsFlowApp(self.root, self.db)
        self.root.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.shutdown()
        except Exception:
            pass
        self.tempdir.cleanup()

    def test_shell_and_all_pages_load(self) -> None:
        self.assertEqual(set(self.app.services),
                         {"db", "audit", "sla", "tickets", "escalations",
                          "analytics", "csv"})
        self.assertEqual(self.app.current_page_name, "dashboard")
        for name in ("dashboard", "tickets", "sla", "escalations", "audit", "data"):
            self.app.show_page(name)
            self.root.update_idletasks()
            self.assertIn(name, self.app.pages)
            self.assertIs(self.app.current_page, self.app.pages[name])
            self.assertEqual(self.app.current_page_name, name)
            self.assertTrue(self.app.page_title_var.get())
        self.assertIn("ticket", self.app.status_var.get().lower())

    def test_ticket_creation_and_escalation_scan_from_shell(self) -> None:
        ticket = self.app.services["tickets"].create_ticket(
            title="UI smoke incident",
            requester="Smoke Tester",
            assignee="Unassigned",
            priority="Critical",
            created_at=utc_now() - timedelta(hours=8),
        )
        self.app.show_page("tickets")
        self.root.update_idletasks()
        self.app.refresh_current()
        self.assertIn("refreshed", self.app.status_var.get().lower())

        events = self.app.run_escalation_scan(silent=False)
        self.assertTrue(events)
        self.assertIn("escalation", self.app.status_var.get().lower())
        self.assertGreaterEqual(self.db.counts()["escalations"], 1)
        self.assertIn("escalations", self.app.sidebar_counts_var.get())
        self.assertEqual(self.app.services["tickets"].get_ticket(ticket.id).id,
                         ticket.id)

    def test_status_levels_update_colour(self) -> None:
        for level in ("info", "success", "warning", "error"):
            self.app.set_status(f"{level} message", level)
            self.assertEqual(self.app.status_var.get(), f"{level} message")

    def test_mousewheel_routing_targets_the_page_scroller(self) -> None:
        from ui.components import _scroller_under

        page = self.app.pages["dashboard"]
        self.assertIs(_scroller_under(page.scroller.content), page.scroller)
        inner_text = tk.Text(page.scroller.content)
        try:
            self.assertIsNone(_scroller_under(inner_text))
        finally:
            inner_text.destroy()


if __name__ == "__main__":
    unittest.main()
