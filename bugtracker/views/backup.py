# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
import json
import os
import sqlite3
import tempfile
from datetime import datetime

from flask import (
    Blueprint, Response, abort, current_app, flash, redirect, render_template,
    request, send_file, url_for,
)
from flask_login import current_user, login_user
from sqlalchemy.engine import make_url

from ..backup import (
    ImportErrorList, export_data, import_data, read_backup_file, save_snapshot,
    write_csv_zip, write_full_backup,
)
from ..extensions import db
from ..models import User
from ..services import admin_required

bp = Blueprint("backup", __name__, url_prefix="/backup")


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sqlite_path():
    url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return url.database


@bp.route("/")
@admin_required
def index():
    snapshots = []
    backup_dir = current_app.config["BACKUP_DIR"]
    if os.path.isdir(backup_dir):
        for name in sorted(os.listdir(backup_dir), reverse=True)[:10]:
            if name.endswith(".json"):
                snapshots.append(name)
    return render_template("backup.html", has_sqlite=_sqlite_path() is not None,
                           snapshots=snapshots)


@bp.route("/export.json")
@admin_required
def export_json():
    return Response(
        json.dumps(export_data(), indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=bug_tracker_backup_{_stamp()}.json"},
    )


@bp.route("/full.zip")
@admin_required
def export_full():
    tmp = tempfile.TemporaryFile()
    missing = write_full_backup(tmp)
    tmp.seek(0)
    if missing:
        current_app.logger.warning("Full backup: %s attachment files were missing", missing)
    return send_file(tmp, mimetype="application/zip", as_attachment=True,
                     download_name=f"bug_tracker_full_{_stamp()}.zip")


@bp.route("/csv.zip")
@admin_required
def export_csv():
    tmp = tempfile.TemporaryFile()
    write_csv_zip(tmp)
    tmp.seek(0)
    return send_file(tmp, mimetype="application/zip", as_attachment=True,
                     download_name=f"bug_tracker_csv_{_stamp()}.zip")


@bp.route("/bugs.db")
@admin_required
def export_sqlite():
    """A consistent copy of the SQLite database (safe while the app is running)."""
    path = _sqlite_path()
    if path is None or not os.path.exists(path):
        abort(404)
    fd, copy_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src, dst = sqlite3.connect(path), sqlite3.connect(copy_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    response = send_file(copy_path, mimetype="application/x-sqlite3", as_attachment=True,
                         download_name=f"bugs_{_stamp()}.db")
    response.call_on_close(lambda: os.path.exists(copy_path) and os.remove(copy_path))
    return response


@bp.route("/import", methods=["POST"])
@admin_required
def import_backup():
    # (The upload limit for this route is raised in create_app.)
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "danger")
        return redirect(url_for("backup.index"))
    if request.form.get("confirm") != "REPLACE":
        flash("Type REPLACE to confirm that all current data will be replaced.", "danger")
        return redirect(url_for("backup.index"))

    my_email = current_user.email
    try:
        data, files = read_backup_file(file.stream, file.filename)
        snapshot = save_snapshot("pre-import")
        warnings, kept_admin_id = import_data(data, files, keep_admin=current_user._get_current_object())
    except ImportErrorList as e:
        flash("Import failed — nothing was changed.", "danger")
        for err in e.errors[:8]:
            flash(err, "danger")
        if len(e.errors) > 8:
            flash(f"…and {len(e.errors) - 8} more problems.", "danger")
        return redirect(url_for("backup.index"))
    except Exception as e:  # unexpected: database error, disk full …
        current_app.logger.exception("Import failed")
        flash(f"Import failed — nothing was changed. ({e.__class__.__name__}: {e})", "danger")
        return redirect(url_for("backup.index"))

    # Our session user object is stale after the swap; sign back in as whoever
    # now owns this email (or the carried-over admin).
    me = db.session.get(User, kept_admin_id) if kept_admin_id else \
        User.query.filter(db.func.lower(User.email) == my_email.lower()).first()
    if me is not None and me.can_login:
        login_user(me)
    flash(f"Backup restored. Previous data was saved to backups/{os.path.basename(snapshot)}.",
          "success")
    for w in warnings:
        flash(w, "warning")
    if me is None or not me.can_login:
        return redirect(url_for("auth.login"))
    return redirect(url_for("backup.index"))


@bp.route("/snapshots/<name>")
@admin_required
def download_snapshot(name):
    backup_dir = current_app.config["BACKUP_DIR"]
    if "/" in name or "\\" in name or not name.endswith(".json"):
        abort(404)
    path = os.path.join(backup_dir, name)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=name)
