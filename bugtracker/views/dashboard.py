# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import current_user
from sqlalchemy import func

from ..extensions import db
from ..models import ACTIVE_STATUSES, DONE_STATUSES, Bug, BugEvent, SWBuild, utcnow

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    status_counts = dict(db.session.query(Bug.status, func.count(Bug.id)).group_by(Bug.status).all())
    total = sum(status_counts.values())
    active = sum(status_counts.get(s, 0) for s in ACTIVE_STATUSES)

    severity_active = dict(
        db.session.query(Bug.severity, func.count(Bug.id))
        .filter(Bug.status.in_(ACTIVE_STATUSES))
        .group_by(Bug.severity).all()
    )

    week_ago = utcnow() - timedelta(days=7)
    reported_this_week = Bug.query.filter(Bug.created_at >= week_ago).count()
    resolved_this_week = Bug.query.filter(
        Bug.status.in_(DONE_STATUSES), Bug.resolved_at >= week_ago
    ).count()

    by_build = (
        db.session.query(SWBuild, func.count(Bug.id))
        .join(Bug, Bug.sw_build_id == SWBuild.id)
        .filter(Bug.status.in_(ACTIVE_STATUSES))
        .group_by(SWBuild.id)
        .order_by(func.count(Bug.id).desc(), SWBuild.name.desc())
        .limit(6).all()
    )

    my_bugs = (
        Bug.query.filter(Bug.assigned_to_id == current_user.id, Bug.status.in_(ACTIVE_STATUSES))
        .order_by(Bug.severity_rank().desc(), Bug.updated_at.desc())
        .limit(8).all()
    )

    recent_events = BugEvent.query.order_by(BugEvent.created_at.desc(), BugEvent.id.desc()).limit(12).all()

    return render_template(
        "dashboard.html",
        total=total,
        active=active,
        status_counts=status_counts,
        severity_active=severity_active,
        critical_active=severity_active.get("critical", 0),
        reported_this_week=reported_this_week,
        resolved_this_week=resolved_this_week,
        by_build=by_build,
        my_bugs=my_bugs,
        recent_events=recent_events,
    )
