"""Run every quality gate in one command.

This is the same set of checks the CI workflow runs, packaged so that they
can be executed locally, in a container, or on any CI provider:

    python ci/run_checks.py

Exit code is 0 only when every check passes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, command: list[str]) -> bool:
    print(f"\n=== {label} ===")
    print(f"$ {' '.join(command)}\n")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode == 0:
        print(f"PASS: {label}")
        return True
    print(f"FAIL: {label} (exit {result.returncode})")
    return False


def main() -> int:
    checks: list[tuple[str, list[str]]] = [
        ("Lint (ruff)", [sys.executable, "-m", "ruff", "check", "."]),
        ("Type check (mypy)", [sys.executable, "-m", "mypy"]),
        ("Tests (pytest)", [sys.executable, "-m", "pytest", "-q"]),
        ("Tests (unittest)", [sys.executable, "-m", "unittest", "discover", "-q"]),
        ("Application self-check", [sys.executable, "main.py", "--check"]),
        ("Native launch", [sys.executable, "tools/smoke_launch.py"]),
    ]

    results: list[tuple[str, bool]] = []
    for label, command in checks:
        results.append((label, run(label, command)))

    print("\n" + "=" * 60)
    failed = [label for label, ok in results if not ok]
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("=" * 60)
    if failed:
        print(f"\n{len(failed)} check(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
