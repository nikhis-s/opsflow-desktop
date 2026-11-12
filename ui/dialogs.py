"""Modal dialogs for ticket workflows, notes, status changes and import reports."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from config import DEFAULT_ACTOR
from models import (
    CATEGORIES, PRIORITIES, STATUSES, ImportResult, Ticket, format_local,
    human_duration, duration_minutes, truncate,
)
from services.audit_service import AuditService
from services.escalation_engine import EscalationEngine
from services.sla_engine import (
    AT_RISK, BREACHED, MET, ON_TRACK, SLAEngine,
)
from services.ticket_service import TicketService, ValidationError
from ui.components import Badge, Card, DataTable, Meter, flat_button
from ui.theme import COLORS, FONTS, SLA_COLORS, mix


def _text_widget(parent: tk.Misc, height: int = 5, bg: str | None = None, **kwargs) -> tk.Text:
    return tk.Text(
        parent, height=height, wrap="word", bg=bg or COLORS["card_soft"],
        fg=COLORS["text_soft"], insertbackground=COLORS["accent"],
        selectbackground=COLORS["selection"], relief="flat", bd=0,
        highlightthickness=1, highlightbackground=COLORS["border"],
        highlightcolor=COLORS["accent_deep"], font=FONTS["body"],
        padx=10, pady=8, **kwargs,
    )


def _field_label(parent: tk.Misc, text: str, required: bool = False) -> tk.Frame:
    frame = tk.Frame(parent, bg=COLORS["card"])
    tk.Label(frame, text=text, bg=COLORS["card"], fg=COLORS["muted"],
             font=FONTS["tiny"], anchor="w").pack(side="left")
    if required:
        tk.Label(frame, text=" *", bg=COLORS["card"], fg=COLORS["accent"],
                 font=FONTS["tiny"]).pack(side="left")
    return frame


class BaseDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        subtitle: str = "",
        width: int = 720,
        height: int = 620,
        resizable: bool = False,
    ):
        super().__init__(parent)
        self.parent_window = parent.winfo_toplevel()
        self._width = width
        self._height = height
        self.title(f"OpsFlow · {title}")
        self.configure(bg=COLORS["card"])
        self.transient(self.parent_window)
        self.resizable(resizable, resizable)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _event: self.close())
        try:
            self.grab_set()
        except tk.TclError:
            pass

        header = tk.Frame(self, bg=COLORS["surface"])
        header.pack(fill="x")
        tk.Frame(header, bg=COLORS["accent"], height=3).pack(fill="x")
        header_inner = tk.Frame(header, bg=COLORS["surface"])
        header_inner.pack(fill="x", padx=24, pady=(16, 14))
        text = tk.Frame(header_inner, bg=COLORS["surface"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=COLORS["surface"], fg=COLORS["text"],
                 font=FONTS["h2"], anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(text, text=subtitle, bg=COLORS["surface"], fg=COLORS["muted"],
                     font=FONTS["small"], anchor="w").pack(fill="x", pady=(2, 0))
        close = tk.Label(header_inner, text="✕", bg=COLORS["surface"],
                         fg=COLORS["muted"], font=FONTS["medium"], cursor="hand2",
                         padx=8, pady=2)
        close.pack(side="right")
        close.bind("<Button-1>", lambda _event: self.close())
        close.bind("<Enter>", lambda _event: close.configure(fg=COLORS["text"]))
        close.bind("<Leave>", lambda _event: close.configure(fg=COLORS["muted"]))

        self.body = tk.Frame(self, bg=COLORS["card"])
        self.body.pack(fill="both", expand=True, padx=24, pady=(16, 8))
        self.footer = tk.Frame(self, bg=COLORS["card"])
        self.footer.pack(fill="x", padx=24, pady=(4, 18))
        self.error_var = tk.StringVar(value="")
        self.error_label = tk.Label(self.footer, textvariable=self.error_var,
                                    bg=COLORS["card"], fg=COLORS["red"],
                                    font=FONTS["small"], anchor="w", wraplength=width - 60)
        self.error_label.pack(fill="x", pady=(0, 6))
        self.buttons = tk.Frame(self.footer, bg=COLORS["card"])
        self.buttons.pack(fill="x")
        self._center()
        self.after(80, self._safe_focus)

    def _safe_focus(self) -> None:
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.parent_window
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = max(0, px + (pw - self._width) // 2)
        y = max(0, py + (ph - self._height) // 2 - 10)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = min(x, max(0, screen_w - self._width - 20))
        y = min(y, max(0, screen_h - self._height - 50))
        self.geometry(f"{self._width}x{self._height}+{x}+{y}")

    def show_error(self, message: str) -> None:
        self.error_var.set(message)
        self.bell()

    def clear_error(self) -> None:
        self.error_var.set("")

    def clear_footer(self) -> None:
        for child in self.buttons.winfo_children():
            child.destroy()

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class TicketDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        sla: SLAEngine,
        ticket: Ticket | None = None,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.sla = sla
        self.ticket = ticket
        self.on_saved = on_saved
        self.created_at = ticket.created_at if ticket else None
        super().__init__(
            parent,
            "Edit ticket" if ticket else "Create ticket",
            (f"{ticket.id} · update details and SLA-affecting fields"
             if ticket else "Log a new request and start its SLA clock"),
            width=800, height=760, resizable=True,
        )
        self.minsize(720, 680)
        self._build()
        self._populate()
        self.update_sla_preview()

    def _build(self) -> None:
        self.body.grid_columnconfigure(0, weight=1, uniform="form")
        self.body.grid_columnconfigure(1, weight=1, uniform="form")
        self.body.grid_rowconfigure(4, weight=1)

        _field_label(self.body, "Title", True).grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.title_var = tk.StringVar()
        self.title_entry = ttk.Entry(self.body, textvariable=self.title_var)
        self.title_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        _field_label(self.body, "Requester", True).grid(
            row=2, column=0, sticky="ew", padx=(0, 8), pady=(0, 4))
        _field_label(self.body, "Assignee").grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        self.requester_var = tk.StringVar()
        self.assignee_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self.requester_var).grid(
            row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 12))
        self.assignee_combo = ttk.Combobox(
            self.body, textvariable=self.assignee_var,
            values=["Unassigned"] + self.tickets.get_assignees(), state="normal",
        )
        self.assignee_combo.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 12))

        _field_label(self.body, "Category").grid(
            row=4, column=0, sticky="ew", padx=(0, 8), pady=(0, 4))
        _field_label(self.body, "Priority", True).grid(
            row=4, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        self.category_var = tk.StringVar()
        self.priority_var = tk.StringVar()
        self.category_combo = ttk.Combobox(
            self.body, textvariable=self.category_var,
            values=self.tickets.get_categories(), state="normal",
        )
        self.category_combo.grid(row=5, column=0, sticky="ew", padx=(0, 8), pady=(0, 12))
        self.priority_combo = ttk.Combobox(
            self.body, textvariable=self.priority_var, values=list(PRIORITIES),
            state="readonly",
        )
        self.priority_combo.grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(0, 12))
        self.priority_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_sla_preview())

        _field_label(self.body, "Status", True).grid(
            row=6, column=0, sticky="ew", padx=(0, 8), pady=(0, 4))
        _field_label(self.body, "Created (UTC clock start)").grid(
            row=6, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        self.status_var = tk.StringVar()
        self.status_combo = ttk.Combobox(
            self.body, textvariable=self.status_var, values=list(STATUSES),
            state="readonly",
        )
        self.status_combo.grid(row=7, column=0, sticky="ew", padx=(0, 8), pady=(0, 14))
        self.created_label = tk.Label(
            self.body, text="", bg=COLORS["card_soft"], fg=COLORS["text_soft"],
            font=FONTS["small"], anchor="w", padx=10, pady=9,
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        self.created_label.grid(row=7, column=1, sticky="ew", padx=(8, 0), pady=(0, 14))

        _field_label(self.body, "Description").grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.description_text = _text_widget(self.body, height=6)
        self.description_text.grid(row=9, column=0, columnspan=2, sticky="nsew", pady=(0, 14))
        self.body.grid_rowconfigure(9, weight=1)

        preview = tk.Frame(self.body, bg=COLORS["card_soft"], highlightthickness=1,
                           highlightbackground=COLORS["border_soft"])
        preview.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        inner = tk.Frame(preview, bg=COLORS["card_soft"])
        inner.pack(fill="x", padx=14, pady=11)
        tk.Label(inner, text="SLA CLOCK PREVIEW", bg=COLORS["card_soft"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(anchor="w")
        self.sla_preview_var = tk.StringVar()
        tk.Label(inner, textvariable=self.sla_preview_var, bg=COLORS["card_soft"],
                 fg=COLORS["text_soft"], font=FONTS["small"], anchor="w",
                 justify="left").pack(fill="x", pady=(4, 0))

        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(
            self.buttons, "Save changes" if self.ticket else "Create ticket",
            self.save, "primary",
        ).pack(side="right", padx=(0, 8))

    def _populate(self) -> None:
        ticket = self.ticket
        if ticket:
            self.title_var.set(ticket.title)
            self.requester_var.set(ticket.requester)
            self.assignee_var.set(ticket.assignee)
            self.category_var.set(ticket.category)
            self.priority_var.set(ticket.priority)
            self.status_var.set(ticket.status)
            self.description_text.insert("1.0", ticket.description)
            self.created_label.configure(text=format_local(ticket.created_at))
        else:
            self.assignee_var.set("Unassigned")
            self.category_var.set("General")
            self.priority_var.set("Medium")
            self.status_var.set("Open")
            self.created_label.configure(text="Set automatically on save")

    def update_sla_preview(self) -> None:
        priority = self.priority_var.get() or "Medium"
        try:
            policy = self.sla.get_policy(priority)
        except ValueError:
            return
        from models import utc_now
        created = self.created_at or utc_now()
        response, resolution = self.sla.deadlines_for(priority, created)
        self.sla_preview_var.set(
            f"{priority}: respond within {duration_minutes(policy.response_minutes)} "
            f"(due {format_local(response)}) · resolve within "
            f"{duration_minutes(policy.resolution_minutes)} "
            f"(due {format_local(resolution)}). Warning at "
            f"{policy.at_risk_percent}% of each window."
        )
        self.created_label.configure(
            text=format_local(created) if self.ticket else "Set automatically on save"
        )

    def save(self) -> None:
        self.clear_error()
        title = self.title_var.get()
        description = self.description_text.get("1.0", "end-1c")
        requester = self.requester_var.get()
        assignee = self.assignee_var.get()
        category = self.category_var.get()
        priority = self.priority_var.get()
        status = self.status_var.get()
        try:
            if self.ticket:
                updated = self.tickets.update_ticket(
                    self.ticket.id,
                    {
                        "title": title,
                        "description": description,
                        "requester": requester,
                        "assignee": assignee,
                        "category": category,
                        "priority": priority,
                        "status": status,
                    },
                )
            else:
                updated = self.tickets.create_ticket(
                    title=title,
                    description=description,
                    requester=requester,
                    assignee=assignee,
                    category=category,
                    priority=priority,
                    status=status,
                )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.show_error(f"Could not save ticket: {exc}")
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()


class AssignDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Assign ticket", f"{ticket.id} · {ticket.title}",
                         width=520, height=330)
        tk.Label(self.body, text="Assign this ticket to an owner or queue.", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["small"]).pack(anchor="w", pady=(0, 8))
        _field_label(self.body, "Assignee", True).pack(anchor="w", pady=(0, 4))
        self.assignee_var = tk.StringVar(value=ticket.assignee)
        self.combo = ttk.Combobox(
            self.body, textvariable=self.assignee_var,
            values=["Unassigned"] + tickets.get_assignees(), state="normal",
        )
        self.combo.pack(fill="x", pady=(0, 8))
        tk.Label(
            self.body,
            text="Assigning a ticket is recorded in the audit trail.",
            bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"],
        ).pack(anchor="w")
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Assign ticket", self.save, "primary").pack(
            side="right", padx=(0, 8))
        self.after(100, self.combo.focus_set)

    def save(self) -> None:
        self.clear_error()
        try:
            updated = self.tickets.assign_ticket(self.ticket.id, self.assignee_var.get())
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()


class StatusDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Ticket], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Change status", f"{ticket.id} · currently {ticket.status}",
                         width=560, height=430)
        _field_label(self.body, "New status", True).pack(anchor="w", pady=(0, 4))
        self.status_var = tk.StringVar(value=ticket.status)
        self.combo = ttk.Combobox(self.body, textvariable=self.status_var,
                                  values=list(STATUSES), state="readonly")
        self.combo.pack(fill="x", pady=(0, 12))
        _field_label(self.body, "Note (optional internal comment)").pack(anchor="w", pady=(0, 4))
        self.note = _text_widget(self.body, height=5)
        self.note.pack(fill="both", expand=True)
        self.hint = tk.Label(
            self.body,
            text="Resolved/Closed stamps resolution time. Reopening clears the completion stamps.",
            bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"],
            wraplength=480, justify="left",
        )
        self.hint.pack(anchor="w", pady=(8, 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Update status", self.save, "primary").pack(
            side="right", padx=(0, 8))
        self.after(100, self.combo.focus_set)

    def save(self) -> None:
        self.clear_error()
        if self.status_var.get() == self.ticket.status:
            self.show_error("Choose a different status, or add the note from the ticket activity tab.")
            return
        try:
            updated = self.tickets.change_status(
                self.ticket.id, self.status_var.get(),
                note=self.note.get("1.0", "end-1c"),
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(updated)
        self.close()


class CommentDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        ticket: Ticket,
        on_saved: Callable[[Any], None] | None = None,
    ):
        self.tickets = tickets
        self.ticket = ticket
        self.on_saved = on_saved
        super().__init__(parent, "Add internal note", f"{ticket.id} · {ticket.title}",
                         width=580, height=430)
        tk.Label(
            self.body,
            text="Internal notes are stored in OpsFlow and never sent externally.",
            bg=COLORS["card"], fg=COLORS["muted"], font=FONTS["small"],
        ).pack(anchor="w", pady=(0, 8))
        self.note = _text_widget(self.body, height=8)
        self.note.pack(fill="both", expand=True)
        self.internal_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.body, text="Internal note", variable=self.internal_var).pack(
            anchor="w", pady=(8, 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Add note", self.save, "primary").pack(
            side="right", padx=(0, 8))
        self.after(120, self.note.focus_set)

    def save(self) -> None:
        self.clear_error()
        try:
            comment = self.tickets.add_comment(
                self.ticket.id, self.note.get("1.0", "end-1c"),
                internal=self.internal_var.get(),
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        if self.on_saved:
            self.on_saved(comment)
        self.close()


class ConfirmDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, message: str,
                 confirm_label: str = "Confirm", danger: bool = False,
                 on_confirm: Callable[[], None] | None = None):
        self.on_confirm = on_confirm
        super().__init__(parent, title, "This action is recorded in the audit trail.",
                         width=520, height=280)
        tk.Label(self.body, text=message, bg=COLORS["card"], fg=COLORS["text_soft"],
                 font=FONTS["body"], wraplength=460, justify="left").pack(
            anchor="w", fill="x", pady=(6, 0))
        flat_button(self.buttons, "Cancel", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, confirm_label, self._confirm,
                    "danger" if danger else "primary").pack(side="right", padx=(0, 8))

    def _confirm(self) -> None:
        callback = self.on_confirm
        self.close()
        if callback:
            callback()


class ImportSummaryDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, filename: str, result: ImportResult):
        self.result = result
        super().__init__(parent, "CSV import summary", filename,
                         width=860, height=620, resizable=True)
        self.minsize(720, 520)

        row = tk.Frame(self.body, bg=COLORS["card"])
        row.pack(fill="x", pady=(0, 12))
        for label, value, color in (
            ("Imported", result.imported, COLORS["green"]),
            ("Duplicates skipped", result.skipped_duplicates, COLORS["amber"]),
            ("Rejected rows", len(result.errors), COLORS["red"]),
            ("Rows read", result.total_rows, COLORS["text"]),
        ):
            stat = tk.Frame(row, bg=COLORS["card_soft"], highlightthickness=1,
                            highlightbackground=COLORS["border_soft"])
            stat.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(stat, text=str(value), bg=COLORS["card_soft"], fg=color,
                     font=FONTS["h1"]).pack(anchor="w", padx=14, pady=(10, 0))
            tk.Label(stat, text=label.upper(), bg=COLORS["card_soft"], fg=COLORS["muted"],
                     font=FONTS["tiny"]).pack(anchor="w", padx=14, pady=(0, 10))

        summary = result.summary
        tk.Label(self.body, text=summary, bg=COLORS["card"], fg=COLORS["text_soft"],
                 font=FONTS["semibold"]).pack(anchor="w", pady=(0, 8))

        if result.errors:
            tk.Label(self.body, text="Rejected rows", bg=COLORS["card"], fg=COLORS["red"],
                     font=FONTS["small"]).pack(anchor="w", pady=(0, 4))
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
            table.pack(fill="both", expand=True, pady=(0, 8))
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
                     font=FONTS["small"]).pack(anchor="w", pady=(4, 4))
            text = _text_widget(self.body, height=5)
            text.pack(fill="x")
            text.insert("1.0", "\n".join(f"• {warning}" for warning in result.warnings[:25]))
            if len(result.warnings) > 25:
                text.insert("end", f"\n… and {len(result.warnings) - 25} more")
            text.configure(state="disabled")

        flat_button(self.buttons, "Done", self.close, "primary").pack(side="right")


class TicketDetailsDialog(BaseDialog):
    def __init__(
        self,
        parent: tk.Misc,
        tickets: TicketService,
        sla: SLAEngine,
        audit: AuditService,
        escalations: EscalationEngine,
        ticket_id: str,
        on_changed: Callable[[], None] | None = None,
    ):
        self.tickets = tickets
        self.sla = sla
        self.audit = audit
        self.escalations = escalations
        self.ticket_id = ticket_id
        self.on_changed = on_changed
        self.ticket: Ticket | None = None
        super().__init__(parent, "Ticket details", "", width=1120, height=840,
                         resizable=True)
        self.minsize(960, 700)
        self._build()

    # --------------------------------------------------------------- layout
    def _build(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.clear_footer()
        try:
            self.ticket = self.tickets.get_ticket(self.ticket_id)
        except Exception as exc:
            tk.Label(self.body, text=f"Unable to load ticket: {exc}", bg=COLORS["card"],
                     fg=COLORS["red"], font=FONTS["body"]).pack(anchor="w")
            return
        ticket = self.ticket
        self.title(f"OpsFlow · {ticket.id}")
        self.body.grid_columnconfigure(0, weight=3)
        self.body.grid_columnconfigure(1, weight=2)
        self.body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self.body, bg=COLORS["card"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        right = tk.Frame(self.body, bg=COLORS["card"])
        right.grid(row=0, column=1, sticky="nsew")

        # Header
        eyebrow = tk.Frame(left, bg=COLORS["card"])
        eyebrow.pack(fill="x")
        tk.Label(eyebrow, text=ticket.id, bg=COLORS["card"], fg=COLORS["accent"],
                 font=FONTS["mono"]).pack(side="left")
        tk.Label(eyebrow, text=f"  ·  Created {format_local(ticket.created_at)}",
                 bg=COLORS["card"], fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        tk.Label(left, text=ticket.title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONTS["h1"], wraplength=490, justify="left", anchor="w").pack(
            fill="x", pady=(4, 8))
        badge_row = tk.Frame(left, bg=COLORS["card"])
        badge_row.pack(fill="x", pady=(0, 14))
        status_badge = Badge(badge_row, ticket.status, bg=COLORS["card"])
        status_badge.set_status(ticket.status)
        status_badge.pack(side="left", padx=(0, 6))
        priority_badge = Badge(badge_row, ticket.priority, bg=COLORS["card"])
        priority_badge.set_priority(ticket.priority)
        priority_badge.pack(side="left", padx=(0, 6))
        evaluation = self.sla.evaluate(ticket)
        sla_badge = Badge(badge_row, evaluation.overall_state, bg=COLORS["card"])
        sla_badge.pack(side="left", padx=(0, 6))
        tk.Label(badge_row, text=ticket.category, bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONTS["small"]).pack(side="left", padx=(8, 0))

        # SLA meters
        meters = tk.Frame(left, bg=COLORS["card"])
        meters.pack(fill="x", pady=(0, 16))
        meters.grid_columnconfigure(0, weight=1)
        meters.grid_columnconfigure(1, weight=1)
        self._deadline_card(
            meters, 0, "RESPONSE SLA", ticket.response_deadline,
            evaluation.response.state, evaluation.response.remaining_seconds,
            evaluation.response.consumed_percent, ticket.first_response_at,
        )
        self._deadline_card(
            meters, 1, "RESOLUTION SLA", ticket.resolution_deadline,
            evaluation.resolution.state, evaluation.resolution.remaining_seconds,
            evaluation.resolution.consumed_percent, ticket.resolved_at,
        )

        # Description
        tk.Label(left, text="DESCRIPTION", bg=COLORS["card"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(anchor="w", pady=(0, 4))
        desc = _text_widget(left, height=4)
        desc.pack(fill="x", pady=(0, 16))
        desc.insert("1.0", ticket.description or "No description provided.")
        desc.configure(state="disabled")

        # Metadata
        meta = tk.Frame(left, bg=COLORS["card"])
        meta.pack(fill="both", expand=True)
        meta.grid_columnconfigure(0, weight=1)
        meta.grid_columnconfigure(1, weight=1)
        fields = [
            ("Requester", ticket.requester),
            ("Assignee", ticket.assignee),
            ("Category", ticket.category),
            ("Priority", ticket.priority),
            ("Created", format_local(ticket.created_at)),
            ("Last updated", format_local(ticket.updated_at)),
            ("First response", format_local(ticket.first_response_at)),
            ("Resolved", format_local(ticket.resolved_at)),
            ("Response deadline", format_local(ticket.response_deadline)),
            ("Resolution deadline", format_local(ticket.resolution_deadline)),
        ]
        for index, (label, value) in enumerate(fields):
            cell = tk.Frame(meta, bg=COLORS["card"])
            cell.grid(row=index // 2, column=index % 2, sticky="ew", pady=(0, 10),
                      padx=(0, 12 if index % 2 == 0 else 0))
            tk.Label(cell, text=label.upper(), bg=COLORS["card"], fg=COLORS["subtle"],
                     font=FONTS["tiny"], anchor="w").pack(fill="x")
            tk.Label(cell, text=value or "—", bg=COLORS["card"], fg=COLORS["text_soft"],
                     font=FONTS["small"], anchor="w").pack(fill="x")

        # Right: notes
        notes_header = tk.Frame(right, bg=COLORS["card"])
        notes_header.pack(fill="x")
        comments = self.tickets.get_comments(ticket.id)
        tk.Label(notes_header, text="INTERNAL NOTES", bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        tk.Label(notes_header, text=f"{len(comments)}", bg=COLORS["card"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="right")

        notes_frame = tk.Frame(right, bg=COLORS["card_soft"], highlightthickness=1,
                               highlightbackground=COLORS["border_soft"])
        notes_frame.pack(fill="both", expand=True, pady=(6, 8))
        notes_text = _text_widget(notes_frame, height=12, bg=COLORS["card_soft"])
        notes_text.pack(fill="both", expand=True, padx=1, pady=1)
        notes_text.tag_configure("author", foreground=COLORS["text"],
                                 font=FONTS["medium"], spacing1=4)
        notes_text.tag_configure("time", foreground=COLORS["subtle"], font=FONTS["tiny"])
        notes_text.tag_configure("body", foreground=COLORS["text_soft"],
                                 font=FONTS["small"], spacing3=8, lmargin1=0, lmargin2=0)
        notes_text.tag_configure("divider", foreground=COLORS["border"])
        if not comments:
            notes_text.insert("end", "No internal notes yet.\n", "body")
        for comment in comments:
            notes_text.insert("end", f"{comment.author}", "author")
            notes_text.insert("end", f"   {format_local(comment.created_at)}\n", "time")
            notes_text.insert("end", f"{comment.body}\n", "body")
            notes_text.insert("end", "─" * 48 + "\n", "divider")
        notes_text.configure(state="disabled")
        notes_text.see("end")

        input_row = tk.Frame(right, bg=COLORS["card"])
        input_row.pack(fill="x")
        self.note_text = _text_widget(input_row, height=3)
        self.note_text.pack(fill="x", pady=(0, 6))
        flat_button(input_row, "Add internal note", self._add_note, "secondary").pack(
            side="right")

        activity_header = tk.Frame(right, bg=COLORS["card"])
        activity_header.pack(fill="x", pady=(14, 0))
        tk.Label(activity_header, text="RECENT ACTIVITY", bg=COLORS["card"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="left")
        activity_frame = tk.Frame(right, bg=COLORS["card_soft"], highlightthickness=1,
                                  highlightbackground=COLORS["border_soft"])
        activity_frame.pack(fill="x", pady=(6, 0))
        activity_text = _text_widget(activity_frame, height=9, bg=COLORS["card_soft"])
        activity_text.pack(fill="both", expand=True, padx=1, pady=1)
        activity_text.tag_configure("action", foreground=COLORS["accent"],
                                    font=FONTS["tiny"])
        activity_text.tag_configure("time", foreground=COLORS["subtle"], font=FONTS["tiny"])
        activity_text.tag_configure("body", foreground=COLORS["muted"],
                                    font=FONTS["small"], spacing3=4)
        for event in self.audit.for_ticket(ticket.id, limit=20):
            activity_text.insert("end", event.action, "action")
            activity_text.insert("end", f"  {format_local(event.created_at)}\n", "time")
            activity_text.insert("end", event.details + "\n", "body")
        activity_text.configure(state="disabled")

        # Footer actions
        flat_button(self.buttons, "Delete", self._delete, "danger").pack(side="left")
        flat_button(self.buttons, "Close", self.close, "ghost").pack(side="right")
        flat_button(self.buttons, "Edit", self._edit, "secondary").pack(
            side="right", padx=(0, 8))
        flat_button(self.buttons, "Change status", self._status, "secondary").pack(
            side="right", padx=(0, 8))
        flat_button(self.buttons, "Assign", self._assign, "primary").pack(
            side="right", padx=(0, 8))

    def _deadline_card(
        self, parent: tk.Misc, column: int, title: str, deadline: Any,
        state: str, remaining: int | None, consumed: float, completed_at: Any,
    ) -> None:
        color = SLA_COLORS.get(state, COLORS["accent"])
        card = tk.Frame(parent, bg=COLORS["card_soft"], highlightthickness=1,
                        highlightbackground=COLORS["border_soft"])
        card.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column == 0 else (8, 0))
        inner = tk.Frame(card, bg=COLORS["card_soft"])
        inner.pack(fill="x", padx=12, pady=10)
        top = tk.Frame(inner, bg=COLORS["card_soft"])
        top.pack(fill="x")
        tk.Label(top, text=title, bg=COLORS["card_soft"], fg=COLORS["subtle"],
                 font=FONTS["tiny"]).pack(side="left")
        badge = Badge(top, state, bg=COLORS["card_soft"])
        badge.pack(side="right")
        if completed_at is not None:
            if remaining is not None and remaining >= 0:
                detail = f"{state} · {human_duration(remaining)} early"
            else:
                detail = f"{state} · {human_duration(abs(remaining or 0))} late"
        else:
            detail = (f"{human_duration(abs(remaining))} remaining" if (remaining or 0) >= 0
                      else f"{human_duration(abs(remaining or 0))} overdue")
        tk.Label(inner, text=format_local(deadline), bg=COLORS["card_soft"],
                 fg=COLORS["text_soft"], font=FONTS["small"]).pack(anchor="w", pady=(5, 2))
        tk.Label(inner, text=detail, bg=COLORS["card_soft"], fg=color,
                 font=FONTS["tiny"]).pack(anchor="w")
        meter = Meter(inner, height=6, bg=COLORS["card_soft"])
        meter.pack(fill="x", pady=(7, 0))
        meter.set(100.0 if state in (MET, "Missed") else consumed, color)

    # --------------------------------------------------------------- actions
    def _add_note(self) -> None:
        self.clear_error()
        try:
            self.tickets.add_comment(
                self.ticket_id, self.note_text.get("1.0", "end-1c"), internal=True,
            )
        except (ValidationError, ValueError) as exc:
            self.show_error(str(exc))
            return
        self._changed()

    def _edit(self) -> None:
        TicketDialog(
            self, self.tickets, self.sla, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _assign(self) -> None:
        AssignDialog(
            self, self.tickets, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _status(self) -> None:
        StatusDialog(
            self, self.tickets, self.ticket, on_saved=lambda _t: self._changed()
        )

    def _delete(self) -> None:
        def confirm() -> None:
            try:
                self.tickets.delete_ticket(self.ticket_id)
            except Exception as exc:
                self.show_error(f"Could not delete ticket: {exc}")
                return
            if self.on_changed:
                self.on_changed()
            self.close()
        ConfirmDialog(
            self, "Delete ticket",
            f"Delete {self.ticket_id} and its comments? Audit and escalation history will be preserved.",
            confirm_label="Delete ticket", danger=True, on_confirm=confirm,
        )

    def _changed(self) -> None:
        if self.on_changed:
            self.on_changed()
        self._build()
