# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Bug list, detail, create/edit, comments and attachments."""

import csv
import io
from datetime import datetime

from flask import (
    Blueprint, Response, abort, current_app, flash, jsonify, redirect,
    render_template, request, send_from_directory, url_for,
)
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from ..extensions import db
from ..models import (
    ACTIVE_STATUSES, DONE_STATUSES, LOOKUPS, SEVERITIES, STATUS_LABELS,
    STATUSES, Attachment, Bug, Comment, Device, Mode, SWBuild, User, utcnow,
)
from ..services import (
    ALLOWED_EXTENSIONS, allowed_file, apply_bug_changes, can_delete_bug, clean,
    delete_attachment_file, log_event, parse_int, read_bug_form,
    save_attachment,
)

bp = Blueprint("bugs", __name__)

SORTS = {
    "id": Bug.id,
    "title": Bug.title,
    "severity": Bug.severity_rank(),
    "status": Bug.status,
    "created": Bug.created_at,
    "updated": Bug.updated_at,
}


# ── list ─────────────────────────────────────────────────────────────────────

def _filtered_query(args):
    """Build the bug query for the list page / CSV export from query args."""
    query = Bug.query
    filters = {}

    q = clean(args.get("q"))
    if q:
        filters["q"] = q
        if q.lstrip("#").isdigit():
            query = query.filter(or_(Bug.id == int(q.lstrip("#")), Bug.title.ilike(f"%{q}%")))
        else:
            like = f"%{q}%"
            query = query.filter(or_(Bug.title.ilike(like), Bug.description.ilike(like), Bug.tg.ilike(like)))

    status = args.get("status", "")
    if status == "active":
        query = query.filter(Bug.status.in_(ACTIVE_STATUSES))
    elif status == "done":
        query = query.filter(Bug.status.in_(DONE_STATUSES))
    elif status in STATUSES:
        query = query.filter(Bug.status == status)
    else:
        status = ""
    filters["status"] = status

    severity = args.get("severity", "")
    if severity in SEVERITIES:
        query = query.filter(Bug.severity == severity)
    else:
        severity = ""
    filters["severity"] = severity

    assignee = args.get("assignee", "")
    if assignee == "me":
        query = query.filter(Bug.assigned_to_id == current_user.id)
    elif assignee == "none":
        query = query.filter(Bug.assigned_to_id.is_(None))
    elif parse_int(assignee) is not None:
        query = query.filter(Bug.assigned_to_id == parse_int(assignee))
    else:
        assignee = ""
    filters["assignee"] = assignee

    for arg, column in (("reporter", Bug.reported_by_id), ("device", Bug.device_id),
                        ("build", Bug.sw_build_id), ("mode", Bug.mode_id)):
        value = parse_int(args.get(arg))
        filters[arg] = str(value) if value is not None else ""
        if value is not None:
            query = query.filter(column == value)

    sort = args.get("sort", "updated")
    if sort not in SORTS:
        sort = "updated"
    direction = "asc" if args.get("dir") == "asc" else "desc"
    column = SORTS[sort]
    query = query.order_by(column.asc() if direction == "asc" else column.desc(), Bug.id.desc())
    filters["sort"], filters["dir"] = sort, direction
    return query, filters


def _lookup_options(include_archived=False):
    def rows(model):
        q = model.query
        if not include_archived:
            q = q.filter(model.archived.is_(False))
        return q.order_by(model.name).all()
    return {
        "testers": User.query.order_by(User.name).all(),
        "devices": rows(Device),
        "sw_builds": rows(SWBuild),
        "modes": rows(Mode),
    }


@bp.route("/bugs", endpoint="list")
def bug_list():
    query, filters = _filtered_query(request.args)
    query = query.options(
        selectinload(Bug.assignee), selectinload(Bug.device), selectinload(Bug.mode),
        selectinload(Bug.sw_build), selectinload(Bug.comments), selectinload(Bug.attachments),
    )
    page = max(parse_int(request.args.get("page")) or 1, 1)
    pagination = query.paginate(page=page, per_page=current_app.config["BUGS_PER_PAGE"],
                                error_out=False)
    advanced_open = any(filters[k] for k in ("reporter", "device", "build", "mode"))
    return render_template(
        "bugs/list.html",
        bugs=pagination.items,
        pagination=pagination,
        filters=filters,
        advanced_open=advanced_open,
        **_lookup_options(include_archived=True),
    )


@bp.route("/bugs/export.csv")
def export_csv():
    query, _ = _filtered_query(request.args)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "title", "severity", "status", "reporter", "assignee", "device",
                     "sw_build", "fixed_in_build", "mode", "tg", "created_at", "updated_at",
                     "resolved_at", "description"])
    for b in query:
        writer.writerow([
            b.id, b.title, b.severity, STATUS_LABELS.get(b.status, b.status),
            b.reporter.name if b.reporter else "", b.assignee.name if b.assignee else "",
            b.device.name if b.device else "", b.sw_build.name if b.sw_build else "",
            b.fixed_in_build.name if b.fixed_in_build else "", b.mode.name if b.mode else "",
            b.tg or "",
            b.created_at.isoformat() if b.created_at else "",
            b.updated_at.isoformat() if b.updated_at else "",
            b.resolved_at.isoformat() if b.resolved_at else "",
            b.description or "",
        ])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        "﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=bugs_{stamp}.csv"},
    )


# ── create / edit ────────────────────────────────────────────────────────────

@bp.route("/bugs/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        values, errors = read_bug_form(request.form, is_new=True)
        files = [f for f in request.files.getlist("files") if f and f.filename]
        bad = [f.filename for f in files if not allowed_file(f.filename)]
        if bad:
            errors.append("File type not allowed: " + ", ".join(bad))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("bugs/form.html", bug=None, form=request.form,
                                   **_lookup_options()), 400

        bug = Bug(status="open", **values)
        db.session.add(bug)
        db.session.flush()
        log_event(bug, "created")
        for f in files:
            save_attachment(bug, f)
        db.session.commit()
        flash(f"Bug #{bug.id} reported.", "success")
        return redirect(url_for("bugs.detail", bug_id=bug.id))

    form = {"reported_by": str(current_user.id)}
    # "Report another like this": prefill environment fields from a previous bug
    template = db.session.get(Bug, parse_int(request.args.get("like")) or 0)
    if template:
        form.update({
            "device": str(template.device_id or ""), "sw_build": str(template.sw_build_id or ""),
            "mode": str(template.mode_id or ""), "tg": template.tg or "",
        })
    return render_template("bugs/form.html", bug=None, form=form, **_lookup_options())


def _get_bug(bug_id):
    bug = db.session.get(Bug, bug_id)
    if bug is None:
        abort(404)
    return bug


@bp.route("/bugs/<int:bug_id>/edit", methods=["GET", "POST"])
def edit(bug_id):
    bug = _get_bug(bug_id)
    if request.method == "POST":
        values, errors = read_bug_form(request.form, is_new=False)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("bugs/form.html", bug=bug, form=request.form,
                                   **_lookup_options()), 400
        changed = apply_bug_changes(bug, values)
        db.session.commit()
        flash("Bug updated." if changed else "No changes.", "success" if changed else "info")
        return redirect(url_for("bugs.detail", bug_id=bug.id))

    form = {
        "title": bug.title, "description": bug.description or "", "severity": bug.severity,
        "status": bug.status, "tg": bug.tg or "",
        "reported_by": str(bug.reported_by_id or ""), "assigned_to": str(bug.assigned_to_id or ""),
        "device": str(bug.device_id or ""), "sw_build": str(bug.sw_build_id or ""),
        "fixed_in_build": str(bug.fixed_in_build_id or ""), "mode": str(bug.mode_id or ""),
    }
    options = _lookup_options()
    # keep archived values that this bug already uses visible in the dropdowns
    for key, attr in (("devices", "device"), ("sw_builds", "sw_build"),
                      ("sw_builds", "fixed_in_build"), ("modes", "mode")):
        current = getattr(bug, attr)
        if current is not None and current not in options[key]:
            options[key] = sorted(options[key] + [current], key=lambda x: x.name.lower())
    return render_template("bugs/form.html", bug=bug, form=form, **options)


# ── detail & quick actions ───────────────────────────────────────────────────

@bp.route("/bugs/<int:bug_id>")
def detail(bug_id):
    bug = _get_bug(bug_id)
    timeline = sorted(
        [("comment", c.created_at, c) for c in bug.comments]
        + [("event", e.created_at, e) for e in bug.events],
        key=lambda item: (item[1] is None, item[1]),
    )
    prev_bug = Bug.query.filter(Bug.id < bug.id).order_by(Bug.id.desc()).first()
    next_bug = Bug.query.filter(Bug.id > bug.id).order_by(Bug.id.asc()).first()
    return render_template(
        "bugs/detail.html", bug=bug, timeline=timeline,
        can_delete=can_delete_bug(bug), testers=User.query.order_by(User.name).all(),
        prev_bug=prev_bug, next_bug=next_bug,
        allowed_extensions=sorted(ALLOWED_EXTENSIONS),
        sw_builds=SWBuild.query.filter(SWBuild.archived.is_(False)).order_by(SWBuild.name).all(),
    )


@bp.route("/bugs/<int:bug_id>/quick", methods=["POST"])
def quick_update(bug_id):
    """Status / assignee changes from the detail page, with an optional comment."""
    bug = _get_bug(bug_id)
    values = {}
    status = request.form.get("status")
    if status:
        if status not in STATUSES:
            abort(400)
        values["status"] = status
    if "assigned_to" in request.form:
        raw = request.form.get("assigned_to")
        if raw == "me":
            values["assigned_to_id"] = current_user.id
        elif raw == "":
            values["assigned_to_id"] = None
        else:
            uid = parse_int(raw)
            if uid is None or db.session.get(User, uid) is None:
                abort(400)
            values["assigned_to_id"] = uid
    if "fixed_in_build" in request.form:
        raw = request.form.get("fixed_in_build")
        build_id = parse_int(raw)
        if raw and (build_id is None or db.session.get(SWBuild, build_id) is None):
            abort(400)
        values["fixed_in_build_id"] = build_id

    changed = apply_bug_changes(bug, values) if values else 0
    body = clean(request.form.get("comment"))
    if body:
        db.session.add(Comment(bug=bug, author_id=current_user.id, body=body))
        bug.updated_at = utcnow()  # a comment counts as activity
        changed += 1
    db.session.commit()
    if changed:
        flash("Bug updated.", "success")
    return redirect(url_for("bugs.detail", bug_id=bug.id))


@bp.route("/bugs/<int:bug_id>/delete", methods=["POST"])
def delete(bug_id):
    bug = _get_bug(bug_id)
    if not can_delete_bug(bug):
        abort(403)
    for att in bug.attachments:
        delete_attachment_file(att)
    db.session.delete(bug)
    db.session.commit()
    flash(f"Bug #{bug_id} deleted.", "info")
    return redirect(url_for("bugs.list"))


# ── comments ─────────────────────────────────────────────────────────────────

@bp.route("/bugs/<int:bug_id>/comments", methods=["POST"])
def add_comment(bug_id):
    bug = _get_bug(bug_id)
    body = clean(request.form.get("body"))
    if not body:
        flash("Comment can't be empty.", "danger")
    else:
        db.session.add(Comment(bug=bug, author_id=current_user.id, body=body))
        bug.updated_at = utcnow()
        db.session.commit()
    return redirect(url_for("bugs.detail", bug_id=bug.id) + "#activity")


@bp.route("/comments/<int:comment_id>/delete", methods=["POST"])
def delete_comment(comment_id):
    comment = db.session.get(Comment, comment_id) or abort(404)
    if not (current_user.is_admin or comment.author_id == current_user.id):
        abort(403)
    bug_id = comment.bug_id
    db.session.delete(comment)
    db.session.commit()
    flash("Comment deleted.", "info")
    return redirect(url_for("bugs.detail", bug_id=bug_id) + "#activity")


# ── attachments ──────────────────────────────────────────────────────────────

@bp.route("/bugs/<int:bug_id>/attach", methods=["POST"])
def attach(bug_id):
    bug = _get_bug(bug_id)
    files = [f for f in request.files.getlist("files") + request.files.getlist("file")
             if f and f.filename]
    if not files:
        flash("No file selected.", "danger")
        return redirect(url_for("bugs.detail", bug_id=bug.id))
    bad = [f.filename for f in files if not allowed_file(f.filename)]
    if bad:
        flash("File type not allowed: " + ", ".join(bad), "danger")
        return redirect(url_for("bugs.detail", bug_id=bug.id))
    for f in files:
        save_attachment(bug, f)
    db.session.commit()
    flash(f"{len(files)} file{'s' if len(files) != 1 else ''} attached.", "success")
    return redirect(url_for("bugs.detail", bug_id=bug.id))


@bp.route("/attachments/<int:att_id>/<path:name>")
def attachment(att_id, name):
    att = db.session.get(Attachment, att_id) or abort(404)
    inline = att.is_image or att.is_video or att.extension in {"pdf", "txt", "log"}
    return send_from_directory(
        current_app.config["UPLOAD_DIR"], att.filename,
        as_attachment=not inline, download_name=att.original_filename,
        mimetype="text/plain" if att.extension in {"txt", "log"} else None,
    )


@bp.route("/uploads/<path:filename>")
def legacy_upload(filename):
    """v1 URL for attachment files; kept so old links still work (signed in)."""
    att = Attachment.query.filter_by(filename=filename).first_or_404()
    return redirect(url_for("bugs.attachment", att_id=att.id, name=att.original_filename))


@bp.route("/attachments/<int:att_id>/delete", methods=["POST"])
def delete_attachment(att_id):
    att = db.session.get(Attachment, att_id) or abort(404)
    if not (current_user.is_admin or att.uploaded_by_id == current_user.id
            or att.bug.reported_by_id == current_user.id):
        abort(403)
    bug = att.bug
    delete_attachment_file(att)
    log_event(bug, "attachment_removed", old=att.original_filename)
    db.session.delete(att)
    db.session.commit()
    flash("Attachment removed.", "info")
    return redirect(url_for("bugs.detail", bug_id=bug.id))


# ── inline "add new" for dropdowns on the bug form ───────────────────────────

@bp.route("/api/<kind>", methods=["POST"])
def api_add_lookup(kind):
    if kind not in LOOKUPS:
        abort(404)
    model = LOOKUPS[kind]["model"]
    name = clean(request.form.get("name"), 120)
    if not name:
        return jsonify({"error": "Name is required"}), 400
    existing = model.query.filter(db.func.lower(model.name) == name.lower()).first()
    if existing:
        if existing.archived:
            existing.archived = False
            db.session.commit()
            return jsonify({"id": existing.id, "name": existing.name, "restored": True})
        return jsonify({"error": f"{LOOKUPS[kind]['singular']} already exists",
                        "id": existing.id, "name": existing.name}), 409
    obj = model(name=name)
    db.session.add(obj)
    db.session.commit()
    return jsonify({"id": obj.id, "name": obj.name})
