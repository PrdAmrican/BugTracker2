# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Shared helpers used by several views."""

import mimetypes
import os
import uuid
from functools import wraps

from flask import abort, current_app
from flask_login import current_user
from werkzeug.utils import secure_filename

from .extensions import db
from .models import (
    DONE_STATUSES, SEVERITIES, STATUS_LABELS, STATUSES, Attachment, Bug,
    BugEvent, Device, Mode, SWBuild, User, utcnow,
)

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "bmp", "webp",      # screenshots
    "mp4", "mov", "webm",                            # screen recordings
    "pdf", "txt", "log", "json", "csv", "xml", "zip",  # logs and reports
}
MIN_PASSWORD_LENGTH = 8


# ── permissions ──────────────────────────────────────────────────────────────

def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def can_delete_bug(bug):
    return current_user.is_admin or bug.reported_by_id == current_user.id


# ── parsing ──────────────────────────────────────────────────────────────────

def parse_int(value):
    """int(value) or None, never raises."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean(value, max_length=None):
    value = (value or "").strip()
    return value[:max_length] if max_length else value


# ── bug form ─────────────────────────────────────────────────────────────────

BUG_FIELDS = [
    # form field, attribute, model for id lookups
    ("reported_by", "reported_by_id", User),
    ("assigned_to", "assigned_to_id", User),
    ("device", "device_id", Device),
    ("sw_build", "sw_build_id", SWBuild),
    ("fixed_in_build", "fixed_in_build_id", SWBuild),
    ("mode", "mode_id", Mode),
]


def read_bug_form(form, is_new):
    """Validate a submitted bug form. Returns (values, errors)."""
    errors = []
    values = {
        "title": clean(form.get("title"), 200),
        "description": clean(form.get("description")),
        "severity": form.get("severity", "medium"),
        "tg": clean(form.get("tg"), 120) or None,
    }
    if not values["title"]:
        errors.append("Title is required.")
    if values["severity"] not in SEVERITIES:
        errors.append("Choose a valid severity.")

    if not is_new:
        values["status"] = form.get("status", "open")
        if values["status"] not in STATUSES:
            errors.append("Choose a valid status.")

    for field, attr, model in BUG_FIELDS:
        raw = form.get(field)
        if raw in (None, ""):
            values[attr] = None
            continue
        ref_id = parse_int(raw)
        if ref_id is None or db.session.get(model, ref_id) is None:
            errors.append(f"The selected {field.replace('_', ' ')} no longer exists.")
            values[attr] = None
        else:
            values[attr] = ref_id
    return values, errors


# ── history ──────────────────────────────────────────────────────────────────

TRACKED_FIELDS = {
    "title": "title",
    "severity": "severity",
    "status": "status",
    "assigned_to_id": "assignee",
    "reported_by_id": "reporter",
    "device_id": "device",
    "sw_build_id": "SW build",
    "fixed_in_build_id": "fixed in build",
    "mode_id": "mode",
    "tg": "TG",
    "description": "description",
}


def _display(bug, attr):
    """Human-readable value of a bug attribute, for the history log."""
    rel = {
        "assigned_to_id": "assignee", "reported_by_id": "reporter",
        "device_id": "device", "sw_build_id": "sw_build",
        "fixed_in_build_id": "fixed_in_build", "mode_id": "mode",
    }.get(attr)
    if rel:
        obj = getattr(bug, rel)
        return obj.name if obj else None
    value = getattr(bug, attr)
    if attr == "status":
        return STATUS_LABELS.get(value, value)
    if attr == "severity":
        return value.title() if value else value
    if attr == "description":
        return None  # too long for the log; we only note that it changed
    return value


def log_event(bug, kind, field=None, old=None, new=None):
    db.session.add(BugEvent(
        bug=bug,
        actor_id=current_user.id if current_user.is_authenticated else None,
        kind=kind,
        field=field,
        old_value=(old or "")[:255] or None,
        new_value=(new or "")[:255] or None,
    ))


def apply_bug_changes(bug, values):
    """Apply validated values to a bug, logging each change. Returns # changed."""
    before = {attr: _display(bug, attr) for attr in TRACKED_FIELDS}
    raw_before = {attr: getattr(bug, attr) for attr in TRACKED_FIELDS}
    for attr, value in values.items():
        setattr(bug, attr, value)
    db.session.flush()
    db.session.expire(bug, [r for r in ("assignee", "reporter", "device", "sw_build",
                                        "fixed_in_build", "mode")])
    changed = 0
    for attr, label in TRACKED_FIELDS.items():
        if attr in values and raw_before[attr] != getattr(bug, attr):
            changed += 1
            log_event(bug, "changed", label, before[attr], _display(bug, attr))
    if "status" in values and raw_before["status"] != bug.status:
        bug.resolved_at = utcnow() if bug.status in DONE_STATUSES else None
    return changed


# ── attachments ──────────────────────────────────────────────────────────────

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(bug, file_storage):
    """Store an uploaded file and return the new Attachment (not yet committed)."""
    original = secure_filename(file_storage.filename) or "file"
    if "." not in original and "." in file_storage.filename:
        original += "." + file_storage.filename.rsplit(".", 1)[1].lower()
    ext = original.rsplit(".", 1)[1].lower()
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(current_app.config["UPLOAD_DIR"], stored)
    file_storage.save(path)
    att = Attachment(
        bug=bug,
        filename=stored,
        original_filename=original,
        uploaded_by_id=current_user.id,
        size_bytes=os.path.getsize(path),
        content_type=mimetypes.guess_type(original)[0] or "application/octet-stream",
    )
    db.session.add(att)
    log_event(bug, "attachment_added", new=original)
    return att


def delete_attachment_file(att):
    path = os.path.join(current_app.config["UPLOAD_DIR"], att.filename)
    if os.path.exists(path):
        os.remove(path)
