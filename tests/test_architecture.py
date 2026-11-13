"""Architecture tests: the layer boundaries are enforced, not just documented.

These are static checks over the source tree. They fail the moment a module
reaches across a layer boundary, so the layering described in the README
cannot quietly rot as the code grows.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A string literal only counts as SQL if it has real statement structure,
#: so ordinary UI copy such as "Update status" is not a false positive.
SQL_LITERAL = re.compile(
    r"\b(SELECT\s+.+?\s+FROM\s|INSERT\s+INTO\s|UPDATE\s+\w+\s+SET\s|"
    r"DELETE\s+FROM\s|CREATE\s+TABLE\s|DROP\s+TABLE\s|ALTER\s+TABLE\s)",
    re.IGNORECASE | re.DOTALL,
)


def _modules(relative: str) -> list[Path]:
    return sorted(
        path for path in (ROOT / relative).rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imported_names(path: Path) -> set[str]:
    """Return the top-level module names imported by a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            names.add(node.module.split(".")[0])
    return names


def _sql_literals(path: Path) -> list[tuple[int, str]]:
    """Return the SQL-looking string literals in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if SQL_LITERAL.search(node.value):
                found.append((node.lineno, node.value.strip()[:60]))
    return found


def _calls_named(path: Path, attribute: str) -> list[int]:
    """Return the line numbers of calls to ``.<attribute>(...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == attribute):
            lines.append(node.lineno)
    return lines


class LayeringTests(unittest.TestCase):
    """The domain must not depend on the presentation layer, and vice versa."""

    def test_domain_layer_does_not_import_the_ui(self) -> None:
        domain = [ROOT / "models.py", ROOT / "database.py", *_modules("services")]
        for path in domain:
            self.assertNotIn(
                "ui", _imported_names(path),
                f"{path.relative_to(ROOT)} must not import the ui package",
            )

    def test_domain_layer_does_not_import_tkinter(self) -> None:
        domain = [ROOT / "models.py", ROOT / "database.py", *_modules("services")]
        for path in domain:
            self.assertNotIn(
                "tkinter", _imported_names(path),
                f"{path.relative_to(ROOT)} must not import tkinter",
            )

    def test_models_has_no_infrastructure_dependencies(self) -> None:
        """models.py is pure domain: no I/O layer, no service layer."""
        imports = _imported_names(ROOT / "models.py")
        for forbidden in ("services", "database", "ui", "sqlite3"):
            self.assertNotIn(
                forbidden, imports,
                f"models.py must not import {forbidden}",
            )

    def test_ui_layer_contains_no_sql(self) -> None:
        for path in _modules("ui"):
            relative = path.relative_to(ROOT)
            self.assertNotIn(
                "sqlite3", _imported_names(path),
                f"{relative} must not import sqlite3",
            )
            self.assertEqual(
                _sql_literals(path), [],
                f"{relative} must not contain SQL statements",
            )
            self.assertEqual(
                _calls_named(path, "execute"), [],
                f"{relative} must not execute SQL directly",
            )


class PublicApiTests(unittest.TestCase):
    """Guard the public surface that other modules import."""

    def test_dialogs_package_exports_every_dialog(self) -> None:
        import ui.dialogs as dialogs

        expected = {
            "AssignDialog",
            "BaseDialog",
            "CommentDialog",
            "ConfirmDialog",
            "ImportSummaryDialog",
            "StatusDialog",
            "TicketDetailsDialog",
            "TicketDialog",
        }
        self.assertEqual(expected - set(dialogs.__all__), set())
        for name in expected:
            self.assertTrue(hasattr(dialogs, name), f"ui.dialogs.{name} is missing")

    def test_components_exports_its_shared_widgets(self) -> None:
        import ui.components as components

        for name in ("Badge", "Card", "DataTable", "KpiCard", "Meter", "Page",
                     "ScrollableFrame", "SectionHeader", "flat_button"):
            self.assertTrue(hasattr(components, name), f"ui.components.{name} is missing")


if __name__ == "__main__":
    unittest.main()
