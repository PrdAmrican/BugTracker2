# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Sign-in, first-run setup and the user's own account page."""

from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from ..extensions import db
from ..models import User, utcnow
from ..services import MIN_PASSWORD_LENGTH, clean

bp = Blueprint("auth", __name__)


def _admin_exists():
    return User.query.filter(User.role == "admin", User.password_hash.isnot(None)).first() is not None


def _safe_next(target):
    """Only follow redirects to paths on this site."""
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def find_user_by_email(email):
    return User.query.filter(func.lower(User.email) == email.lower()).first()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not _admin_exists():
        return redirect(url_for("auth.setup"))
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    email = ""
    if request.method == "POST":
        email = clean(request.form.get("email"))
        password = request.form.get("password", "")
        user = find_user_by_email(email) if email else None
        if user and user.can_login and user.check_password(password):
            user.last_login_at = utcnow()
            db.session.commit()
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(_safe_next(request.args.get("next")) or url_for("dashboard.index"))
        flash("Email or password is incorrect.", "danger")

    return render_template("auth/login.html", email=email)


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("You've been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """Create the first admin. Only reachable while no admin can sign in."""
    if _admin_exists():
        return redirect(url_for("auth.login"))

    existing_testers = User.query.count()
    form = {"name": "", "email": ""}
    if request.method == "POST":
        form["name"] = clean(request.form.get("name"), 120)
        form["email"] = clean(request.form.get("email"), 120)
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if not form["name"] or not form["email"]:
            errors.append("Name and email are required.")
        if "@" not in form["email"]:
            errors.append("Enter a valid email address.")
        if len(password) < MIN_PASSWORD_LENGTH:
            errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if password != confirm:
            errors.append("Passwords don't match.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            # Upgrading from v1: reuse the existing tester record with that email.
            user = find_user_by_email(form["email"])
            if user is None:
                user = User(name=form["name"], email=form["email"])
                db.session.add(user)
            else:
                user.name = form["name"]
            user.role = "admin"
            user.active = True
            user.set_password(password)
            user.last_login_at = utcnow()
            db.session.commit()
            login_user(user)
            flash("Admin account created. Welcome!", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/setup.html", form=form, existing_testers=existing_testers,
                           min_length=MIN_PASSWORD_LENGTH)


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = clean(request.form.get("name"), 120)
            if not name:
                flash("Name can't be empty.", "danger")
            else:
                current_user.name = name
                db.session.commit()
                flash("Profile updated.", "success")
        elif action == "password":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            if not current_user.check_password(current):
                flash("Your current password is incorrect.", "danger")
            elif len(new) < MIN_PASSWORD_LENGTH:
                flash(f"New password must be at least {MIN_PASSWORD_LENGTH} characters.", "danger")
            elif new != confirm:
                flash("New passwords don't match.", "danger")
            else:
                current_user.set_password(new)
                db.session.commit()
                flash("Password changed.", "success")
        return redirect(url_for("auth.account"))

    return render_template("auth/account.html", min_length=MIN_PASSWORD_LENGTH)
