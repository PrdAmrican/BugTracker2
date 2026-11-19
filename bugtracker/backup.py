# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Export and import of the whole tracker.

Formats
-------
* JSON — every table; v1 backups (no ``format_version``) import too.
* Full backup ZIP — ``data.json`` plus ``attachments/<stored name>`` files.
* CSV ZIP — one spreadsheet per table, for reading in Excel/Sheets.

Imports are validated completely before anything is touched and run in one
transaction, so a bad file can't leave the database half-replaced.
"""

import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone

from flask import current_app

from . import __version__
from .extensions import db
from .models import (
    SEVERITIES, STATUSES, ROLES, Attachment, Bug, BugEvent, Comment, Device,
    Mode, SWBuild, User,
)

FORMAT_NAME = "bug-tracker-backup"
FORMAT_VERSION = 2
SAFE_STORED_NAME = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9]+)?$")


class ImportErrorList(Exception):
    """Raised when a backup fails validation; ``errors`` lists every problem."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors[:5]) + (" …" if len(errors) > 5 else ""))


def _ts(dt):
    return dt.isoformat() if dt else None


def _parse_ts(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ── export ───────────────────────────────────────────────────────────────────

def export_data():
    def lookups(model):
        return [{"id": x.id, "name": x.name, "archived": bool(x.archived)}
                for x in model.query.order_by(model.id)]

    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "devices": lookups(Device),
        "sw_builds": lookups(SWBuild),
        "modes": lookups(Mode),
        "testers": [
            {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
             "active": bool(u.active), "password_hash": u.password_hash,
             "created_at": _ts(u.created_at), "last_login_at": _ts(u.last_login_at)}
            for u in User.query.order_by(User.id)
        ],
        "bugs": [
            {"id": b.id, "title": b.title, "description": b.description,
             "severity": b.severity, "status": b.status,
             "reported_by_id": b.reported_by_id, "assigned_to_id": b.assigned_to_id,
             "device_id": b.device_id, "sw_build_id": b.sw_build_id,
             "fixed_in_build_id": b.fixed_in_build_id, "mode_id": b.mode_id, "tg": b.tg,
             "created_at": _ts(b.created_at), "updated_at": _ts(b.updated_at),
             "resolved_at": _ts(b.resolved_at)}
            for b in Bug.query.order_by(Bug.id)
        ],
        "attachments": [
            {"id": a.id, "bug_id": a.bug_id, "filename": a.filename,
             "original_filename": a.original_filename, "uploaded_at": _ts(a.uploaded_at),
             "uploaded_by_id": a.uploaded_by_id, "size_bytes": a.size_bytes,
             "content_type": a.content_type}
            for a in Attachment.query.order_by(Attachment.id)
        ],
        "comments": [
            {"id": c.id, "bug_id": c.bug_id, "author_id": c.author_id, "body": c.body,
             "created_at": _ts(c.created_at)}
            for c in Comment.query.order_by(Comment.id)
        ],
        "bug_events": [
            {"id": e.id, "bug_id": e.bug_id, "actor_id": e.actor_id, "kind": e.kind,
             "field": e.field, "old_value": e.old_value, "new_value": e.new_value,
             "created_at": _ts(e.created_at)}
            for e in BugEvent.query.order_by(BugEvent.id)
        ],
    }


def write_full_backup(fileobj):
    """Write data.json and every attachment file into a ZIP."""
    data = export_data()
    upload_dir = current_app.config["UPLOAD_DIR"]
    missing = 0
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(data, indent=2))
        for att in data["attachments"]:
            path = os.path.join(upload_dir, att["filename"])
            if os.path.exists(path):
                zf.write(path, f"attachments/{att['filename']}")
            else:
                missing += 1
    return missing


def write_csv_zip(fileobj):
    data = export_data()
    names = {
        "testers": {u["id"]: u["name"] for u in data["testers"]},
        "devices": {x["id"]: x["name"] for x in data["devices"]},
        "sw_builds": {x["id"]: x["name"] for x in data["sw_builds"]},
        "modes": {x["id"]: x["name"] for x in data["modes"]},
    }

    def sheet(rows, columns):
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
        return "﻿" + buf.getvalue()

    bugs = []
    for b in data["bugs"]:
        row = dict(b)
        row["reported_by"] = names["testers"].get(b["reported_by_id"])
        row["assigned_to"] = names["testers"].get(b["assigned_to_id"])
        row["device"] = names["devices"].get(b["device_id"])
        row["sw_build"] = names["sw_builds"].get(b["sw_build_id"])
        row["fixed_in_build"] = names["sw_builds"].get(b["fixed_in_build_id"])
        row["mode"] = names["modes"].get(b["mode_id"])
        bugs.append(row)
    comments = [dict(c, author=names["testers"].get(c["author_id"])) for c in data["comments"]]

    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bugs.csv", sheet(bugs, [
            "id", "title", "description", "severity", "status", "reported_by", "assigned_to",
            "device", "sw_build", "fixed_in_build", "mode", "tg", "created_at", "updated_at",
            "resolved_at"]))
        zf.writestr("comments.csv", sheet(comments, ["id", "bug_id", "author", "body", "created_at"]))
        zf.writestr("testers.csv", sheet(data["testers"],
                                         ["id", "name", "email", "role", "active", "created_at"]))
        for kind in ("devices", "sw_builds", "modes"):
            zf.writestr(f"{kind}.csv", sheet(data[kind], ["id", "name", "archived"]))
        zf.writestr("attachments.csv", sheet(data["attachments"], [
            "id", "bug_id", "filename", "original_filename", "size_bytes", "uploaded_at"]))
        zf.writestr("history.csv", sheet(data["bug_events"], [
            "id", "bug_id", "actor_id", "kind", "field", "old_value", "new_value", "created_at"]))


# ── import ───────────────────────────────────────────────────────────────────

def read_backup_file(fileobj, filename):
    """Return (data dict, {stored filename: bytes loader}) from an uploaded file."""
    name = (filename or "").lower()
    raw = fileobj.read()
    if name.endswith(".zip") or raw[:2] == b"PK":
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise ImportErrorList(["That file isn't a valid ZIP archive."])
        if "data.json" not in zf.namelist():
            raise ImportErrorList(["The ZIP has no data.json — use a Full backup ZIP "
                                   "(the CSV export can't be imported)."])
        try:
            data = json.loads(zf.read("data.json").decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportErrorList([f"data.json is not valid JSON ({e})."])
        files = {n.split("/", 1)[1]: zf for n in zf.namelist()
                 if n.startswith("attachments/") and not n.endswith("/")}
        return data, files
    try:
        return json.loads(raw.decode("utf-8-sig")), {}
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ImportErrorList([f"That file isn't valid JSON ({e})."])


def _validate(data):
    """Check a backup thoroughly. Returns (normalized data, warnings)."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        raise ImportErrorList(["The backup must be a JSON object."])
    version = data.get("format_version", 1)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise ImportErrorList([f"This backup was made by a newer version (format {version}); "
                               "upgrade the app first."])
    if version == 1 and "bugs" not in data and "testers" not in data:
        raise ImportErrorList(["That JSON doesn't look like a bug tracker backup."])

    out = {}
    for table in ("devices", "sw_builds", "modes", "testers", "bugs", "attachments",
                  "comments", "bug_events"):
        rows = data.get(table, [])
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            errors.append(f"“{table}” must be a list of records.")
            rows = []
        ids = [r.get("id") for r in rows]
        if any(not isinstance(i, int) or isinstance(i, bool) for i in ids):
            errors.append(f"Every record in “{table}” needs a whole-number id.")
        elif len(set(ids)) != len(ids):
            errors.append(f"“{table}” has duplicate ids.")
        out[table] = rows

    def need(table, row, *fields):
        for f in fields:
            if not row.get(f) and row.get(f) != 0:
                errors.append(f"{table} #{row.get('id')} is missing “{f}”.")

    for table in ("devices", "sw_builds", "modes"):
        seen = set()
        for r in out[table]:
            need(table, r, "name")
            key = str(r.get("name", "")).lower()
            if key in seen:
                errors.append(f"{table} has the name “{r.get('name')}” twice.")
            seen.add(key)

    seen_emails = set()
    for r in out["testers"]:
        need("testers", r, "name", "email")
        key = str(r.get("email", "")).lower()
        if key in seen_emails:
            errors.append(f"Two testers share the email {r.get('email')}.")
        seen_emails.add(key)
        if r.get("role", "tester") not in ROLES:
            errors.append(f"Tester #{r.get('id')} has an unknown role “{r.get('role')}”.")

    for r in out["bugs"]:
        need("bugs", r, "title")
        if r.get("severity") not in SEVERITIES:
            errors.append(f"Bug #{r.get('id')} has an unknown severity “{r.get('severity')}”.")
        if r.get("status") not in STATUSES:
            errors.append(f"Bug #{r.get('id')} has an unknown status “{r.get('status')}”.")

    for r in out["attachments"]:
        need("attachments", r, "bug_id", "filename", "original_filename")
        if r.get("filename") and not SAFE_STORED_NAME.match(str(r["filename"])):
            errors.append(f"Attachment #{r.get('id')} has an unsafe file name.")
    for r in out["comments"]:
        need("comments", r, "bug_id", "body")
    for r in out["bug_events"]:
        need("bug_events", r, "bug_id", "kind")

    for table in out:
        for r in out[table]:
            for key, value in r.items():
                if key.endswith("_at") and value:
                    try:
                        _parse_ts(value)
                    except (TypeError, ValueError):
                        errors.append(f"{table} #{r.get('id')} has a bad date in “{key}”.")

    if errors:
        raise ImportErrorList(errors)

    # Dangling references: drop the link (optional) or the row (required).
    ids = {t: {r["id"] for r in out[t]} for t in out}
    refs = [("bugs", "reported_by_id", "testers"), ("bugs", "assigned_to_id", "testers"),
            ("bugs", "device_id", "devices"), ("bugs", "sw_build_id", "sw_builds"),
            ("bugs", "fixed_in_build_id", "sw_builds"), ("bugs", "mode_id", "modes"),
            ("attachments", "uploaded_by_id", "testers"), ("comments", "author_id", "testers"),
            ("bug_events", "actor_id", "testers")]
    cleared = 0
    for table, column, parent in refs:
        for r in out[table]:
            if r.get(column) is not None and r[column] not in ids[parent]:
                r[column] = None
                cleared += 1
    if cleared:
        warnings.append(f"Cleared {cleared} link{'s' if cleared != 1 else ''} to records that "
                        "weren't in the backup.")
    for table in ("attachments", "comments", "bug_events"):
        before = len(out[table])
        out[table] = [r for r in out[table] if r["bug_id"] in ids["bugs"]]
        if len(out[table]) != before:
            warnings.append(f"Skipped {before - len(out[table])} {table.replace('_', ' ')} "
                            "belonging to bugs that weren't in the backup.")
    out["format_version"] = version
    return out, warnings


def import_data(data, files=None, keep_admin=None):
    """Replace everything with the backup's contents.

    ``keep_admin`` (a User) is carried over when the backup has no admin who
    could sign in — e.g. a v1 backup — so whoever runs the import isn't
    locked out. Returns (warnings, id of the kept admin or None).
    """
    files = files or {}
    data, warnings = _validate(data)
    admin_snapshot = None
    if keep_admin is not None:
        admin_snapshot = {"name": keep_admin.name, "email": keep_admin.email,
                          "password_hash": keep_admin.password_hash}

    kept_admin_id = None
    try:
        for model in (BugEvent, Comment, Attachment, Bug, User, Device, SWBuild, Mode):
            model.query.delete()
        db.session.flush()

        for table, model in (("devices", Device), ("sw_builds", SWBuild), ("modes", Mode)):
            for r in data[table]:
                db.session.add(model(id=r["id"], name=str(r["name"])[:120],
                                     archived=bool(r.get("archived", False))))
        for r in data["testers"]:
            db.session.add(User(
                id=r["id"], name=r["name"], email=r["email"],
                role=r.get("role", "tester"), active=bool(r.get("active", True)),
                password_hash=r.get("password_hash"),
                created_at=_parse_ts(r.get("created_at")),
                last_login_at=_parse_ts(r.get("last_login_at")),
            ))
        db.session.flush()

        has_admin = any(r.get("role") == "admin" and r.get("password_hash")
                        and r.get("active", True) for r in data["testers"])
        if not has_admin and admin_snapshot:
            match = User.query.filter(db.func.lower(User.email) == admin_snapshot["email"].lower()).first()
            if match is None:
                match = User(name=admin_snapshot["name"], email=admin_snapshot["email"])
                db.session.add(match)
            match.role, match.active = "admin", True
            match.password_hash = admin_snapshot["password_hash"]
            db.session.flush()
            kept_admin_id = match.id
            warnings.append(f"The backup had no admin login, so {admin_snapshot['email']} "
                            "was kept as admin.")

        for r in data["bugs"]:
            db.session.add(Bug(
                id=r["id"], title=str(r["title"])[:200], description=r.get("description"),
                severity=r["severity"], status=r["status"],
                reported_by_id=r.get("reported_by_id"), assigned_to_id=r.get("assigned_to_id"),
                device_id=r.get("device_id"), sw_build_id=r.get("sw_build_id"),
                fixed_in_build_id=r.get("fixed_in_build_id"), mode_id=r.get("mode_id"),
                tg=r.get("tg"),
                created_at=_parse_ts(r.get("created_at")),
                updated_at=_parse_ts(r.get("updated_at")),
                resolved_at=_parse_ts(r.get("resolved_at")),
            ))
        db.session.flush()
        for r in data["attachments"]:
            db.session.add(Attachment(
                id=r["id"], bug_id=r["bug_id"], filename=r["filename"],
                original_filename=r["original_filename"],
                uploaded_at=_parse_ts(r.get("uploaded_at")),
                uploaded_by_id=r.get("uploaded_by_id"), size_bytes=r.get("size_bytes"),
                content_type=r.get("content_type"),
            ))
        for r in data["comments"]:
            db.session.add(Comment(id=r["id"], bug_id=r["bug_id"], author_id=r.get("author_id"),
                                   body=r["body"], created_at=_parse_ts(r.get("created_at"))))
        for r in data["bug_events"]:
            db.session.add(BugEvent(
                id=r["id"], bug_id=r["bug_id"], actor_id=r.get("actor_id"), kind=r["kind"],
                field=r.get("field"), old_value=r.get("old_value"), new_value=r.get("new_value"),
                created_at=_parse_ts(r.get("created_at")),
            ))
        # v1 backups have no resolved dates; use the last update as a best guess
        db.session.flush()
        if data["format_version"] == 1:
            for bug in Bug.query.filter(Bug.status.in_(["resolved", "closed", "wont_fix"]),
                                        Bug.resolved_at.is_(None)):
                bug.resolved_at = bug.updated_at
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    # Restore attachment files from a full-backup ZIP.
    upload_dir = current_app.config["UPLOAD_DIR"]
    restored = 0
    for att in data["attachments"]:
        source = files.get(att["filename"])
        if source is not None:
            with open(os.path.join(upload_dir, att["filename"]), "wb") as fh:
                fh.write(source.read(f"attachments/{att['filename']}"))
            restored += 1
    missing = [a for a in data["attachments"]
               if not os.path.exists(os.path.join(upload_dir, a["filename"]))]
    if missing:
        warnings.append(f"{len(missing)} attachment file{'s are' if len(missing) != 1 else ' is'} "
                        "missing from the uploads folder; copy them over to see them.")
    return warnings, kept_admin_id


def save_snapshot(label="snapshot"):
    """Write a JSON backup into BACKUP_DIR and return its path."""
    backup_dir = current_app.config["BACKUP_DIR"]
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backup_dir, f"{label}_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(export_data(), fh, indent=2)
    return path
