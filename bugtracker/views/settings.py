# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Admin settings: manage dropdown values (devices, SW builds, modes)."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_

from ..extensions import db
from ..models import LOOKUPS, Bug
from ..services import admin_required, clean

bp = Blueprint("settings", __name__, url_prefix="/settings")

USAGE_COLUMNS = {
    "devices": [Bug.device_id],
    "sw_builds": [Bug.sw_build_id, Bug.fixed_in_build_id],
    "modes": [Bug.mode_id],
}


def _usage(kind):
    counts = {}
    for column in USAGE_COLUMNS[kind]:
        for value, n in db.session.query(column, func.count(Bug.id)).filter(column.isnot(None)).group_by(column):
            counts[value] = counts.get(value, 0) + n
    return counts


def _lookup(kind, item_id):
    if kind not in LOOKUPS:
        abort(404)
    return db.session.get(LOOKUPS[kind]["model"], item_id) or abort(404)


@bp.route("/")
@admin_required
def index():
    kind = request.args.get("kind", "sw_builds")
    if kind not in LOOKUPS:
        kind = "sw_builds"
    model = LOOKUPS[kind]["model"]
    items = model.query.order_by(model.archived, func.lower(model.name)).all()
    return render_template("settings/index.html", kind=kind, lookups=LOOKUPS,
                           items=items, usage=_usage(kind))


@bp.route("/<kind>/add", methods=["POST"])
@admin_required
def add(kind):
    if kind not in LOOKUPS:
        abort(404)
    model = LOOKUPS[kind]["model"]
    names = [clean(n, 120) for n in request.form.get("names", "").splitlines()]
    added, skipped = 0, 0
    for name in filter(None, names):
        if model.query.filter(func.lower(model.name) == name.lower()).first():
            skipped += 1
            continue
        db.session.add(model(name=name))
        db.session.flush()
        added += 1
    db.session.commit()
    if added:
        flash(f"Added {added} {LOOKUPS[kind]['label'].lower()}.", "success")
    if skipped:
        flash(f"Skipped {skipped} that already exist.", "info")
    return redirect(url_for("settings.index", kind=kind))


@bp.route("/<kind>/<int:item_id>/rename", methods=["POST"])
@admin_required
def rename(kind, item_id):
    item = _lookup(kind, item_id)
    model = LOOKUPS[kind]["model"]
    name = clean(request.form.get("name"), 120)
    clash = model.query.filter(func.lower(model.name) == name.lower(), model.id != item.id).first()
    if not name:
        flash("Name can't be empty.", "danger")
    elif clash:
        flash(f"“{name}” already exists.", "danger")
    else:
        item.name = name
        db.session.commit()
        flash("Renamed.", "success")
    return redirect(url_for("settings.index", kind=kind))


@bp.route("/<kind>/<int:item_id>/archive", methods=["POST"])
@admin_required
def toggle_archive(kind, item_id):
    item = _lookup(kind, item_id)
    item.archived = not item.archived
    db.session.commit()
    flash(f"“{item.name}” {'archived — hidden from new bugs' if item.archived else 'restored'}.", "info")
    return redirect(url_for("settings.index", kind=kind))


@bp.route("/<kind>/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete(kind, item_id):
    item = _lookup(kind, item_id)
    used = Bug.query.filter(or_(*[c == item.id for c in USAGE_COLUMNS[kind]])).count()
    if used:
        flash(f"“{item.name}” is used by {used} bug{'s' if used != 1 else ''}; archive it instead.", "warning")
    else:
        db.session.delete(item)
        db.session.commit()
        flash(f"Deleted “{item.name}”.", "info")
    return redirect(url_for("settings.index", kind=kind))
