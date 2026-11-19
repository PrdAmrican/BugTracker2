# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bugtracker import create_app  # noqa: E402
from bugtracker.extensions import db  # noqa: E402
from bugtracker.models import Bug, Device, Mode, SWBuild, User  # noqa: E402

PASSWORD = "correct-horse"


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """Factory for an app whose data lives in a throwaway folder."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def factory(**overrides):
        config = {"TESTING": True, "WTF_CSRF_ENABLED": False, "SECRET_KEY": "test",
                  "DATA_DIR": str(tmp_path)}
        config.update(overrides)
        return create_app(config)
    return factory


@pytest.fixture
def app(make_app):
    app = make_app()
    with app.app_context():
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


def add_user(name="Alice", email="alice@example.com", role="tester", password=PASSWORD, active=True):
    user = User(name=name, email=email, role=role, active=active)
    if password:
        user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def login(client, email, password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


@pytest.fixture
def admin(app):
    return add_user("Ann Admin", "admin@example.com", role="admin")


@pytest.fixture
def tester(app, admin):
    return add_user("Tom Tester", "tom@example.com")


@pytest.fixture
def admin_client(client, admin):
    login(client, admin.email)
    return client


@pytest.fixture
def tester_client(client, tester):
    login(client, tester.email)
    return client


@pytest.fixture
def lookups(app):
    d, b, b2, m = Device(name="Phone X"), SWBuild(name="1.0.0"), SWBuild(name="1.1.0"), Mode(name="Dark")
    db.session.add_all([d, b, b2, m])
    db.session.commit()
    return {"device": d.id, "build": b.id, "build2": b2.id, "mode": m.id}


def add_bug(**kwargs):
    defaults = {"title": "Crash on launch", "severity": "medium", "status": "open"}
    defaults.update(kwargs)
    bug = Bug(**defaults)
    db.session.add(bug)
    db.session.commit()
    return bug
