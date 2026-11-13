"""Modal dialogs for ticket workflows, notes, status changes and import reports."""
from __future__ import annotations

from ui.dialogs.base import BaseDialog
from ui.dialogs.confirm import ConfirmDialog
from ui.dialogs.details import TicketDetailsDialog
from ui.dialogs.import_summary import ImportSummaryDialog
from ui.dialogs.ticket import TicketDialog
from ui.dialogs.workflow import AssignDialog, CommentDialog, StatusDialog

__all__ = [
    "AssignDialog",
    "BaseDialog",
    "CommentDialog",
    "ConfirmDialog",
    "ImportSummaryDialog",
    "StatusDialog",
    "TicketDetailsDialog",
    "TicketDialog",
]
