# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
import io
import json
import os
import sqlite3
import zipfile

import pytest

from bugtracker import create_app
from bugtracker.extensions import db
from bugtracker.models import Attachment, Bug, BugEvent, Comment, Device, SWBuild, User

from conftest import PASSWORD, add_bug, add_user, login

# A backup exactly as v1's "Export as JSON" wrote it.
V1_BACKUP = {
    "exported_at": "2025-03-01T10:00:00+00:00",
    "devices": [{"id": 1, "name": "Phone X"}],
    "sw_builds": [{"id": 1, "name": "v1.0.0"}],
    "modes": [{"id": 1, "name": "Dark"}],
    "testers": [{"id": 1, "name": "Alice", "email": "alice@example.com",
                 "created_at": "2025-01-01T09:00:00"}],
    "bugs": [
        {"id": 7, "title": "Crash on launch", "description": "Splash then crash", "severity": "critical",
         "status": "resolved", "reported_by_id": 1, "assigned_to_id": 1, "device_id": 1,
         "sw_build_id": 1, "mode_id": 1, "tg": "TG-42",
         "created_at": "2025-01-02T09:00:00", "updated_at": "2025-01-03T09:00:00"},
        {"id": 8, "title": "Ghost tester", "description": None, "severity": "low", "status": "open",
         "reported_by_id": 99, "assigned_to_id": None, "device_id": None, "sw_build_id": None,
         "mode_id": None, "tg": None, "created_at": None, "updated_at": None},
    ],
    "attachments": [{"id": 1, "bug_id": 7, "filename": "abc123.png", "original_filename": "shot.png",
                     "uploaded_at": "2025-01-02T09:05:00"}],
}

V1_SCHEMA = """
CREATE TABLE devices (id INTEGER NOT NULL, name VARCHAR(120) NOT NULL, PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE sw_builds (id INTEGER NOT NULL, name VARCHAR(120) NOT NULL, PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE modes (id INTEGER NOT NULL, name VARCHAR(120) NOT NULL, PRIMARY KEY (id), UNIQUE (name));
CREATE TABLE testers (id INTEGER NOT NULL, name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL,
    created_at DATETIME, PRIMARY KEY (id), UNIQUE (email));
CREATE TABLE bugs (id INTEGER NOT NULL, title VARCHAR(200) NOT NULL, description TEXT,
    severity VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, reported_by_id INTEGER,
    assigned_to_id INTEGER, device_id INTEGER, sw_build_id INTEGER, mode_id INTEGER, tg VARCHAR(120),
    created_at DATETIME, updated_at DATETIME, PRIMARY KEY (id),
    FOREIGN KEY(reported_by_id) REFERENCES testers (id), FOREIGN KEY(assigned_to_id) REFERENCES testers (id),
    FOREIGN KEY(device_id) REFERENCES devices (id), FOREIGN KEY(sw_build_id) REFERENCES sw_builds (id),
    FOREIGN KEY(mode_id) REFERENCES modes (id));
CREATE TABLE attachments (id INTEGER NOT NULL, bug_id INTEGER NOT NULL, filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL, uploaded_at DATETIME, PRIMARY KEY (id),
    FOREIGN KEY(bug_id) REFERENCES bugs (id));
"""


def restore(client, payload, filename="backup.json", confirm="REPLACE"):
    return client.post("/backup/import", data={
        "file": (io.BytesIO(payload), filename), "confirm": confirm,
    }, content_type="multipart/form-data")


@pytest.fixture
def populated(admin, tester, lookups):
    bug = add_bug(title="Original bug", severity="high", reported_by_id=tester.id,
                  sw_build_id=lookups["build"], tg="TG-1")
    db.session.add(Comment(bug=bug, author_id=tester.id, body="A comment"))
    db.session.add(BugEvent(bug=bug, actor_id=tester.id, kind="created"))
    db.session.commit()
    return bug


class TestExport:
    def test_json(self, admin_client, populated):
        data = json.loads(admin_client.get("/backup/export.json").data)
        assert data["format_version"] == 2
        assert data["bugs"][0]["title"] == "Original bug"
        assert data["comments"][0]["body"] == "A comment"
        assert {t["email"] for t in data["testers"]} == {"admin@example.com", "tom@example.com"}

    def test_csv_zip(self, admin_client, populated):
        zf = zipfile.ZipFile(io.BytesIO(admin_client.get("/backup/csv.zip").data))
        assert {"bugs.csv", "comments.csv", "testers.csv", "devices.csv", "sw_builds.csv",
                "modes.csv", "attachments.csv", "history.csv"} <= set(zf.namelist())
        bugs_csv = zf.read("bugs.csv").decode("utf-8-sig")
        assert "Original bug" in bugs_csv and "Tom Tester" in bugs_csv and "1.0.0" in bugs_csv

    def test_sqlite_copy_is_a_valid_database(self, admin_client, populated, tmp_path):
        r = admin_client.get("/backup/bugs.db")
        path = tmp_path / "copy.db"
        path.write_bytes(r.data)
        rows = sqlite3.connect(path).execute("SELECT title FROM bugs").fetchall()
        assert rows == [("Original bug",)]


class TestRestore:
    def test_json_round_trip(self, admin_client, populated):
        backup = admin_client.get("/backup/export.json").data
        add_bug(title="Added after backup")
        r = restore(admin_client, backup)
        assert r.status_code == 302
        assert [b.title for b in Bug.query] == ["Original bug"]
        assert Comment.query.one().body == "A comment"
        assert admin_client.get("/").status_code == 200  # still signed in

    def test_full_zip_round_trip_restores_files(self, admin_client, app, populated):
        admin_client.post(f"/bugs/{populated.id}/attach",
                          data={"files": [(io.BytesIO(b"IMAGE"), "shot.png")]},
                          content_type="multipart/form-data")
        stored = Attachment.query.one().filename
        backup = admin_client.get("/backup/full.zip").data
        assert f"attachments/{stored}" in zipfile.ZipFile(io.BytesIO(backup)).namelist()

        os.remove(os.path.join(app.config["UPLOAD_DIR"], stored))
        Attachment.query.delete()
        db.session.commit()

        restore(admin_client, backup, "full.zip")
        att = Attachment.query.one()
        assert admin_client.get(f"/attachments/{att.id}/shot.png").data == b"IMAGE"

    def test_v1_backup_imports_and_keeps_current_admin(self, admin_client, admin):
        r = restore(admin_client, json.dumps(V1_BACKUP).encode())
        assert r.status_code == 302
        assert admin_client.get("/").status_code == 200  # not locked out
        me = User.query.filter_by(email="admin@example.com").one()
        assert me.is_admin and me.check_password(PASSWORD)
        assert User.query.filter_by(email="alice@example.com").one().password_hash is None
        crash = db.session.get(Bug, 7)
        assert crash.reporter.name == "Alice" and crash.device.name == "Phone X"
        assert crash.resolved_at is not None  # inferred from updated_at
        assert db.session.get(Bug, 8).reported_by_id is None  # dangling reference cleared

    def test_snapshot_written_before_restore(self, admin_client, app, populated):
        restore(admin_client, json.dumps(V1_BACKUP).encode())
        snaps = os.listdir(app.config["BACKUP_DIR"])
        assert len(snaps) == 1 and snaps[0].startswith("pre-import")
        snapshot = json.load(open(os.path.join(app.config["BACKUP_DIR"], snaps[0])))
        assert snapshot["bugs"][0]["title"] == "Original bug"
        assert admin_client.get("/backup/").status_code == 200
        assert admin_client.get(f"/backup/snapshots/{snaps[0]}").status_code == 200
        assert admin_client.get("/backup/snapshots/..%2Fbugs.db").status_code == 404

    @pytest.mark.parametrize("payload, filename", [
        (b"{not json", "x.json"),
        (b"[]", "x.json"),
        (json.dumps({"hello": "world"}).encode(), "x.json"),
        (json.dumps(dict(V1_BACKUP, bugs=[dict(V1_BACKUP["bugs"][0], severity="extreme")])).encode(), "x.json"),
        (json.dumps(dict(V1_BACKUP, testers=V1_BACKUP["testers"] * 2)).encode(), "x.json"),
        (json.dumps(dict(V1_BACKUP, attachments=[dict(V1_BACKUP["attachments"][0], filename="../../etc")])).encode(), "x.json"),
        (json.dumps({"format_version": 99, "bugs": []}).encode(), "x.json"),
        (b"PK not really a zip", "x.zip"),
    ])
    def test_bad_backups_change_nothing(self, admin_client, populated, payload, filename):
        r = restore(admin_client, payload, filename)
        assert r.status_code == 302
        assert [b.title for b in Bug.query] == ["Original bug"]
        assert b"nothing was changed" in admin_client.get("/backup/").data

    def test_requires_typed_confirmation(self, admin_client, populated):
        restore(admin_client, json.dumps(V1_BACKUP).encode(), confirm="yes")
        assert [b.title for b in Bug.query] == ["Original bug"]


class TestUpgradeFromV1:
    def make_v1_database(self, data_dir):
        conn = sqlite3.connect(data_dir / "bugs.db")
        conn.executescript(V1_SCHEMA)
        conn.executescript("""
            INSERT INTO testers VALUES (1, 'Alice', 'alice@example.com', '2025-01-01 09:00:00');
            INSERT INTO testers VALUES (2, 'Bob', 'bob@example.com', '2025-01-01 09:00:00');
            INSERT INTO devices VALUES (1, 'Phone X');
            INSERT INTO sw_builds VALUES (1, 'v1.0.0');
            INSERT INTO bugs VALUES (1, 'Crash', 'desc', 'critical', 'open', 1, 2, 1, 1, NULL, 'TG',
                                     '2025-01-02 09:00:00', '2025-01-02 09:00:00');
            INSERT INTO bugs VALUES (2, 'Done', NULL, 'low', 'closed', 3, NULL, NULL, NULL, NULL, NULL,
                                     '2025-01-02 09:00:00', '2025-01-05 09:00:00');
            INSERT INTO attachments VALUES (1, 1, 'f00.png', 'shot.png', '2025-01-02 09:00:00');
        """)
        conn.commit()
        conn.close()
        (data_dir / "uploads").mkdir()
        (data_dir / "uploads" / "f00.png").write_bytes(b"12345")

    def test_upgrade_in_place(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        self.make_v1_database(tmp_path)
        app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "SECRET_KEY": "t",
                          "DATA_DIR": str(tmp_path)})
        client = app.test_client()
        with app.app_context():
            crash = db.session.get(Bug, 1)
            assert crash.reporter.name == "Alice" and crash.assignee.name == "Bob"
            assert crash.attachments[0].size_bytes == 5
            done = db.session.get(Bug, 2)
            assert done.reported_by_id is None          # tester 3 never existed
            assert done.resolved_at is not None
            assert SWBuild.query.one().archived is False
            assert User.query.filter_by(email="alice@example.com").one().role == "tester"

            # nobody can sign in yet, so the app asks for an admin
            assert client.get("/").location.endswith("/setup")
            assert b"upgraded" in client.get("/setup").data
            client.post("/setup", data={"name": "Alice A.", "email": "alice@example.com",
                                        "password": PASSWORD, "confirm": PASSWORD})
            alice = User.query.filter_by(email="alice@example.com").one()
            assert alice.is_admin and alice.name == "Alice A."
            assert b"Crash" in client.get("/bugs").data
            r = client.get("/uploads/f00.png")  # v1 attachment link
            assert r.status_code == 302

        # starting again is a no-op
        app2 = create_app({"TESTING": True, "SECRET_KEY": "t", "DATA_DIR": str(tmp_path)})
        with app2.app_context():
            assert Bug.query.count() == 2

    def test_fresh_database_gets_all_tables(self, app):
        tables = set(db.inspect(db.engine).get_table_names())
        assert {"bugs", "testers", "comments", "bug_events", "app_meta"} <= tables


class TestCli:
    def test_create_admin_backup_restore(self, make_app, tmp_path):
        app = make_app()
        runner = app.test_cli_runner()
        r = runner.invoke(args=["create-admin", "--email", "cli@example.com", "--name", "Cli",
                                "--password", PASSWORD])
        assert r.exit_code == 0, r.output
        with app.app_context():
            assert User.query.one().is_admin
            add_bug(title="CLI bug")

        out = tmp_path / "b.zip"
        assert runner.invoke(args=["backup", str(out)]).exit_code == 0
        with app.app_context():
            add_bug(title="Later bug")
        r = runner.invoke(args=["restore", str(out), "--yes"])
        assert r.exit_code == 0, r.output
        with app.app_context():
            assert [b.title for b in Bug.query] == ["CLI bug"]

        r = runner.invoke(args=["set-password", "--email", "cli@example.com", "--password", "another-pass"])
        assert r.exit_code == 0
        with app.app_context():
            assert User.query.one().check_password("another-pass")


def test_restore_allows_files_bigger_than_upload_limit(make_app):
    """Full backups can exceed MAX_CONTENT_LENGTH; CSRF checks must not 413 them."""
    import re
    app = make_app(WTF_CSRF_ENABLED=True, MAX_CONTENT_LENGTH=2048)
    with app.app_context():
        add_user("Ann", "admin@example.com", role="admin")
    client = app.test_client()
    token = re.search(rb'name="csrf_token" value="([^"]+)"', client.get("/login").data).group(1).decode()
    client.post("/login", data={"email": "admin@example.com", "password": PASSWORD, "csrf_token": token})
    big = dict(V1_BACKUP, bugs=V1_BACKUP["bugs"] + [
        dict(V1_BACKUP["bugs"][1], id=100 + i, title="x" * 150) for i in range(40)])
    payload = json.dumps(big).encode()
    assert len(payload) > 2048
    r = client.post("/backup/import", data={"file": (io.BytesIO(payload), "b.json"), "confirm": "REPLACE",
                                             "csrf_token": token}, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        assert Bug.query.count() == 42
    # other routes keep the normal limit
    r = client.post("/bugs/new", data={"title": "t", "severity": "low", "csrf_token": token,
                                       "files": (io.BytesIO(b"x" * 5000), "big.log")},
                    content_type="multipart/form-data")
    assert r.status_code == 413
