# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Beta Tester Bug Tracker."""

import logging
import os

from flask import Flask, redirect, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup, escape

from .config import build_config
from .extensions import csrf, db, login_manager

__version__ = "2.0.0"
__author__ = "PrdAmrican"
__author_url__ = "https://github.com/PrdAmrican"
__license__ = "AGPL-3.0-or-later"
__source_url__ = "https://github.com/PrdAmrican/BugTracker2"


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.update(build_config(config_overrides))
    logging.basicConfig(level=logging.INFO)

    db.init_app(app)

    @app.before_request
    def larger_limit_for_restores():
        # Must run before CSRFProtect reads the form, or big restores get a 413.
        if request.endpoint == "backup.import_backup":
            restore_mb = int(os.environ.get("BUGTRACKER_MAX_RESTORE_MB", "1024"))
            request.max_content_length = max(restore_mb * 1024 * 1024,
                                             app.config["MAX_CONTENT_LENGTH"] or 0)

    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
        return user if user and user.can_login else None

    from .views import register_blueprints
    register_blueprints(app)

    _register_template_helpers(app)
    _register_request_hooks(app)
    _register_error_handlers(app)

    from .cli import register_cli
    register_cli(app)

    if not app.config.get("SKIP_DB_UPGRADE"):
        with app.app_context():
            from .migrations import upgrade_database
            upgrade_database(app)

    return app


# ── request hooks ────────────────────────────────────────────────────────────

PUBLIC_ENDPOINTS = {"static", "auth.login", "auth.setup", "auth.logout",
                    "about.index", "about.license_text"}


def _register_request_hooks(app):
    from .models import User

    @app.before_request
    def require_login():
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        # First run (or an upgraded v1 database): nobody can sign in yet.
        has_admin = db.session.query(
            User.query.filter(User.role == "admin", User.password_hash.isnot(None)).exists()
        ).scalar()
        if not has_admin:
            return redirect(url_for("auth.setup"))
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


# ── templates ────────────────────────────────────────────────────────────────

def _register_template_helpers(app):
    from .models import (
        ACTIVE_STATUSES, DONE_STATUSES, SEVERITIES, SEVERITY_LABELS,
        STATUS_LABELS, STATUSES,
    )

    # Jinja globals (not a context processor) so imported macros can see them.
    app.jinja_env.globals.update(
        APP_VERSION=__version__,
        APP_AUTHOR=__author__,
        APP_AUTHOR_URL=__author_url__,
        APP_LICENSE=__license__,
        SOURCE_URL=app.config["SOURCE_URL"],
        SEVERITIES=SEVERITIES,
        SEVERITY_LABELS=SEVERITY_LABELS,
        STATUSES=STATUSES,
        STATUS_LABELS=STATUS_LABELS,
        ACTIVE_STATUSES=ACTIVE_STATUSES,
        DONE_STATUSES=DONE_STATUSES,
    )

    @app.template_filter("iso")
    def iso(dt):
        return dt.isoformat(timespec="seconds") + "Z" if dt else ""

    @app.template_filter("localtime")
    def localtime(dt, style="datetime"):
        """Render a <time> tag; static/app.js converts it to the viewer's zone."""
        if not dt:
            return Markup("&ndash;")
        fallback = dt.strftime("%Y-%m-%d %H:%M UTC" if style != "date" else "%Y-%m-%d")
        return Markup(
            f'<time datetime="{iso(dt)}" data-style="{escape(style)}">{escape(fallback)}</time>'
        )

    @app.template_filter("filesize")
    def filesize(n):
        if n is None:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024

    @app.template_global()
    def url_with(**changes):
        """Current URL with some query arguments replaced (None removes)."""
        args = request.args.to_dict(flat=False)
        for key, value in changes.items():
            if value is None or value == "":
                args.pop(key, None)
            else:
                args[key] = [value]
        return url_for(request.endpoint, **(request.view_args or {}), **args)


# ── errors ───────────────────────────────────────────────────────────────────

def _register_error_handlers(app):
    def render_error(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return render_error(400, "Bad request", getattr(e, "description", "") or
                            "The request could not be understood.")

    @app.errorhandler(403)
    def forbidden(e):
        return render_error(403, "Not allowed", "You don't have permission to do that.")

    @app.errorhandler(404)
    def not_found(e):
        return render_error(404, "Not found", "That page or item doesn't exist.")

    @app.errorhandler(413)
    def too_large(e):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_error(413, "File too large", f"Uploads are limited to {limit} MB per request.")

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_error(500, "Something went wrong", "The error has been logged.")
