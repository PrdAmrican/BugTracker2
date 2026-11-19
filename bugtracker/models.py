# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Database models.

Table and column names from v1 are kept as-is so an existing ``bugs.db`` can
be upgraded in place (see ``migrations.py``). Timestamps are stored as naive
UTC and converted to the viewer's local time in the browser.
"""

from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import case
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── choices ──────────────────────────────────────────────────────────────────

SEVERITIES = ["low", "medium", "high", "critical"]
SEVERITY_LABELS = {s: s.title() for s in SEVERITIES}

STATUSES = ["open", "needs_info", "in_progress", "resolved", "closed", "wont_fix"]
STATUS_LABELS = {
    "open": "Open",
    "needs_info": "Needs Info",
    "in_progress": "In Progress",
    "resolved": "Resolved",
    "closed": "Closed",
    "wont_fix": "Won't Fix",
}
ACTIVE_STATUSES = ["open", "needs_info", "in_progress"]
DONE_STATUSES = ["resolved", "closed", "wont_fix"]

ROLES = ["tester", "admin"]


# ── lookups (dropdown values) ────────────────────────────────────────────────

class LookupMixin:
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    archived = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    def __repr__(self):
        return f"<{type(self).__name__} {self.name}>"


class Device(LookupMixin, db.Model):
    __tablename__ = "devices"


class SWBuild(LookupMixin, db.Model):
    __tablename__ = "sw_builds"


class Mode(LookupMixin, db.Model):
    __tablename__ = "modes"


LOOKUPS = {
    "devices": {"model": Device, "label": "Devices", "singular": "Device"},
    "sw_builds": {"model": SWBuild, "label": "SW Builds", "singular": "SW Build"},
    "modes": {"model": Mode, "label": "Modes", "singular": "Mode"},
}


# ── people ───────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    """A tester. Testers with a password can sign in; admins manage the app.

    Stored in the v1 ``testers`` table so existing data carries over.
    """

    __tablename__ = "testers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(20), nullable=False, default="tester", server_default="tester")
    active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    last_login_at = db.Column(db.DateTime)

    reported_bugs = db.relationship(
        "Bug", foreign_keys="Bug.reported_by_id", back_populates="reporter"
    )
    assigned_bugs = db.relationship(
        "Bug", foreign_keys="Bug.assigned_to_id", back_populates="assignee"
    )

    # Flask-Login
    @property
    def is_active(self):
        return bool(self.active)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def can_login(self):
        return bool(self.password_hash) and self.is_active

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    def __repr__(self):
        return f"<User {self.email}>"


# Kept so code written against v1 names still reads naturally.
Tester = User


# ── bugs ─────────────────────────────────────────────────────────────────────

class Bug(db.Model):
    __tablename__ = "bugs"

    SEVERITY_CHOICES = SEVERITIES
    STATUS_CHOICES = STATUSES

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), nullable=False, default="medium", index=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    reported_by_id = db.Column(db.Integer, db.ForeignKey("testers.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("testers.id"), index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))
    sw_build_id = db.Column(db.Integer, db.ForeignKey("sw_builds.id"))
    fixed_in_build_id = db.Column(db.Integer, db.ForeignKey("sw_builds.id"))
    mode_id = db.Column(db.Integer, db.ForeignKey("modes.id"))
    tg = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    resolved_at = db.Column(db.DateTime)

    reporter = db.relationship("User", foreign_keys=[reported_by_id], back_populates="reported_bugs")
    assignee = db.relationship("User", foreign_keys=[assigned_to_id], back_populates="assigned_bugs")
    device = db.relationship("Device", foreign_keys=[device_id])
    sw_build = db.relationship("SWBuild", foreign_keys=[sw_build_id])
    fixed_in_build = db.relationship("SWBuild", foreign_keys=[fixed_in_build_id])
    mode = db.relationship("Mode", foreign_keys=[mode_id])
    attachments = db.relationship(
        "Attachment", back_populates="bug", cascade="all, delete-orphan",
        order_by="Attachment.uploaded_at",
    )
    comments = db.relationship(
        "Comment", back_populates="bug", cascade="all, delete-orphan",
        order_by="Comment.created_at",
    )
    events = db.relationship(
        "BugEvent", back_populates="bug", cascade="all, delete-orphan",
        order_by="BugEvent.created_at",
    )

    @property
    def is_done(self):
        return self.status in DONE_STATUSES

    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

    @staticmethod
    def severity_rank():
        """SQL expression ordering severities low → critical."""
        return case({s: i for i, s in enumerate(SEVERITIES)}, value=Bug.severity, else_=-1)

    def __repr__(self):
        return f"<Bug #{self.id}: {self.title}>"


class Attachment(db.Model):
    __tablename__ = "attachments"

    IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
    VIDEO_EXTENSIONS = {"mp4", "mov", "webm"}

    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey("bugs.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=utcnow)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("testers.id"))
    size_bytes = db.Column(db.Integer)
    content_type = db.Column(db.String(120))

    bug = db.relationship("Bug", back_populates="attachments")
    uploaded_by = db.relationship("User")

    @property
    def extension(self):
        return self.original_filename.rsplit(".", 1)[-1].lower() if "." in self.original_filename else ""

    @property
    def is_image(self):
        return self.extension in self.IMAGE_EXTENSIONS

    @property
    def is_video(self):
        return self.extension in self.VIDEO_EXTENSIONS

    def __repr__(self):
        return f"<Attachment {self.original_filename}>"


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey("bugs.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("testers.id"))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    bug = db.relationship("Bug", back_populates="comments")
    author = db.relationship("User")


class BugEvent(db.Model):
    """One line of a bug's history: created, a field changed, a file added…"""

    __tablename__ = "bug_events"

    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey("bugs.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("testers.id"))
    kind = db.Column(db.String(30), nullable=False)
    field = db.Column(db.String(40))
    old_value = db.Column(db.String(255))
    new_value = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    bug = db.relationship("Bug", back_populates="events")
    actor = db.relationship("User")


class AppMeta(db.Model):
    """Small key/value table; holds the schema version."""

    __tablename__ = "app_meta"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255))
