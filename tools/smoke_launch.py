"""Launch the desktop application, verify the window, and close it.

Run by CI on every supported platform to prove that the native GUI really
starts, renders every page and shuts down cleanly - not just that the unit
tests pass.

    python tools/smoke_launch.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXPECTED_TITLE = "Operations & SLA Management"
MIN_WIDTH = 800
MIN_HEIGHT = 600


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="opsflow-smoke-") as tmp:
        os.environ["OPSFLOW_DATA_DIR"] = tmp
        os.environ["OPSFLOW_DB_PATH"] = str(Path(tmp) / "opsflow.db")

        from database import Database

        db = Database(Path(tmp) / "opsflow.db")
        db.initialize()

        root = tk.Tk()
        from ui.app import NAV_ITEMS, OpsFlowApp

        app = OpsFlowApp(root, db)
        root.update_idletasks()
        root.update()

        title = root.title()
        print(f"window title    : {title}")
        if EXPECTED_TITLE not in title:
            print(f"FAIL: unexpected window title {title!r}")
            return 1

        width = root.winfo_width()
        height = root.winfo_height()
        print(f"window geometry : {width}x{height}")
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            print(f"FAIL: window is smaller than {MIN_WIDTH}x{MIN_HEIGHT}")
            return 1

        for key, _label, _icon in NAV_ITEMS:
            app.show_page(key)
            root.update_idletasks()
            root.update()
            page = app.pages[key]
            if not page.winfo_ismapped():
                print(f"FAIL: page {key} did not render")
                return 1
            print(f"  page {key:<12} ok ({page.winfo_width()}x{page.winfo_height()})")

        app.close()
        try:
            root.update()
        except tk.TclError:
            pass

    print("PASS: application launched, rendered every page and closed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
