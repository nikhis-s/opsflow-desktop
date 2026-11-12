"""Application configuration and platform-specific data locations."""
from __future__ import annotations

import getpass
import os
from pathlib import Path

APP_NAME = "OpsFlow"
APP_VERSION = "1.1.0"
DEFAULT_ACTOR = os.environ.get("OPSFLOW_ACTOR") or getpass.getuser() or "Operator"


def get_data_dir() -> Path:
    """Return the per-user directory used for the database and backups."""
    override = os.environ.get("OPSFLOW_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = base / APP_NAME
    elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_backup_dir() -> Path:
    path = get_data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    override = os.environ.get("OPSFLOW_DB_PATH")
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return get_data_dir() / "opsflow.db"


def get_log_path() -> Path:
    return get_data_dir() / "opsflow.log"
