"""CSV import summary with per-row rejection reporting."""
from __future__ import annotations

import tkinter as tk

from models import ImportResult, truncate
from ui.components import DataTable, flat_button
from ui.dialogs.base import BaseDialog, _text_widget
from ui.theme import COLORS, FONTS, px


class ImportSummaryDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, filename: str, result: ImportResult):
        self.result = result
        super().__init__(parent, "CSV import summary", filename,
                         width=860, height=620, resizable=True)
        self.set_min_size(720, 520)

        row = tk.Frame(self.body, bg=COLORS["card"])
        row.pack(fill="x", pady=(0, px(12)))
        for label, value, color in (
            ("Imported", result.imported, COLORS["green"]),
            ("Duplicates skipped", result.skipped_duplicates, COLORS["amber"]),
            ("Rejected rows", len(result.errors), COLORS["red"]),
            ("Rows read", result.total_rows, COLORS["text"]),
        ):
            stat = tk.Frame(row, bg=COLORS["card_soft"], highlightthickness=1,
                            highlightbackground=COLORS["border_soft"])
            stat.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
            tk.Label(stat, text=str(value), bg=COLORS["card_soft"], fg=color,
                     font=FONTS["h1"]).pack(anchor="w", padx=px(14), pady=(px(10), 0))
            tk.Label(stat, text=label.upper(), bg=COLORS["card_soft"], fg=COLORS["muted"],
                     font=FONTS["micro"]).pack(anchor="w", padx=px(14), pady=(0, px(10)))

        summary = result.summary
        tk.Label(self.body, text=summary, bg=COLORS["card"], fg=COLORS["text_soft"],
                 font=FONTS["semibold"]).pack(anchor="w", pady=(0, px(8)))

        if result.errors:
            tk.Label(self.body, text="Rejected rows", bg=COLORS["card"], fg=COLORS["red"],
                     font=FONTS["small"]).pack(anchor="w", pady=(0, px(4)))
            table = DataTable(
                self.body,
                [
                    {"key": "row", "label": "ROW", "width": 55, "anchor": "center"},
                    {"key": "error", "label": "VALIDATION ERROR", "width": 440, "stretch": True},
                    {"key": "ticket", "label": "TICKET", "width": 105},
                    {"key": "title", "label": "TITLE", "width": 180},
                ],
                height=8,
                empty_title="No rejected rows",
            )
            table.pack(fill="both", expand=True, pady=(0, px(8)))
            rows = []
            payloads = []
            for error in result.errors:
                raw = error.raw or {}
                rows.append((error.row_number, error.message,
                             raw.get("ticket_id", ""), truncate(raw.get("title", ""), 34)))
                payloads.append(error)
            table.set_rows(rows, payloads)

        if result.warnings:
            tk.Label(self.body, text="Warnings", bg=COLORS["card"], fg=COLORS["amber"],
                     font=FONTS["small"]).pack(anchor="w", pady=(px(4), px(4)))
            text = _text_widget(self.body, height=5)
            text.pack(fill="x")
            text.insert("1.0", "\n".join(f"• {warning}" for warning in result.warnings[:25]))
            if len(result.warnings) > 25:
                text.insert("end", f"\n… and {len(result.warnings) - 25} more")
            text.configure(state="disabled")

        flat_button(self.buttons, "Done", self.close, "primary").pack(side="right")

