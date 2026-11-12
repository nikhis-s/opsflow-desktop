"""Regression tests for every modal dialog in the UI layer.

Dialogs are built lazily and were historically untested, which allowed a
name-shadowing bug in the centering helper to break every dialog at runtime.
These tests construct each dialog for real and assert that it opens, lays
itself out and closes again.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database import Database
from models import ImportResult, ImportRowError
from tests.tkroot import get_root, unavailable_reason

try:  # Tk is not available in every CI/headless environment.
    import tkinter as tk
except Exception:  # pragma: no cover - import guard
    tk = None  # type: ignore[assignment]


@unittest.skipIf(tk is None, "tkinter is not available")
class DialogTests(unittest.TestCase):
    def setUp(self) -> None:
        root = get_root()
        if root is None:
            self.skipTest(f"Tk display unavailable: {unavailable_reason()}")
        self.root: tk.Tk = root
        self.tempdir = tempfile.TemporaryDirectory(prefix="opsflow-dialog-test-")
        self.db = Database(Path(self.tempdir.name) / "opsflow-dialog.db")
        self.db.initialize()
        from ui.app import OpsFlowApp

        self.app = OpsFlowApp(self.root, self.db)
        self.root.update_idletasks()
        self.ticket = self.app.services["tickets"].create_ticket(
            title="Dialog regression ticket",
            requester="Dialog Tester",
            assignee="Unassigned",
            priority="High",
        )
        self.root.update_idletasks()

    def tearDown(self) -> None:
        try:
            self.app.shutdown()
        except Exception:
            pass
        self.tempdir.cleanup()

    def _open(self, factory):
        """Open a dialog, assert it rendered, then close it."""
        dialog = factory()
        self.root.update_idletasks()
        self.root.update()
        self.assertTrue(dialog.winfo_exists())
        self.assertGreater(dialog.winfo_width(), 0)
        self.assertGreater(dialog.winfo_height(), 0)
        # The dialog must fit on the display it was opened on.
        self.assertLessEqual(
            dialog.winfo_width(), self.root.winfo_screenwidth())
        self.assertLessEqual(
            dialog.winfo_height(), self.root.winfo_screenheight())
        dialog.close()
        self.root.update()
        return dialog

    def test_confirm_dialog_opens_and_closes(self) -> None:
        from ui.dialogs import ConfirmDialog

        self._open(lambda: ConfirmDialog(
            self.root, "Delete ticket", "This cannot be undone.",
            confirm_label="Delete", danger=True))

    def test_ticket_dialog_opens_for_create_and_edit(self) -> None:
        from ui.dialogs import TicketDialog

        self._open(lambda: TicketDialog(
            self.root, self.app.services["tickets"], self.app.services["sla"], None))
        self._open(lambda: TicketDialog(
            self.root, self.app.services["tickets"], self.app.services["sla"],
            self.ticket))

    def test_assign_dialog_opens(self) -> None:
        from ui.dialogs import AssignDialog

        self._open(lambda: AssignDialog(
            self.root, self.app.services["tickets"], self.ticket))

    def test_status_dialog_opens(self) -> None:
        from ui.dialogs import StatusDialog

        self._open(lambda: StatusDialog(
            self.root, self.app.services["tickets"], self.ticket))

    def test_comment_dialog_opens(self) -> None:
        from ui.dialogs import CommentDialog

        self._open(lambda: CommentDialog(
            self.root, self.app.services["tickets"], self.ticket))

    def test_import_summary_dialog_opens(self) -> None:
        from ui.dialogs import ImportSummaryDialog

        result = ImportResult(
            imported=2,
            skipped_duplicates=1,
            total_rows=4,
            errors=[ImportRowError(3, "priority is required", {})],
            warnings=["Row 2: completed status without resolved_at"],
        )
        self._open(lambda: ImportSummaryDialog(self.root, "sample.csv", result))

    def test_ticket_details_dialog_opens(self) -> None:
        from ui.dialogs import TicketDetailsDialog

        self._open(lambda: TicketDetailsDialog(
            self.root, self.app.services["tickets"], self.app.services["sla"],
            self.app.services["audit"], self.app.services["escalations"],
            self.ticket.id))

    def test_dialog_centering_does_not_shadow_the_scale_helper(self) -> None:
        """The centering helper must not shadow the theme's px() helper."""
        from ui.dialogs import ConfirmDialog

        dialog = ConfirmDialog(self.root, "Centring", "Body")
        self.root.update_idletasks()
        geometry = dialog.geometry()
        self.root.update()
        self.assertRegex(geometry, r"^\d+x\d+\+\d+\+\d+$")
        dialog.close()

    def test_dialogs_leave_no_pending_timers_behind(self) -> None:
        """Closing a dialog must cancel its deferred focus callbacks."""
        from ui.dialogs import ConfirmDialog

        dialog = ConfirmDialog(self.root, "Timers", "Body")
        self.root.update_idletasks()
        self.assertTrue(dialog._jobs)
        dialog.close()
        self.root.update()
        self.assertFalse(dialog._jobs)


if __name__ == "__main__":
    unittest.main()
