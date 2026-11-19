# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""In-place schema upgrades.

v1 databases are upgraded automatically the first time v2 starts: new
tables are created, new columns are added to existing tables, and a few
data clean-ups run (for example references to testers that v1 deleted
without clearing the bugs that pointed at them).

Each step is idempotent, so running it on an up-to-date database is a no-op.
"""

import os
import time

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from .extensions import db
from .models import AppMeta, Attachment

SCHEMA_VERSION = 2

# Columns added after v1: table -> [(column, DDL)]
NEW_COLUMNS = {
    "testers": [
        ("password_hash", "VARCHAR(255)"),
        ("role", "VARCHAR(20) NOT NULL DEFAULT 'tester'"),
        ("active", "BOOLEAN NOT NULL DEFAULT 1"),
        ("last_login_at", "DATETIME"),
    ],
    "bugs": [
        ("fixed_in_build_id", "INTEGER REFERENCES sw_builds(id)"),
        ("resolved_at", "DATETIME"),
    ],
    "attachments": [
        ("uploaded_by_id", "INTEGER REFERENCES testers(id)"),
        ("size_bytes", "INTEGER"),
        ("content_type", "VARCHAR(120)"),
    ],
    "devices": [("archived", "BOOLEAN NOT NULL DEFAULT 0")],
    "sw_builds": [("archived", "BOOLEAN NOT NULL DEFAULT 0")],
    "modes": [("archived", "BOOLEAN NOT NULL DEFAULT 0")],
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_bugs_status ON bugs (status)",
    "CREATE INDEX IF NOT EXISTS ix_bugs_severity ON bugs (severity)",
    "CREATE INDEX IF NOT EXISTS ix_bugs_assigned_to_id ON bugs (assigned_to_id)",
]

# (child table, column, parent table) pairs whose dangling values get NULLed.
NULLABLE_REFERENCES = [
    ("bugs", "reported_by_id", "testers"),
    ("bugs", "assigned_to_id", "testers"),
    ("bugs", "device_id", "devices"),
    ("bugs", "sw_build_id", "sw_builds"),
    ("bugs", "fixed_in_build_id", "sw_builds"),
    ("bugs", "mode_id", "modes"),
    ("attachments", "uploaded_by_id", "testers"),
]


def current_version():
    row = db.session.get(AppMeta, "schema_version")
    return int(row.value) if row else None


def upgrade_database(app, attempts=5):
    """Bring the database up to SCHEMA_VERSION. Returns the starting version.

    Several worker processes (gunicorn -w 4) may start at once; if another
    worker is mid-upgrade we get "duplicate column"/"database is locked",
    so wait a moment and try again — every step is idempotent.
    """
    for attempt in range(attempts):
        try:
            return _upgrade(app)
        except OperationalError:
            db.session.rollback()
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def _upgrade(app):
    engine = db.engine
    existing_tables = set(inspect(engine).get_table_names())
    is_legacy = "testers" in existing_tables and "app_meta" not in existing_tables

    # 1. new tables (comments, bug_events, app_meta …); existing ones untouched
    db.create_all()

    # 2. new columns on tables that predate them
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            have = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
        for stmt in INDEXES:
            conn.execute(text(stmt))

        # 3. data clean-ups (safe to repeat)
        for child, column, parent in NULLABLE_REFERENCES:
            conn.execute(text(
                f"UPDATE {child} SET {column} = NULL WHERE {column} IS NOT NULL "
                f"AND {column} NOT IN (SELECT id FROM {parent})"
            ))
        # attachments whose bug no longer exists cannot be shown anywhere
        conn.execute(text("DELETE FROM attachments WHERE bug_id NOT IN (SELECT id FROM bugs)"))
        conn.execute(text(
            "UPDATE bugs SET resolved_at = updated_at "
            "WHERE resolved_at IS NULL AND status IN ('resolved', 'closed', 'wont_fix')"
        ))

    # 4. fill in attachment sizes from files already on disk
    upload_dir = app.config["UPLOAD_DIR"]
    missing = Attachment.query.filter(Attachment.size_bytes.is_(None)).all()
    for att in missing:
        path = os.path.join(upload_dir, att.filename)
        if os.path.exists(path):
            att.size_bytes = os.path.getsize(path)

    start = None if is_legacy else current_version()
    meta = db.session.get(AppMeta, "schema_version")
    if meta is None:
        db.session.add(AppMeta(key="schema_version", value=str(SCHEMA_VERSION)))
    else:
        meta.value = str(SCHEMA_VERSION)
    db.session.commit()
    if is_legacy:
        app.logger.info("Upgraded v1 database to schema version %s", SCHEMA_VERSION)
    return 1 if is_legacy else start
