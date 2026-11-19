# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""About page: version, creator, license and source code.

Public (no sign-in needed) so anyone using the site can see the license
and reach the source code, as the AGPL expects.
"""

import os
import platform
from importlib.metadata import PackageNotFoundError, version

from flask import Blueprint, Response, abort, current_app, render_template
from flask_login import current_user
from sqlalchemy.engine import make_url

from .. import __author__, __author_url__, __license__, __version__
from ..config import PROJECT_ROOT
from ..extensions import db
from ..migrations import current_version
from ..models import Attachment, Bug, Comment, User

bp = Blueprint("about", __name__)

COMPONENTS = [
    # (name, distribution for version lookup, license, homepage)
    ("Flask", "flask", "BSD-3-Clause", "https://flask.palletsprojects.com/"),
    ("Flask-SQLAlchemy", "flask-sqlalchemy", "BSD-3-Clause", "https://flask-sqlalchemy.readthedocs.io/"),
    ("SQLAlchemy", "sqlalchemy", "MIT", "https://www.sqlalchemy.org/"),
    ("Flask-Login", "flask-login", "MIT", "https://flask-login.readthedocs.io/"),
    ("Flask-WTF", "flask-wtf", "BSD-3-Clause", "https://flask-wtf.readthedocs.io/"),
    ("Waitress", "waitress", "ZPL-2.1", "https://docs.pylonsproject.org/projects/waitress/"),
    ("Bootstrap 5.3", None, "MIT", "https://getbootstrap.com/"),
    ("Bootstrap Icons 1.11", None, "MIT", "https://icons.getbootstrap.com/"),
]


def _version(dist):
    if not dist:
        return None
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


@bp.route("/about")
def index():
    components = [
        {"name": n, "version": _version(d), "license": lic, "url": url, "installed": d is None or _version(d)}
        for n, d, lic, url in COMPONENTS
    ]
    components = [c for c in components if c["installed"]]

    system = None
    if current_user.is_authenticated and current_user.is_admin:
        url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
        system = {
            "Python": platform.python_version(),
            "Operating system": f"{platform.system()} {platform.release()}",
            "Database": (f"SQLite — {url.database}" if url.get_backend_name() == "sqlite"
                         else url.render_as_string(hide_password=True)),
            "Schema version": current_version(),
            "Data folder": current_app.config["DATA_DIR"],
            "Uploads folder": current_app.config["UPLOAD_DIR"],
            "Upload limit": f"{current_app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB",
            "Bugs / comments / files / testers": " / ".join(str(n) for n in (
                Bug.query.count(), Comment.query.count(), Attachment.query.count(), User.query.count())),
        }

    return render_template(
        "about.html",
        version=__version__, author=__author__, author_url=__author_url__,
        license_id=__license__, components=components, system=system,
    )


@bp.route("/about/license")
def license_text():
    path = os.path.join(PROJECT_ROOT, "LICENSE")
    if not os.path.exists(path):
        abort(404)
    with open(path, encoding="utf-8") as fh:
        return Response(fh.read(), mimetype="text/plain")
