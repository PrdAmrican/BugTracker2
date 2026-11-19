# Beta Tester Bug Tracker

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

A small, self-hosted bug tracker for beta-testing programs, built with Flask and SQLite. No database server needed — everything lives in one `bugs.db` file plus an `uploads/` folder.

**Version 2.0** — see [CHANGELOG.md](CHANGELOG.md) for what's new and [Upgrading from v1](#upgrading-from-v1).

## Features

- **Sign-in with roles** — testers report and work on bugs; admins also manage people, dropdown values and backups.
- **Dashboard** — active and critical counts, bugs reported/resolved this week, status and severity breakdowns, active bugs per SW build, your assigned bugs and a live activity feed.
- **Bug list** — search (title, description, TG or `#id`), status tabs, filters by severity, assignee (incl. "me" and "unassigned"), reporter, device, build and mode, sortable columns, pagination and CSV export of whatever you're looking at.
- **Bug pages** — comments, a full change history ("Alice changed status: Open → Resolved"), one-click status/assignee changes, *Fixed in build*, previous/next navigation and "report another on this setup".
- **Beta-testing fields** — Device, SW Build and Mode dropdowns (add new values inline from the form), plus a free-text TG field. Old builds can be archived so they stop cluttering the form without losing history.
- **Attachments** — upload several files at once, drag and drop, or paste a screenshot straight from the clipboard. Screenshots, screen recordings (mp4/mov/webm), logs, PDFs and ZIPs.
- **Backup & restore** — full backup ZIP (data + attachment files), JSON, CSV spreadsheets and a consistent SQLite copy. Restores are validated first, run in one transaction and take an automatic snapshot beforehand. v1 backups import too.
- **About page** with version, creator, license and a link to the source code (visible without signing in).
- **Dark mode**, works on phones, and shows times in each viewer's own time zone.

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/PrdAmrican/BugTracker2.git
cd BugTracker2

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. The first visit asks you to create the admin account. Then add your testers under **Testers** — give them a temporary password if they should sign in, or leave it blank to just track them as reporters/assignees.

### One-click start on Windows

- **`Bug Tracker.vbs`** — double-click to start the app with no window at all and open it in your browser. Put a shortcut to it on the desktop, or in the Startup folder (`Win+R` → `shell:startup`) to start it when you log in.
- **`start_bugtracker.bat`** — the same, but shows a small window while it starts (handy for seeing errors).
- **`stop_bugtracker.bat`** — stops the background server.

They use the `venv` folder if there is one (otherwise Python on your PATH), install missing packages on the first run, and run the app with Waitress in the background. Server output goes to `logs\server.log`. If the app is already running, they just open the page. To use a different port, or to let other computers on your network connect (`HOST=0.0.0.0`), edit the two lines at the top of `start_bugtracker.bat`.

## Upgrading from v1

Your existing data upgrades itself — nothing to export or convert.

1. Stop the app and make a copy of `bugs.db` and `uploads/` (just in case).
2. Download this repository into a new folder (or replace the old files with these) and run `pip install -r requirements.txt` — v2 adds Flask-Login and Flask-WTF. If you use a new folder, copy `bugs.db` and `uploads/` into it.
3. Start the app. On first start it adds the new columns and tables to `bugs.db`, cleans up links to testers that v1 deleted, and keeps all bugs, testers, dropdown values and attachments.
4. Open the app. Because v1 had no logins, it asks you to create an admin. **Use your own tester email** and that existing record becomes the admin.
5. Under **Testers**, use *Edit* to give a password to each tester who should sign in.

Old JSON exports from v1 can be restored on the **Backup** page as well.

## Configuration

Everything is optional and set through environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `BUGTRACKER_DATA_DIR` | the project folder | Where `bugs.db`, `uploads/` and `backups/` live |
| `DATABASE_URL` | SQLite in the data folder | SQLAlchemy database URL |
| `BUGTRACKER_UPLOAD_DIR` | `<data dir>/uploads` | Attachment folder |
| `BUGTRACKER_SECRET_KEY` | generated once, saved to `<data dir>/.secret_key` | Signs session cookies |
| `BUGTRACKER_MAX_UPLOAD_MB` | `25` | Upload size limit per request |
| `BUGTRACKER_MAX_RESTORE_MB` | `1024` | Size limit for restoring a full backup |
| `BUGTRACKER_SECURE_COOKIES` | `0` | Set to `1` when the site is served over HTTPS |
| `BUGTRACKER_HOST` / `BUGTRACKER_PORT` | `127.0.0.1` / `5000` | For `python app.py` |
| `FLASK_DEBUG` | `0` | `1` turns on the debugger (development only) |
| `BUGTRACKER_SOURCE_URL` | this GitHub repository | "Source code" link in the footer (set it if you run a modified copy) |

## Command-line tools

```bash
flask --app bugtracker create-admin           # create or promote an admin
flask --app bugtracker set-password           # reset a forgotten password
flask --app bugtracker backup backup.zip      # full backup, e.g. from a scheduled job
flask --app bugtracker restore backup.zip     # restore a JSON or full-backup ZIP
```

## Project structure

```
BugTracker2/
├── app.py                  # entry point (python app.py / waitress app:app)
├── bugtracker/
│   ├── __init__.py         # app factory, request hooks, template helpers
│   ├── config.py           # settings from environment variables
│   ├── models.py           # database models
│   ├── migrations.py       # automatic in-place upgrades (v1 → v2)
│   ├── services.py         # validation, history logging, file handling
│   ├── backup.py           # export / validated import
│   ├── cli.py              # flask commands
│   ├── views/              # auth, dashboard, bugs, people, settings, backup
│   ├── templates/
│   └── static/
├── tests/                  # pytest suite
├── requirements.txt
└── DEPLOYMENT.md
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use a temporary folder for their database and files, so they never touch your real `bugs.db`.

## Production

See [DEPLOYMENT.md](DEPLOYMENT.md) for running with Waitress or Gunicorn, as a service, behind Nginx, and for moving to another server.

## Author

Created by **[PrdAmrican](https://github.com/PrdAmrican)**.

## License

Copyright © 2026 PrdAmrican

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU Affero General Public License** as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [LICENSE](LICENSE) file for the full text.

**Running a modified version?** The AGPL asks that people using it over a network can get your modified source code. The footer of every page links to the source; point it at your copy by setting `BUGTRACKER_SOURCE_URL`.
