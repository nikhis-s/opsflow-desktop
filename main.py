"""OpsFlow desktop application entry point.

Run with:
    python main.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import APP_NAME, APP_VERSION, get_log_path
from database import Database, DatabaseError


def configure_logging() -> None:
    try:
        log_path = get_log_path()
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except OSError:
        logging.basicConfig(level=logging.INFO)


def _show_startup_error(title: str, message: str) -> None:
    print(f"{title}\n{message}", file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="opsflow",
        description="OpsFlow — offline operations and SLA management desktop app.",
    )
    parser.add_argument("--db", help="override the SQLite database path")
    parser.add_argument("--data-dir", help="override the OpsFlow application data directory")
    parser.add_argument("--check", action="store_true",
                        help="initialize the database, print diagnostics and exit")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["OPSFLOW_DATA_DIR"] = args.data_dir
    if args.db:
        os.environ["OPSFLOW_DB_PATH"] = args.db

    configure_logging()
    logger = logging.getLogger("opsflow")
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)

    try:
        db = Database()
        db.initialize()
    except Exception as exc:
        logger.exception("Database initialization failed")
        _show_startup_error(
            "OpsFlow could not start",
            "The OpsFlow database could not be initialized.\n\n"
            f"{exc}\n\n"
            "If an existing database is present, a backup may have been created in the "
            "application data folder. Check the log for details.",
        )
        return 1

    if args.check:
        counts = db.counts()
        print(f"{APP_NAME} {APP_VERSION}")
        print(f"Database: {db.path}")
        print(f"Schema: v{db.schema_version}")
        print(f"Health: {db.health()}")
        print(
            "Tickets: {tickets} | Comments: {comments} | Audit events: {audit_events} | "
            "Escalations: {escalations}".format(**counts)
        )
        return 0

    try:
        import tkinter as tk
        from ui.app import OpsFlowApp
        root = tk.Tk()
        OpsFlowApp(root, db)
        root.mainloop()
        return 0
    except Exception as exc:
        logger.exception("Application failed")
        _show_startup_error(
            "OpsFlow encountered a startup error",
            f"{exc}\n\nSee {get_log_path()} for details.",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
