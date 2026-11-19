# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Testers and their accounts."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from ..extensions import db
from ..models import ACTIVE_STATUSES, ROLES, Attachment, Bug, BugEvent, Comment, User
from ..services import MIN_PASSWORD_LENGTH, admin_required, clean

bp = Blueprint("people", __name__, url_prefix="/people")


def _counts(column, active_only=False):
    q = db.session.query(column, func.count(Bug.id)).filter(column.isnot(None))
    if active_only:
        q = q.filter(Bug.status.in_(ACTIVE_STATUSES))
    return dict(q.group_by(column).all())


def _other_admins(user):
    return User.query.filter(User.role == "admin", User.active.is_(True),
                             User.password_hash.isnot(None), User.id != user.id).count()


def _validate(name, email, role, password, user=None):
    errors = []
    if not name or not email:
        errors.append("Name and email are required.")
    elif "@" not in email:
        errors.append("Enter a valid email address.")
    else:
        clash = User.query.filter(func.lower(User.email) == email.lower())
        if user is not None:
            clash = clash.filter(User.id != user.id)
        if clash.first():
            errors.append("A tester with that email already exists.")
    if role not in ROLES:
        errors.append("Choose a valid role.")
    if password and len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters.")
    return errors


@bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if not current_user.is_admin:
            abort(403)
        name = clean(request.form.get("name"), 120)
        email = clean(request.form.get("email"), 120)
        role = request.form.get("role", "tester")
        password = request.form.get("password", "")
        errors = _validate(name, email, role, password)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            user = User(name=name, email=email, role=role)
            if password:
                user.set_password(password)
            db.session.add(user)
            db.session.commit()
            note = "" if password else " They can't sign in until you set a password."
            flash(f"Added {name}.{note}", "success")
        return redirect(url_for("people.index"))

    users = User.query.order_by(User.active.desc(), func.lower(User.name)).all()
    return render_template(
        "people/index.html", users=users,
        reported=_counts(Bug.reported_by_id), assigned=_counts(Bug.assigned_to_id, active_only=True),
        roles=ROLES, min_length=MIN_PASSWORD_LENGTH,
    )


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if request.method == "POST":
        name = clean(request.form.get("name"), 120)
        email = clean(request.form.get("email"), 120)
        role = request.form.get("role", user.role)
        active = bool(request.form.get("active"))
        password = request.form.get("password", "")
        errors = _validate(name, email, role, password, user=user)
        losing_admin = user.is_admin and (role != "admin" or not active)
        if losing_admin and _other_admins(user) == 0:
            errors.append("You can't remove the last admin. Make someone else an admin first.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("people/edit.html", user=user, roles=ROLES,
                                   min_length=MIN_PASSWORD_LENGTH), 400
        user.name, user.email, user.role, user.active = name, email, role, active
        if password:
            user.set_password(password)
        if request.form.get("remove_login"):
            user.password_hash = None
        db.session.commit()
        flash(f"Saved changes to {user.name}.", "success")
        if user.id == current_user.id and not user.can_login:
            return redirect(url_for("auth.login"))
        return redirect(url_for("people.index"))
    return render_template("people/edit.html", user=user, roles=ROLES, min_length=MIN_PASSWORD_LENGTH)


@bp.route("/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You can't delete your own account.", "danger")
        return redirect(url_for("people.edit", user_id=user.id))
    if user.is_admin and _other_admins(user) == 0:
        flash("You can't delete the last admin.", "danger")
        return redirect(url_for("people.edit", user_id=user.id))
    # Keep the bugs and comments; just drop the link to this person.
    Bug.query.filter_by(reported_by_id=user.id).update({"reported_by_id": None})
    Bug.query.filter_by(assigned_to_id=user.id).update({"assigned_to_id": None})
    Comment.query.filter_by(author_id=user.id).update({"author_id": None})
    BugEvent.query.filter_by(actor_id=user.id).update({"actor_id": None})
    Attachment.query.filter_by(uploaded_by_id=user.id).update({"uploaded_by_id": None})
    name = user.name
    db.session.delete(user)
    db.session.commit()
    flash(f"Removed {name}. Their bugs and comments were kept.", "info")
    return redirect(url_for("people.index"))

