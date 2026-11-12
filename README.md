# OpsFlow

OpsFlow is a fully offline, Python-only desktop application for operations ticket
management. It combines a ticket queue, deterministic SLA tracking, escalation
history, an immutable audit trail, analytics, and validated CSV import/export in a
single dark-themed Tkinter application.

There is no web stack, no JavaScript, no cloud dependency, no AI/LLM integration,
and no external notification channel. Everything runs locally against SQLite.

> This repository is the **Python/Tkinter desktop application only**. The separate
> OpsFlow Mobile PWA is a different product, lives in a different repository, and is
> not part of this codebase.

## Requirements

- Python **3.11 or newer** (developed and tested on Python 3.12.10)
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

## Project structure

```
opsflow-desktop/
├── main.py                    # entry point, CLI and logging setup
├── config.py                  # app metadata and data-directory resolution
├── database.py                # SQLite schema, transactions, backup and migration
├── models.py                  # enums, dataclasses, time and formatting helpers
├── requirements.txt           # no third-party runtime dependencies
├── README.md
├── .gitignore
├── services/
│   ├── audit_service.py       # append-only audit history
│   ├── sla_engine.py          # policies, deadline evaluation, compliance
│   ├── ticket_service.py      # ticket CRUD, comments, status/assignment
│   ├── escalation_engine.py   # scan, deduplicate and record escalations
│   ├── analytics.py           # dashboard metrics and SLA reports
│   └── csv_service.py         # validated import and report export
├── ui/
│   ├── app.py                 # shell, sidebar, shortcuts, scheduled scans
│   ├── theme.py               # dark navy/cyan theme and ttk styles
│   ├── components.py          # cards, responsive tables, charts, scrollers
│   ├── dashboard.py
│   ├── tickets.py
│   ├── sla.py
│   ├── escalations.py
│   ├── audit.py
│   ├── data.py
│   └── dialogs.py             # create/edit/assign/status/note/detail dialogs
├── tests/                     # unittest suite (84 tests)
└── sample_data/
    ├── operations_import.csv  # valid import example
    ├── import_template.csv    # header and one example row
    └── invalid_import.csv     # demonstrates per-row rejection reporting
```

## CSV import

The importer requires `title`, `requester`, and `priority` columns. It accepts
aliases such as `summary`, `requested_by`, `owner`, `type`, `created`, and
`resolution_due`, ignores unknown columns with a warning, and validates each row
independently so one bad row does not block the rest. Duplicate ticket IDs are
skipped. Timestamps accept ISO/date forms such as `2026-05-01 14:30`.

Use `sample_data/operations_import.csv` for a valid demonstration and
`sample_data/invalid_import.csv` to see the validation report. The app can also
write a fresh template from the Data exchange page.

## Tests

Run the full suite from the project root:

```powershell
python -m unittest discover -v
```

The suite covers models, database initialization/migration/backup, ticket
lifecycle, SLA evaluation and compliance, escalation deduplication, audit history,
analytics, CSV import/export validation, and a Tkinter UI smoke test.

## Known limitations

- The application is single-user and local; it does not synchronize between
  machines and intentionally sends no email, chat, or webhook notifications.
- CSV import is transactional per successful row, not as one all-or-nothing batch;
  valid rows are kept while invalid rows are reported.
- The audit trail is append-only from the UI, but a user with direct filesystem
  access to the SQLite file could modify it.
- Timestamps are stored in UTC and rendered in the machine's local timezone; the
  UI does not offer per-user timezone selection.
- Charts are lightweight Canvas renderings intended for operational summaries, not
  a full BI/exporting visualization tool.
- Scheduled scans run while the application is open only; a closed app does not
  raise escalations in the background.
- Ticket deletion is permanent for the ticket and its comments; audit and
  escalation records are preserved by design.
