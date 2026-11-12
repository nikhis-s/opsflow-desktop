"""Data exchange: guarded CSV import, report exports and database utilities."""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

from services.csv_service import CSVFormatError
from ui.components import Card, Page, ScrollableFrame, SectionHeader, flat_button
from ui.dialogs import ImportSummaryDialog
from ui.theme import COLORS, FONTS


class DataPage(Page):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent, app)
        self._last_import_summary = "No import run in this session."
        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True)
        outer = tk.Frame(self.scroller.content, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=26, pady=20)

        header = SectionHeader(
            outer, "Data exchange",
            "Import validated ticket data, export operational reports and manage the local database.",
        )
        header.pack(fill="x", pady=(0, 16))

        top = tk.Frame(outer, bg=COLORS["bg"])
        top.pack(fill="x", pady=(0, 16))
        top.grid_columnconfigure(0, weight=3, uniform="data-top")
        top.grid_columnconfigure(1, weight=2, uniform="data-top")

        import_card = Card(top, padding=(20, 17), accent=COLORS["accent"])
        import_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(import_card.body, text="IMPORT TICKETS", bg=COLORS["card"],
                 fg=COLORS["accent"], font=FONTS["tiny"]).pack(anchor="w")
        tk.Label(import_card.body, text="CSV import with row-level validation",
                 bg=COLORS["card"], fg=COLORS["text"], font=FONTS["h2"]).pack(
            anchor="w", pady=(4, 4))
        tk.Label(
            import_card.body,
            text="Required columns: title, requester and priority. Missing deadlines are calculated "
                 "from the applicable SLA policy. Duplicate ticket IDs are skipped, and every rejected "
                 "row is reported individually.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"],
            justify="left", wraplength=630,
        ).pack(anchor="w")
        import_buttons = tk.Frame(import_card.body, bg=COLORS["card"])
        import_buttons.pack(fill="x", pady=(12, 0))
        flat_button(import_buttons, "Choose CSV file", self.import_csv, "primary").pack(
            side="left")
        flat_button(import_buttons, "Download template", self.download_template,
                    "secondary").pack(side="left", padx=(8, 0))
        self.import_summary_var = tk.StringVar(value=self._last_import_summary)
        tk.Label(import_card.body, textvariable=self.import_summary_var, bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").pack(
            fill="x", pady=(10, 0))

        rules_card = Card(top, padding=(20, 17), bg=COLORS["surface"])
        rules_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(rules_card.body, text="IMPORT RULES", bg=COLORS["surface"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(anchor="w")
        rules = (
            "• Priority: Critical, High, Medium, Low\n"
            "• Status: Open, In Progress, Pending, Resolved, Closed\n"
            "• Timestamps: ISO or 2026-05-01 14:30 (local)\n"
            "• Blank ticket_id → generated automatically\n"
            "• Existing IDs and in-file duplicates are skipped\n"
            "• Valid rows import independently; errors are listed"
        )
        tk.Label(rules_card.body, text=rules, bg=COLORS["surface"], fg=COLORS["text_soft"],
                 font=FONTS["small"], justify="left").pack(anchor="w", pady=(8, 0))

        tk.Label(outer, text="EXPORTS", bg=COLORS["bg"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(anchor="w", pady=(0, 6))
        exports = tk.Frame(outer, bg=COLORS["bg"])
        exports.pack(fill="x", pady=(0, 16))
        for column in range(2):
            exports.grid_columnconfigure(column, weight=1, uniform="exports")
        self.export_count_vars: dict[str, tk.StringVar] = {}
        export_specs = [
            ("all", "All tickets", "Full ticket dataset with SLA state and timestamps.",
             COLORS["accent"], self.export_all_tickets),
            ("sla", "SLA report", "Deadline states, remaining time and compliance fields.",
             COLORS["green"], self.export_sla),
            ("escalations", "Escalation history", "Every recorded warning and critical event.",
             COLORS["amber"], self.export_escalations),
            ("audit", "Audit trail", "Complete immutable operation log for compliance review.",
             COLORS["blue"], self.export_audit),
        ]
        for index, (key, title, description, accent, command) in enumerate(export_specs):
            card = Card(exports, padding=(18, 15))
            card.grid(row=index // 2, column=index % 2, sticky="nsew",
                      padx=(0, 6) if index % 2 == 0 else (6, 0),
                      pady=(0, 8) if index < 2 else (8, 0))
            top_row = tk.Frame(card.body, bg=COLORS["card"])
            top_row.pack(fill="x")
            tk.Frame(top_row, bg=accent, width=3, height=32).pack(side="left", padx=(0, 10))
            text = tk.Frame(top_row, bg=COLORS["card"])
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=title, bg=COLORS["card"], fg=COLORS["text"],
                     font=FONTS["semibold"], anchor="w").pack(fill="x")
            count_var = tk.StringVar(value="—")
            self.export_count_vars[key] = count_var
            tk.Label(text, textvariable=count_var, bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"], anchor="w").pack(fill="x")
            tk.Label(card.body, text=description, bg=COLORS["card"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w", justify="left").pack(
                fill="x", pady=(8, 10))
            flat_button(card.body, "Export CSV", command, "secondary").pack(anchor="e")

        db_card = Card(outer, padding=(20, 17))
        db_card.pack(fill="x")
        db_header = tk.Frame(db_card.body, bg=COLORS["card"])
        db_header.pack(fill="x", pady=(0, 8))
        db_text = tk.Frame(db_header, bg=COLORS["card"])
        db_text.pack(side="left", fill="x", expand=True)
        tk.Label(db_text, text="Local database", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x")
        tk.Label(db_text, text="SQLite · persistent across restarts · offline only",
                 bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["tiny"],
                 anchor="w").pack(fill="x", pady=(2, 0))
        flat_button(db_header, "Open data folder", self.open_folder, "ghost").pack(
            side="right", padx=(8, 0))
        flat_button(db_header, "Backup now", self.backup_now, "secondary").pack(side="right")

        self.db_path_var = tk.StringVar(value="")
        self.db_info_var = tk.StringVar(value="")
        self.backup_var = tk.StringVar(value="")
        tk.Label(db_card.body, textvariable=self.db_path_var, bg=COLORS["card"],
                 fg=COLORS["text_soft"], font=FONTS["mono"], anchor="w").pack(
            fill="x", pady=(2, 4))
        tk.Label(db_card.body, textvariable=self.db_info_var, bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"], anchor="w").pack(fill="x")
        tk.Label(db_card.body, textvariable=self.backup_var, bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").pack(
            fill="x", pady=(4, 0))

        tk.Label(
            outer,
            text="OpsFlow runs entirely offline. No external API credentials, cloud services or "
                 "notification providers are used.",
            bg=COLORS["bg"], fg=COLORS["subtle"], font=FONTS["tiny"],
        ).pack(fill="x", pady=(12, 2))

    # ---------------------------------------------------------------- updates
    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        db = self.app.services["db"]
        counts = db.counts()
        self.export_count_vars["all"].set(f"{counts['tickets']} ticket row(s)")
        self.export_count_vars["sla"].set(f"{counts['tickets']} SLA row(s)")
        self.export_count_vars["escalations"].set(f"{counts['escalations']} event(s)")
        self.export_count_vars["audit"].set(f"{counts['audit_events']} audit event(s)")
        self.import_summary_var.set(self._last_import_summary)
        self.db_path_var.set(str(db.path))
        size_kb = db.size_bytes() / 1024
        health = db.health()
        self.db_info_var.set(
            f"Schema v{db.schema_version} · {size_kb:,.1f} KB · health: {health} · "
            f"{counts['comments']} comment(s)"
        )
        backups = sorted(db.backup_dir.glob("opsflow-backup-*.db"))
        self.backup_var.set(
            f"Latest backup: {backups[-1].name}" if backups else
            "No backups yet. Backups are created automatically before migrations, and on demand."
        )

    # ----------------------------------------------------------------- import
    def import_csv(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self,
            title="Import tickets from CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not filename:
            return
        try:
            result = self.app.services["csv"].import_tickets(filename)
        except CSVFormatError as exc:
            messagebox.showerror("CSV import rejected", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("CSV import failed", str(exc), parent=self)
            return
        self._last_import_summary = f"Last import: {Path(filename).name} · {result.summary}"
        self.refresh()
        self.app.notify_data_changed()
        self.app.set_status(
            f"CSV import: {result.summary}.", "success" if not result.errors else "warning"
        )
        ImportSummaryDialog(self, Path(filename).name, result)

    def download_template(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save CSV import template",
            defaultextension=".csv",
            initialfile="opsflow-import-template.csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not filename:
            return
        try:
            self.app.services["csv"].write_template(filename)
        except Exception as exc:
            messagebox.showerror("Template export failed", str(exc), parent=self)
            return
        self.app.set_status(f"CSV template saved to {Path(filename).name}.", "success")

    # ----------------------------------------------------------------- export
    def _save_path(self, title: str, prefix: str) -> str:
        return filedialog.asksaveasfilename(
            parent=self,
            title=title,
            defaultextension=".csv",
            initialfile=f"opsflow-{prefix}-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )

    def export_all_tickets(self) -> None:
        filename = self._save_path("Export all tickets", "all-tickets")
        if not filename:
            return
        self._export(filename, "ticket", lambda path: self.app.services["csv"].export_tickets(path))

    def export_sla(self) -> None:
        filename = self._save_path("Export SLA report", "sla-report")
        if not filename:
            return
        self._export(filename, "SLA row", lambda path: self.app.services["csv"].export_sla_report(path))

    def export_escalations(self) -> None:
        filename = self._save_path("Export escalation history", "escalations")
        if not filename:
            return
        self._export(filename, "escalation event",
                     lambda path: self.app.services["csv"].export_escalations(path))

    def export_audit(self) -> None:
        filename = self._save_path("Export audit trail", "audit")
        if not filename:
            return
        self._export(filename, "audit event",
                     lambda path: self.app.services["csv"].export_audit(path))

    def _export(self, filename: str, noun: str, operation: Callable[[str], int]) -> None:
        try:
            count = operation(filename)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.app.set_status(
            f"Exported {count} {noun}{'s' if count != 1 else ''} to {Path(filename).name}.",
            "success",
        )

    # ---------------------------------------------------------------- database
    def backup_now(self) -> None:
        db = self.app.services["db"]
        try:
            path = db.backup_database("manual")
        except Exception as exc:
            messagebox.showerror("Backup failed", str(exc), parent=self)
            return
        self.refresh()
        self.app.set_status(f"Database backup written to {path.name}.", "success")

    def open_folder(self) -> None:
        path = self.app.services["db"].path.parent
        try:
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("Could not open data folder", str(exc), parent=self)
