"""Application shell: sidebar navigation, topbar, scheduled scans and page lifecycle."""
from __future__ import annotations

import logging
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import messagebox
from typing import Any, Callable

from config import APP_NAME, APP_VERSION, DEFAULT_ACTOR
from database import Database
from models import AuditEvent, format_local, utc_now
from services.analytics import AnalyticsService
from services.audit_service import AuditService
from services.csv_service import CSVService
from services.escalation_engine import EscalationEngine
from services.sla_engine import SLAEngine
from services.ticket_service import NotFoundError, TicketService
from ui.audit import AuditPage
from ui.components import SidebarItem, flat_button
from ui.dashboard import DashboardPage
from ui.data import DataPage
from ui.dialogs import TicketDetailsDialog
from ui.escalations import EscalationsPage
from ui.sla import SLAPage
from ui.theme import COLORS, FONTS, apply_theme
from ui.tickets import TicketsPage

logger = logging.getLogger(__name__)

PAGE_META = {
    "dashboard": ("Operations overview", "Live workload, SLA health and operational activity."),
    "tickets": ("Ticket queue", "Search, filter and manage every request."),
    "sla": ("SLA center", "Configure SLA targets and monitor live deadlines."),
    "escalations": ("Escalation desk", "Watch critical tickets and recorded escalation history."),
    "audit": ("Audit trail", "Review every recorded ticket operation."),
    "data": ("Data exchange", "Import validated CSV data and export operational reports."),
}

NAV_ITEMS = [
    ("dashboard", "Dashboard", "▦"),
    ("tickets", "Tickets", "▤"),
    ("sla", "SLA center", "◷"),
    ("escalations", "Escalations", "▲"),
    ("audit", "Audit trail", "≡"),
    ("data", "Data exchange", "⇅"),
]

PAGE_CLASSES: dict[str, type] = {
    "dashboard": DashboardPage,
    "tickets": TicketsPage,
    "sla": SLAPage,
    "escalations": EscalationsPage,
    "audit": AuditPage,
    "data": DataPage,
}


class OpsFlowApp:
    def __init__(self, root: tk.Tk, db: Database):
        self.root = root
        self.db = db
        self.actor = DEFAULT_ACTOR
        self.services = self._build_services(db)
        self.pages: dict[str, Any] = {}
        self.nav_items: dict[str, SidebarItem] = {}
        self.current_page_name: str = ""
        self.current_page: Any = None
        self._timers: list[str] = []
        self._last_scan: datetime | None = None

        root.title(f"{APP_NAME} · Operations & SLA Management")
        root.configure(bg=COLORS["bg"])
        apply_theme(root)
        root.minsize(1200, 720)
        self._set_geometry()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._report_exception
        self._build_shell()
        self._bind_shortcuts()
        self.show_page("dashboard")
        self.update_sidebar_status()
        self.set_status(
            f"Ready · {self.services['db'].counts()['tickets']} ticket(s) loaded from local SQLite.",
            "success",
        )
        self._tick_clock()
        self._schedule_scan()
        self._timers.append(root.after(800, lambda: self.run_escalation_scan(silent=True)))

    def _build_services(self, db: Database) -> dict[str, Any]:
        audit = AuditService(db)
        sla = SLAEngine(db, audit)
        tickets = TicketService(db, sla, audit)
        escalations = EscalationEngine(db, sla, audit)
        analytics = AnalyticsService(db, sla, audit)
        csv_service = CSVService(db, tickets, sla, escalations, audit, analytics)
        return {
            "db": db,
            "audit": audit,
            "sla": sla,
            "tickets": tickets,
            "escalations": escalations,
            "analytics": analytics,
            "csv": csv_service,
        }

    # ------------------------------------------------------------------- shell
    def _set_geometry(self) -> None:
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1460, max(1180, screen_w - 80))
        height = min(920, max(720, screen_h - 90))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 16)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_shell(self) -> None:
        self.shell = tk.Frame(self.root, bg=COLORS["bg"])
        self.shell.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.shell, bg=COLORS["sidebar"], width=236)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.main = tk.Frame(self.shell, bg=COLORS["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self._build_sidebar()
        self._build_topbar()
        self._build_statusbar()

        self.page_host = tk.Frame(self.main, bg=COLORS["bg"])
        self.page_host.pack(fill="both", expand=True)
        self.page_host.grid_rowconfigure(0, weight=1)
        self.page_host.grid_columnconfigure(0, weight=1)

    def _build_sidebar(self) -> None:
        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        brand.pack(fill="x", padx=18, pady=(22, 20))
        logo = tk.Canvas(brand, width=38, height=38, bg=COLORS["sidebar"],
                         highlightthickness=0)
        logo.pack(side="left")
        logo.create_polygon(4, 19, 19, 4, 34, 19, 19, 34, fill=COLORS["accent"], outline="")
        logo.create_polygon(12, 19, 19, 12, 26, 19, 19, 26, fill=COLORS["sidebar"], outline="")
        brand_text = tk.Frame(brand, bg=COLORS["sidebar"])
        brand_text.pack(side="left", padx=(10, 0))
        tk.Label(brand_text, text="OPSFLOW", bg=COLORS["sidebar"], fg=COLORS["text"],
                 font=(FONTS["h2"].actual("family"), 15, "bold")).pack(anchor="w")
        tk.Label(brand_text, text="OPERATIONS CONTROL", bg=COLORS["sidebar"],
                 fg=COLORS["accent"], font=(FONTS["tiny"].actual("family"), 7, "bold")).pack(
            anchor="w", pady=(1, 0))

        tk.Frame(self.sidebar, bg=COLORS["border_soft"], height=1).pack(
            fill="x", padx=18, pady=(0, 16))
        tk.Label(self.sidebar, text="WORKSPACE", bg=COLORS["sidebar"], fg=COLORS["subtle"],
                 font=(FONTS["tiny"].actual("family"), 7, "bold")).pack(
            anchor="w", padx=22, pady=(0, 6))
        nav_container = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        nav_container.pack(fill="x", padx=10)
        for key, label, icon in NAV_ITEMS:
            item = SidebarItem(nav_container, key, label, icon, self.show_page)
            item.pack(fill="x", pady=1)
            self.nav_items[key] = item

        spacer = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        spacer.pack(fill="both", expand=True, pady=(20, 0))

        footer = tk.Frame(self.sidebar, bg=COLORS["sidebar"])
        footer.pack(fill="x", padx=18, pady=(0, 18))
        tk.Frame(footer, bg=COLORS["border_soft"], height=1).pack(fill="x", pady=(0, 14))
        tk.Label(footer, text="SYSTEM", bg=COLORS["sidebar"], fg=COLORS["subtle"],
                 font=(FONTS["tiny"].actual("family"), 7, "bold")).pack(anchor="w")
        state_row = tk.Frame(footer, bg=COLORS["sidebar"])
        state_row.pack(fill="x", pady=(6, 2))
        tk.Label(state_row, text="●", bg=COLORS["sidebar"], fg=COLORS["green"],
                 font=FONTS["tiny"]).pack(side="left")
        tk.Label(state_row, text="Local SQLite · offline ready", bg=COLORS["sidebar"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="left", padx=(6, 0))
        self.sidebar_counts_var = tk.StringVar(value="—")
        tk.Label(footer, textvariable=self.sidebar_counts_var, bg=COLORS["sidebar"],
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").pack(
            fill="x", pady=(0, 10))
        tk.Frame(footer, bg=COLORS["border_soft"], height=1).pack(fill="x", pady=(0, 12))
        operator_row = tk.Frame(footer, bg=COLORS["sidebar"])
        operator_row.pack(fill="x")
        avatar = tk.Label(operator_row, text=(self.actor[:1] or "O").upper(),
                          bg=COLORS["card_alt"], fg=COLORS["accent"], width=3, height=1,
                          font=FONTS["medium"])
        avatar.pack(side="left")
        operator_text = tk.Frame(operator_row, bg=COLORS["sidebar"])
        operator_text.pack(side="left", padx=(8, 0))
        tk.Label(operator_text, text=self.actor, bg=COLORS["sidebar"], fg=COLORS["text_soft"],
                 font=FONTS["small"], anchor="w").pack(fill="x")
        tk.Label(operator_text, text=f"OpsFlow v{APP_VERSION}", bg=COLORS["sidebar"],
                 fg=COLORS["subtle"], font=FONTS["tiny"], anchor="w").pack(fill="x")

    def _build_topbar(self) -> None:
        topbar = tk.Frame(self.main, bg=COLORS["bg"], height=84)
        topbar.pack(side="top", fill="x")
        topbar.pack_propagate(False)
        inner = tk.Frame(topbar, bg=COLORS["bg"])
        inner.pack(fill="both", expand=True, padx=26, pady=(15, 10))
        title_box = tk.Frame(inner, bg=COLORS["bg"])
        title_box.pack(side="left", fill="y")
        self.page_title_var = tk.StringVar(value="Operations overview")
        self.page_subtitle_var = tk.StringVar(value="")
        tk.Label(title_box, textvariable=self.page_title_var, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONTS["h1"], anchor="w").pack(anchor="w")
        tk.Label(title_box, textvariable=self.page_subtitle_var, bg=COLORS["bg"],
                 fg=COLORS["muted"], font=FONTS["small"], anchor="w").pack(
            anchor="w", pady=(1, 0))

        actions = tk.Frame(inner, bg=COLORS["bg"])
        actions.pack(side="right", fill="y")
        self.clock_var = tk.StringVar(value="")
        tk.Label(actions, textvariable=self.clock_var, bg=COLORS["bg"],
                 fg=COLORS["muted"], font=FONTS["mono"]).pack(side="left", padx=(0, 16))
        flat_button(actions, "↻ Refresh", self.refresh_current, "ghost").pack(
            side="left", padx=(0, 6))
        flat_button(actions, "Run SLA scan", self.run_scan_from_topbar, "primary").pack(
            side="left")

    def _build_statusbar(self) -> None:
        statusbar = tk.Frame(self.main, bg=COLORS["sidebar"], height=30)
        statusbar.pack(side="bottom", fill="x")
        statusbar.pack_propagate(False)
        inner = tk.Frame(statusbar, bg=COLORS["sidebar"])
        inner.pack(fill="both", expand=True, padx=18)
        self.status_dot = tk.Label(inner, text="●", bg=COLORS["sidebar"],
                                   fg=COLORS["accent"], font=FONTS["tiny"])
        self.status_dot.pack(side="left")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(inner, textvariable=self.status_var, bg=COLORS["sidebar"],
                 fg=COLORS["muted"], font=FONTS["tiny"]).pack(side="left", padx=(7, 0))
        self.last_scan_var = tk.StringVar(value="SLA scan pending")
        tk.Label(inner, textvariable=self.last_scan_var, bg=COLORS["sidebar"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="right")
        tk.Label(inner, text=f"{self.db.path.name} · local only", bg=COLORS["sidebar"],
                 fg=COLORS["subtle"], font=FONTS["tiny"]).pack(side="right", padx=(0, 16))

    # --------------------------------------------------------------- lifecycle
    def _ensure_page(self, name: str) -> Any:
        if name not in self.pages:
            page_class = PAGE_CLASSES[name]
            self.pages[name] = page_class(self.page_host, self)
        return self.pages[name]

    def show_page(self, name: str) -> None:
        if name not in PAGE_META:
            return
        page = self._ensure_page(name)
        if name == self.current_page_name:
            page.on_show()
            return
        if self.current_page is not None:
            self.current_page.grid_remove()
        page.grid(row=0, column=0, sticky="nsew")
        self.current_page = page
        self.current_page_name = name
        for key, item in self.nav_items.items():
            item.set_active(key == name)
        title, subtitle = PAGE_META[name]
        self.page_title_var.set(title)
        self.page_subtitle_var.set(subtitle)
        page.on_show()

    def refresh_current(self) -> None:
        if self.current_page:
            try:
                self.current_page.on_show()
                self.set_status("View refreshed.", "info")
            except Exception as exc:
                self.set_status(f"Refresh failed: {exc}", "error")

    def _shortcut_new_ticket(self) -> None:
        self.show_page("tickets")
        page = self.pages.get("tickets")
        if page:
            self.root.after(80, page.open_create)

    def _shortcut_search(self) -> None:
        self.show_page("tickets")
        page = self.pages.get("tickets")
        if page:
            self.root.after(80, page.focus_search)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-n>", lambda _event: self._shortcut_new_ticket())
        self.root.bind_all("<Control-f>", lambda _event: self._shortcut_search())
        self.root.bind_all("<F5>", lambda _event: self.refresh_current())
        self.root.bind_all("<Control-r>", lambda _event: self.refresh_current())
        for index, (key, _label, _icon) in enumerate(NAV_ITEMS, start=1):
            self.root.bind_all(
                f"<Alt-Key-{index}>",
                lambda _event, page_key=key: self.show_page(page_key),
            )

    def open_ticket_details(self, ticket_id: str,
                            on_changed: Callable[[], None] | None = None) -> None:
        try:
            self.services["tickets"].get_ticket(ticket_id)
        except NotFoundError:
            self.set_status(
                f"Ticket {ticket_id} no longer exists; historical audit data is still available.",
                "warning",
            )
            return
        parent = self.current_page or self.root

        def changed() -> None:
            if on_changed:
                on_changed()
            self.update_sidebar_status()

        TicketDetailsDialog(
            parent,
            self.services["tickets"],
            self.services["sla"],
            self.services["audit"],
            self.services["escalations"],
            ticket_id,
            on_changed=changed,
        )

    # ------------------------------------------------------------------ scans
    def run_escalation_scan(self, silent: bool = False) -> list[Any]:
        try:
            events = self.services["escalations"].run()
        except Exception as exc:
            logger.exception("Escalation scan failed")
            if not silent:
                self.set_status(f"Escalation scan failed: {exc}", "error")
            return []
        self._last_scan = utc_now()
        self.last_scan_var.set(f"Last SLA scan {format_local(self._last_scan, '%H:%M:%S')}")
        self.update_sidebar_status()
        if events:
            self.set_status(
                f"SLA scan recorded {len(events)} new escalation(s) · internal only.",
                "warning",
            )
        elif not silent:
            self.set_status("SLA scan complete · no new escalations.", "success")
        if self.current_page_name in ("dashboard", "escalations", "sla"):
            try:
                self.current_page.on_show()
            except Exception:
                logger.exception("Could not refresh page after SLA scan")
        return events

    def run_scan_from_topbar(self) -> None:
        self.run_escalation_scan(silent=False)

    def _schedule_scan(self) -> None:
        self._timers.append(self.root.after(60000, self._scheduled_scan))

    def _scheduled_scan(self) -> None:
        self.run_escalation_scan(silent=True)
        self._schedule_scan()

    def _tick_clock(self) -> None:
        now = datetime.now()
        self.clock_var.set(now.strftime("%a %d %b  ·  %H:%M:%S"))
        self._timers.append(self.root.after(1000, self._tick_clock))

    # ------------------------------------------------------------------ status
    def set_status(self, message: str, level: str = "info") -> None:
        colors = {
            "info": COLORS["accent"],
            "success": COLORS["green"],
            "warning": COLORS["amber"],
            "error": COLORS["red"],
        }
        self.status_var.set(message)
        self.status_dot.configure(fg=colors.get(level, COLORS["accent"]))

    def update_sidebar_status(self) -> None:
        try:
            counts = self.db.counts()
            self.sidebar_counts_var.set(
                f"{counts['tickets']} tickets · {counts['escalations']} escalations\n"
                f"{counts['audit_events']} audit events"
            )
        except Exception:
            self.sidebar_counts_var.set("Database status unavailable")

    def notify_data_changed(self) -> None:
        self.update_sidebar_status()

    def _report_exception(self, exc_type: type, value: BaseException, tb: Any) -> None:
        logger.error("Unhandled UI exception", exc_info=(exc_type, value, tb))
        details = "".join(traceback.format_exception(exc_type, value, tb))
        logger.error(details)
        try:
            self.set_status(f"Unexpected error: {value}", "error")
            messagebox.showerror(
                "OpsFlow encountered an error",
                f"{value}\n\nDetails were written to the OpsFlow log.",
                parent=self.root,
            )
        except tk.TclError:
            pass

    def close(self) -> None:
        for timer in self._timers:
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass
        self._timers.clear()
        self.root.destroy()
