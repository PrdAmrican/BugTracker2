# Changelog

## 2.0.0 — 2026-11-18

A rewrite of the whole app. Existing v1 databases, uploads and JSON backups carry over automatically (see *Upgrading from v1* in the README).

### New
- **Sign-in and roles.** First-run setup creates an admin; testers can have a login or just be tracked by name. Admins manage people, settings and backups; testers can delete only their own bugs, comments and files.
- **Comments and change history** on every bug, plus an activity feed on the dashboard.
- **Search, more filters and sorting** on the bug list: free text and `#id`, status tabs (Active / Done …), assignee "me"/"unassigned", reporter, device, build, mode; sortable columns, pagination, CSV export of the current view.
- **New statuses** *Needs Info* and *Won't Fix*, a **Fixed in build** field and a resolved date.
- **Quick actions** on the bug page: change status or assignee, *Assign to me*, *Report another on this setup*, previous/next bug.
- **Settings page** to rename, archive (hide from new bugs) or delete devices, SW builds and modes; add several at once.
- **Better attachments:** several files at once, drag and drop, paste screenshots from the clipboard, video and JSON/CSV/XML files, sizes and uploader recorded.
- **Full backup ZIP** that includes attachment files; restores accept it, v2 JSON and v1 JSON.
- **Dashboard** rebuilt: active/critical counts, weekly reported/resolved, status, severity and per-build breakdowns, "Assigned to me".
- **About page** with version, creator, license, source link and the libraries used; admins also see system details.
- Dark mode, phone-friendly layout, local time display.
- `flask --app bugtracker create-admin | set-password | backup | restore` commands.

### Fixed
- The test suite wrote to (and wiped) the real `bugs.db`: it set `DATABASE_URL`, which the app ignored. Tests now run against a temporary folder.
- Restoring a backup deleted everything *before* reading the new data, so a bad file could leave the tracker empty. Imports are now validated first, run in one transaction and take a snapshot beforehand.
- Deleting a tester left bugs pointing at a missing person; the upgrade cleans those up and deletes now unlink properly.
- A non-numeric assignee in the URL caused a server error; all filters now ignore bad values.
- Invalid severity/status values and dropdown ids that don't exist were saved as-is; they are now rejected.
- The new-bug form lost everything you typed when the title was missing.
- Forms had no CSRF protection; all forms and the inline "add" buttons are now protected.
- The secret key was hard-coded and the dev server always ran in debug mode.
- The raw database download could copy a file mid-write; it now uses SQLite's backup API.

### Changed
- Licensed under the **GNU AGPL v3 or later** (see `LICENSE`); creator credit and a source-code link in every page footer.
- Code is organised as a `bugtracker` package with blueprints; `app.py` remains the entry point, so `python app.py` and `waitress-serve app:app` work as before.
- Default upload limit raised from 16 MB to 25 MB (configurable).
- Attachment URLs are now `/attachments/<id>/<name>`; old `/uploads/<file>` links redirect.

## 1.0.0

Initial version: dashboard, bugs with Device / SW Build / Mode / TG fields, testers, attachments, JSON/CSV/SQLite backup.
