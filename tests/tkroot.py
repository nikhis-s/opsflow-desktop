"""Shared Tk root for the UI test session.

Tcl tears down global interpreter state when the last Tk root is destroyed.
Creating a second root in the same process can then fail with
``invalid command name tcl_findLibrary`` or "Can't find a usable init.tcl".
Every UI test therefore shares a single root and destroys only the widgets
it created.
"""
from __future__ import annotations

import sys
import tkinter as tk

_root: tk.Tk | None = None
_unavailable_reason: str = ""

#: The Tk dialog tests do not complete on GitHub's macOS runners - the
#: deferred focus handling never returns there, so the GUI suite runs on
#: Linux (Xvfb) and Windows instead. macOS still runs the headless suite.
#: The application itself launches fine on macOS: tools/smoke_launch.py runs
#: there as part of the launch job.
GUI_TESTS_SUPPORTED = sys.platform != "darwin"


def get_root() -> tk.Tk | None:
    """Return the shared Tk root, or ``None`` when no display is available."""
    global _root, _unavailable_reason
    if _root is not None:
        return _root
    try:
        _root = tk.Tk()
    except Exception as exc:  # pragma: no cover - headless display
        _unavailable_reason = str(exc).splitlines()[0] if str(exc) else repr(exc)
        return None
    _root.withdraw()
    return _root


def unavailable_reason() -> str:
    """Explain why the shared root could not be created."""
    return _unavailable_reason or "tkinter is not available"
