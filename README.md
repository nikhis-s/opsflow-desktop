# OpsFlow

[![CI](https://github.com/nikhis-s/opsflow-desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/nikhis-s/opsflow-desktop/actions/workflows/ci.yml)

OpsFlow is a fully offline, Python-only desktop application for operations ticket
management. It combines a ticket queue, deterministic SLA tracking, escalation
history, an append-only audit trail, analytics, and validated CSV import/export in a
single dark-themed Tkinter application.

There is no web stack, no JavaScript, no cloud dependency, no AI/LLM integration,
and no external notification channel. Everything runs locally against SQLite.

## Requirements

- Python **3.11 or newer** (developed on 3.12.10; CI covers 3.11 and 3.12 on
  Linux, Windows and macOS)
- Tkinter, included with the standard Windows/macOS Python installers and available
  through the `python3-tk` package on most Linux distributions
- No third-party packages are required at runtime

## Launch

From the project root:

```powershell
python main.py
```

Optional command-line flags:

```powershell
python main.py --db C:\path\to\opsflow.db          # use a specific database
python main.py --data-dir C:\path\to\opsflow-data  # override the app data folder
python main.py --check                             # initialize, print diagnostics, exit
python main.py --version
```

The application creates its data directory automatically:

| Platform | Default location |
| --- | --- |
| Windows | `%APPDATA%\OpsFlow` |
| macOS | `~/Library/Application Support/OpsFlow` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/OpsFlow` |

Environment overrides: `OPSFLOW_DATA_DIR`, `OPSFLOW_DB_PATH`, and `OPSFLOW_ACTOR`
(the operator name written to audit entries). The database file lives in the data
directory, with timestamped backups in `backups/` and a rotating `opsflow.log`.
If an existing database is opened, a backup is made before any schema migration.

## Features

- **Ticket queue** — create, edit, assign, change status, add internal notes,
  delete, search, filter by priority/status/assignee, and sort six ways.
- **SLA center** — configurable response and resolution targets per priority,
  warning thresholds, live countdowns, at-risk/breached detection, compliance
  reporting, and deadline recalculation for existing tickets.
- **Escalations** — deterministic internal escalation detection with deduplication,
  reasons, watchlist, history, and automatic scans every 60 seconds plus manual and
  startup scans. No messages are sent outside the application.
- **Audit trail** — searchable, filterable, exportable record of ticket creation,
  edits, assignment, status/priority changes, notes, SLA events, imports and
  escalations. History survives ticket deletion.
- **Dashboard** — KPI cards, native Canvas donut/bar/trend charts, at-risk
  watchlist, and recent activity.
- **Data exchange** — validated CSV import with per-row error reporting, duplicate
  skipping, template generation, and ticket/SLA/escalation/audit exports.
- **Resilience** — parameterized SQL, transactions, foreign keys, indexes,
  timezone-aware timestamps, tables that scale their columns to the window with a
  horizontal-scroll fallback, backups before migration, and graceful startup error
  handling.

## Desktop interface

The window is built for a real operations desk rather than a demo shell.

- **DPI aware** — the app opts into per-monitor DPI awareness on Windows before
  Tk starts, so text and charts stay crisp instead of being bitmap-scaled. A
  single scale factor derived from the display DPI (`ui/theme.py: px()`) drives
  every spacing, control height, table row height, canvas geometry and dialog
  size, so the layout keeps its proportions from 96 DPI up to 4K.
- **Fits the screen** — window and dialog dimensions are clamped to the
  available display area, and every page scrolls when its content is taller than
  the viewport, so nothing is ever cut off on a 1366×768 laptop.
- **Smart mouse wheel** — a table scrolls itself first and hands the wheel to
  the page scroller once it reaches its limit, so a full-height table never
  traps the pointer.
- **Live canvas charts** — the donut, priority-bar and trend charts are drawn
  with Tk's `Canvas` at runtime and re-render on resize; there are no image
  assets to ship or blur.
- **Keyboard driven** — `Ctrl+N` new ticket, `Ctrl+F` focus search, `F5` or
  `Ctrl+R` refresh, `Alt+1`–`Alt+6` jump between pages.

## Project structure

```
opsflow/
├── main.py                    # entry point, CLI and logging setup
├── config.py                  # app metadata and data-directory resolution
├── database.py                # SQLite schema, transactions, backup and migration
├── models.py                  # enums, dataclasses, time and formatting helpers
├── pyproject.toml             # project metadata, ruff and mypy configuration
├── requirements.txt           # no third-party runtime dependencies
├── requirements-dev.txt       # pytest, ruff, mypy (development only)
├── README.md
├── LICENSE
├── .gitignore
├── .github/workflows/ci.yml   # lint, type check, tests and launch smoke test
├── services/
│   ├── audit_service.py       # append-only audit history
│   ├── sla_engine.py          # policies, deadline evaluation, compliance
│   ├── ticket_service.py      # ticket CRUD, comments, status/assignment
│   ├── escalation_engine.py   # scan, deduplicate and record escalations
│   ├── analytics.py           # dashboard metrics and SLA reports
│   └── csv_service.py         # validated import and report export
├── tools/
│   └── smoke_launch.py        # launch the GUI, render every page, close it
├── ci/
│   └── run_checks.py          # run every quality gate in one command
├── ui/
│   ├── app.py                 # shell, sidebar, shortcuts, scheduled scans
│   ├── theme.py               # dark navy/cyan theme, ttk styles, DPI scaling
│   ├── components.py          # cards, responsive tables, charts, scrollers
│   ├── dashboard.py
│   ├── tickets.py
│   ├── sla.py
│   ├── escalations.py
│   ├── audit.py
│   ├── data.py
│   └── dialogs/               # modal dialogs, one module per concern
│       ├── base.py            # themed frame, header, footer, shared widgets
│       ├── ticket.py          # create / edit ticket
│       ├── workflow.py        # assign, change status, add note
│       ├── confirm.py         # destructive-action confirmation
│       ├── import_summary.py  # CSV import report
│       └── details.py         # ticket details, SLA meters, activity
├── tests/                     # unittest suite (99 tests)
└── sample_data/
    ├── operations_import.csv  # valid import example
    ├── import_template.csv    # header and one example row
    └── invalid_import.csv     # demonstrates per-row rejection reporting
```

## Architecture

The code is layered so that the domain logic never imports Tkinter. That is what
makes the whole rule set testable without a display.

| Layer | Module | Responsibility |
| --- | --- | --- |
| Domain | `models.py` | enums, dataclasses, UTC time handling and formatting |
| Persistence | `database.py` | schema, migrations, transactions, backups, health |
| Services | `services/` | ticket lifecycle, SLA evaluation, escalation detection, audit, CSV, analytics |
| Presentation | `ui/` | the Tkinter shell, pages, components and dialogs |
| Entry point | `main.py` | CLI parsing, logging, DPI setup, application wiring |

Two rules keep the layers honest, and both are enforced by
`tests/test_architecture.py` — the checks fail the moment a module reaches
across a boundary:

- **`services/` never imports `ui/` or `tkinter`.** The domain rules are
  exercised directly by the unit tests, with no window in sight.
- **`ui/` never writes SQL.** Pages call services; services own the queries.

## CSV import

The importer requires `title`, `requester`, and `priority` columns. It accepts
aliases such as `summary`, `requested_by`, `owner`, `type`, `created`, and
`resolution_due`, ignores unknown columns with a warning, and validates each row
independently so one bad row does not block the rest. Duplicate ticket IDs are
skipped. Timestamps accept ISO/date forms such as `2026-05-01 14:30`.

Use `sample_data/operations_import.csv` for a valid demonstration and
`sample_data/invalid_import.csv` to see the validation report. The app can also
write a fresh template from the Data exchange page.

## Development

The application itself has no third-party runtime dependencies. Development and
CI tooling is installed separately:

```powershell
python -m pip install -r requirements-dev.txt
```

| Command | What it checks |
| --- | --- |
| `python ci/run_checks.py` | **every check below, in one command** |
| `python -m pytest -q` | the full test suite |
| `python -m unittest discover -q` | the same suite through the stdlib runner |
| `ruff check .` | lint (configured in `pyproject.toml`) |
| `mypy --platform linux` | static type checking for Linux |
| `mypy --platform win32` | static type checking for Windows |
| `mypy --platform darwin` | static type checking for macOS |
| `python main.py --check` | database initialization and health diagnostics |
| `python tools/smoke_launch.py` | launches the real window, renders every page, closes it |

`ruff` and `mypy` are both clean on the current tree, on all three platforms.

## Tests

Run the full suite from the project root:

```powershell
python -m unittest discover -v
```

The suite covers models, database initialization/migration/backup, ticket
lifecycle, SLA evaluation and compliance, escalation deduplication, audit history,
analytics, CSV import/export validation, the Tkinter UI layer, and the
architecture rules above. The UI tests build the real application shell, open
every page, exercise an SLA scan, check mouse-wheel routing and construct every
modal dialog to confirm it opens, lays itself out within the screen bounds and
closes cleanly.

The suite needs no display server beyond a normal desktop session. On a headless
Linux box it runs under `xvfb-run`.

The Tk GUI tests run on **Linux (Xvfb) and Windows**. GitHub's macOS runners do
not complete the deferred-focus path in the dialog tests, so macOS runs the
headless suite and is covered by the launch job instead, which starts the real
application there. The skip is declared once, in `tests/tkroot.py`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **quality** — `ruff check`, plus `mypy` run separately for the Linux, Windows
  and macOS targets. Platform-specific APIs such as `os.startfile` and
  `ctypes.windll` only exist on some platforms, so checking one platform
  would hide real errors on the others.
- **test** — `pytest` and `unittest` across Python 3.11 and 3.12 on Ubuntu,
  Windows and macOS, plus the `main.py --check` diagnostics.
- **launch** — `tools/smoke_launch.py` starts the real desktop application on
  each platform and verifies the window, every page and a clean shutdown.

The same gates run locally with one command:

```powershell
python ci/run_checks.py
```

## Known limitations

- The application is single-user and local; it does not synchronize between
  machines and intentionally sends no email, chat, or webhook notifications.
- CSV import is transactional per successful row, not as one all-or-nothing batch;
  valid rows are kept while invalid rows are reported.
- The audit trail is append-only through the application layer, but a user with
  direct filesystem access to the SQLite file could modify it.
- Timestamps are stored in UTC and rendered in the machine's local timezone; the
  UI does not offer per-user timezone selection.
- Charts are lightweight Canvas renderings intended for operational summaries, not
  a full BI/exporting visualization tool.
- Scheduled scans run while the application is open only; a closed app does not
  raise escalations in the background.
- Ticket deletion is permanent for the ticket and its comments; audit and
  escalation records are preserved by design.
