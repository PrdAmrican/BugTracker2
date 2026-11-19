# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
import csv
import io

import pytest

from bugtracker.extensions import db
from bugtracker.models import Bug, BugEvent, Comment, SWBuild

from conftest import add_bug, add_user, login


class TestCreate:
    def test_form_defaults_reporter_to_me(self, tester_client, tester):
        r = tester_client.get("/bugs/new")
        assert f'value="{tester.id}" selected'.encode() in r.data

    def test_create_minimal(self, tester_client, tester):
        r = tester_client.post("/bugs/new", data={"title": "Crash", "severity": "high"})
        bug = Bug.query.one()
        assert r.location.endswith(f"/bugs/{bug.id}")
        assert bug.status == "open" and bug.severity == "high"
        assert BugEvent.query.one().kind == "created"
        assert BugEvent.query.one().actor_id == tester.id

    def test_create_all_fields(self, tester_client, tester, lookups):
        tester_client.post("/bugs/new", data={
            "title": "  Freeze  ", "description": "Steps…", "severity": "critical",
            "reported_by": tester.id, "assigned_to": tester.id, "device": lookups["device"],
            "sw_build": lookups["build"], "mode": lookups["mode"], "tg": "TG-7",
        })
        bug = Bug.query.one()
        assert bug.title == "Freeze"
        assert (bug.device.name, bug.sw_build.name, bug.mode.name, bug.tg) == ("Phone X", "1.0.0", "Dark", "TG-7")
        assert bug.reporter == bug.assignee == tester

    def test_missing_title_keeps_input(self, tester_client):
        r = tester_client.post("/bugs/new", data={"title": "", "description": "keep me", "severity": "low"})
        assert r.status_code == 400
        assert b"Title is required" in r.data and b"keep me" in r.data
        assert Bug.query.count() == 0

    @pytest.mark.parametrize("data", [
        {"title": "x", "severity": "apocalyptic"},
        {"title": "x", "severity": "low", "device": "999"},
        {"title": "x", "severity": "low", "assigned_to": "abc"},
    ])
    def test_rejects_bad_values(self, tester_client, data):
        assert tester_client.post("/bugs/new", data=data).status_code == 400
        assert Bug.query.count() == 0

    def test_create_with_files(self, tester_client, app):
        r = tester_client.post("/bugs/new", data={
            "title": "With files", "severity": "low",
            "files": [(io.BytesIO(b"png"), "shot.png"), (io.BytesIO(b"log"), "app.log")],
        }, content_type="multipart/form-data")
        assert r.status_code == 302
        assert sorted(a.original_filename for a in Bug.query.one().attachments) == ["app.log", "shot.png"]

    def test_report_another_like_this_prefills_environment(self, tester_client, lookups):
        bug = add_bug(device_id=lookups["device"], sw_build_id=lookups["build"], tg="TG-1")
        r = tester_client.get(f"/bugs/new?like={bug.id}")
        assert f'value="{lookups["device"]}" selected'.encode() in r.data
        assert b'value="TG-1"' in r.data


class TestEditAndHistory:
    def test_edit_logs_changes(self, tester_client, tester, lookups):
        bug = add_bug(severity="low")
        tester_client.post(f"/bugs/{bug.id}/edit", data={
            "title": "Crash on launch", "severity": "high", "status": "in_progress",
            "sw_build": lookups["build"], "assigned_to": tester.id,
        })
        changes = {e.field: (e.old_value, e.new_value) for e in BugEvent.query.filter_by(kind="changed")}
        assert changes["severity"] == ("Low", "High")
        assert changes["status"] == ("Open", "In Progress")
        assert changes["SW build"] == (None, "1.0.0")
        assert changes["assignee"] == (None, "Tom Tester")
        assert "title" not in changes

    def test_resolving_sets_and_reopening_clears_resolved_at(self, tester_client):
        bug = add_bug()
        tester_client.post(f"/bugs/{bug.id}/quick", data={"status": "resolved"})
        assert db.session.get(Bug, bug.id).resolved_at is not None
        tester_client.post(f"/bugs/{bug.id}/quick", data={"status": "open"})
        assert db.session.get(Bug, bug.id).resolved_at is None

    def test_clear_optional_fields(self, tester_client, tester, lookups):
        bug = add_bug(device_id=lookups["device"], assigned_to_id=tester.id, tg="TG")
        tester_client.post(f"/bugs/{bug.id}/edit", data={"title": "t", "severity": "low", "status": "open",
                                                        "device": "", "assigned_to": "", "tg": ""})
        bug = db.session.get(Bug, bug.id)
        assert bug.device_id is None and bug.assigned_to_id is None and bug.tg is None

    def test_quick_assign_to_me_with_comment(self, tester_client, tester):
        bug = add_bug()
        tester_client.post(f"/bugs/{bug.id}/quick", data={"assigned_to": "me", "comment": "On it"})
        bug = db.session.get(Bug, bug.id)
        assert bug.assignee == tester
        assert bug.comments[0].body == "On it"

    def test_quick_rejects_bad_status(self, tester_client):
        bug = add_bug()
        assert tester_client.post(f"/bugs/{bug.id}/quick", data={"status": "bogus"}).status_code == 400

    def test_fixed_in_build(self, tester_client, lookups):
        bug = add_bug(status="resolved")
        tester_client.post(f"/bugs/{bug.id}/quick", data={"fixed_in_build": lookups["build2"]})
        assert db.session.get(Bug, bug.id).fixed_in_build.name == "1.1.0"

    def test_detail_shows_timeline(self, tester_client):
        bug = add_bug()
        tester_client.post(f"/bugs/{bug.id}/quick", data={"status": "needs_info", "comment": "Which device?"})
        r = tester_client.get(f"/bugs/{bug.id}")
        assert b"Which device?" in r.data and b"Needs Info" in r.data

    def test_unknown_bug_404(self, tester_client):
        assert tester_client.get("/bugs/9999").status_code == 404
        assert tester_client.get("/bugs/9999/edit").status_code == 404


class TestDelete:
    def test_admin_can_delete_any_bug(self, admin_client, app):
        bug = add_bug()
        db.session.add(Comment(bug=bug, body="hi"))
        db.session.commit()
        r = admin_client.post(f"/bugs/{bug.id}/delete")
        assert r.status_code == 302
        assert Bug.query.count() == 0 and Comment.query.count() == 0

    def test_tester_can_delete_only_own_bugs(self, tester_client, tester, admin):
        mine = add_bug(reported_by_id=tester.id)
        theirs = add_bug(reported_by_id=admin.id)
        assert tester_client.post(f"/bugs/{theirs.id}/delete").status_code == 403
        assert tester_client.post(f"/bugs/{mine.id}/delete").status_code == 302
        assert [b.id for b in Bug.query] == [theirs.id]


class TestComments:
    def test_add_and_delete_own_comment(self, tester_client):
        bug = add_bug()
        tester_client.post(f"/bugs/{bug.id}/comments", data={"body": "Repro on 1.1"})
        comment = Comment.query.one()
        assert tester_client.post(f"/comments/{comment.id}/delete").status_code == 302
        assert Comment.query.count() == 0

    def test_empty_comment_rejected(self, tester_client):
        bug = add_bug()
        tester_client.post(f"/bugs/{bug.id}/comments", data={"body": "   "})
        assert Comment.query.count() == 0

    def test_cannot_delete_someone_elses_comment(self, tester_client, admin):
        bug = add_bug()
        c = Comment(bug=bug, author_id=admin.id, body="mine")
        db.session.add(c)
        db.session.commit()
        assert tester_client.post(f"/comments/{c.id}/delete").status_code == 403


class TestList:
    @pytest.fixture
    def bugs(self, tester, admin, lookups):
        return {
            "a": add_bug(title="Login crash", severity="critical", status="open",
                         assigned_to_id=tester.id, device_id=lookups["device"]),
            "b": add_bug(title="Typo", severity="low", status="resolved", description="spelling in crash dialog"),
            "c": add_bug(title="Slow sync", severity="high", status="in_progress",
                         assigned_to_id=admin.id, sw_build_id=lookups["build"], tg="TG-99"),
        }

    def titles(self, client, query):
        r = client.get("/bugs?" + query)
        assert r.status_code == 200
        return {t for t in ("Login crash", "Typo", "Slow sync") if t.encode() in r.data}

    def test_filters(self, tester_client, bugs, lookups):
        assert self.titles(tester_client, "") == {"Login crash", "Typo", "Slow sync"}
        assert self.titles(tester_client, "status=active") == {"Login crash", "Slow sync"}
        assert self.titles(tester_client, "status=done") == {"Typo"}
        assert self.titles(tester_client, "status=in_progress") == {"Slow sync"}
        assert self.titles(tester_client, "severity=critical") == {"Login crash"}
        assert self.titles(tester_client, "assignee=me") == {"Login crash"}
        assert self.titles(tester_client, "assignee=none") == {"Typo"}
        assert self.titles(tester_client, f"device={lookups['device']}") == {"Login crash"}
        assert self.titles(tester_client, f"build={lookups['build']}") == {"Slow sync"}

    def test_search(self, tester_client, bugs):
        assert self.titles(tester_client, "q=crash") == {"Login crash", "Typo"}  # title + description
        assert self.titles(tester_client, "q=TG-99") == {"Slow sync"}
        assert self.titles(tester_client, f"q=%23{bugs['b'].id}") == {"Typo"}

    def test_sort_by_severity(self, tester_client, bugs):
        r = tester_client.get("/bugs?sort=severity&dir=desc").data
        assert r.index(b"Login crash") < r.index(b"Slow sync") < r.index(b"Typo")

    def test_bad_parameters_do_not_crash(self, tester_client, bugs):
        r = tester_client.get("/bugs?assignee=abc&severity=x&status=y&sort=z&page=-4&device=q")
        assert r.status_code == 200

    def test_pagination(self, tester_client, app):
        app.config["BUGS_PER_PAGE"] = 5
        for i in range(12):
            add_bug(title=f"Bug number {i:02d}")
        r = tester_client.get("/bugs?sort=id&dir=asc&page=3")
        assert b"Bug number 10" in r.data and b"Bug number 04" not in r.data
        assert b"12 bugs" in r.data

    def test_csv_export_respects_filters(self, tester_client, bugs):
        r = tester_client.get("/bugs/export.csv?status=active")
        rows = list(csv.DictReader(io.StringIO(r.data.decode("utf-8-sig"))))
        assert {row["title"] for row in rows} == {"Login crash", "Slow sync"}


class TestAttachments:
    def upload(self, client, bug_id, *files):
        return client.post(f"/bugs/{bug_id}/attach",
                           data={"files": [(io.BytesIO(data), name) for name, data in files]},
                           content_type="multipart/form-data")

    def test_upload_view_and_delete(self, tester_client, app, tester):
        import os
        bug = add_bug(reported_by_id=tester.id)
        self.upload(tester_client, bug.id, ("screen shot.png", b"PNGDATA"), ("crash.log", b"trace"))
        atts = {a.original_filename: a for a in db.session.get(Bug, bug.id).attachments}
        assert set(atts) == {"screen_shot.png", "crash.log"}
        png = atts["screen_shot.png"]
        assert png.size_bytes == 7 and png.uploaded_by_id == tester.id

        r = tester_client.get(f"/attachments/{png.id}/x")
        assert r.data == b"PNGDATA" and r.mimetype == "image/png"
        assert "attachment" not in r.headers.get("Content-Disposition", "")

        path = os.path.join(app.config["UPLOAD_DIR"], png.filename)
        assert os.path.exists(path)
        tester_client.post(f"/attachments/{png.id}/delete")
        assert not os.path.exists(path)
        assert BugEvent.query.filter_by(kind="attachment_removed").count() == 1

    def test_zip_is_downloaded_not_shown(self, tester_client):
        bug = add_bug()
        self.upload(tester_client, bug.id, ("logs.zip", b"PK.."))
        att = db.session.get(Bug, bug.id).attachments[0]
        r = tester_client.get(f"/attachments/{att.id}/logs.zip")
        assert "attachment" in r.headers["Content-Disposition"]

    def test_disallowed_type(self, tester_client):
        bug = add_bug()
        r = self.upload(tester_client, bug.id, ("evil.html", b"<script>"))
        assert r.status_code == 302
        assert db.session.get(Bug, bug.id).attachments == []

    def test_no_file(self, tester_client):
        bug = add_bug()
        assert tester_client.post(f"/bugs/{bug.id}/attach", data={}).status_code == 302

    def test_deleting_bug_removes_files(self, admin_client, app):
        import os
        bug = add_bug()
        self.upload(admin_client, bug.id, ("a.png", b"x"))
        path = os.path.join(app.config["UPLOAD_DIR"], db.session.get(Bug, bug.id).attachments[0].filename)
        admin_client.post(f"/bugs/{bug.id}/delete")
        assert not os.path.exists(path)

    def test_legacy_upload_url_redirects(self, tester_client):
        bug = add_bug()
        self.upload(tester_client, bug.id, ("a.png", b"x"))
        att = db.session.get(Bug, bug.id).attachments[0]
        r = tester_client.get(f"/uploads/{att.filename}")
        assert r.status_code == 302 and f"/attachments/{att.id}/" in r.location

    def test_other_tester_cannot_delete_attachment(self, client, admin, tester):
        other = add_user("Olga", "olga@example.com")
        bug = add_bug(reported_by_id=admin.id)
        login(client, other.email)
        self.upload(client, bug.id, ("a.png", b"x"))
        att_id = db.session.get(Bug, bug.id).attachments[0].id
        client.post("/logout")
        login(client, tester.email)
        assert client.post(f"/attachments/{att_id}/delete").status_code == 403


class TestInlineLookups:
    def test_add_and_duplicate(self, tester_client):
        r = tester_client.post("/api/sw_builds", data={"name": "2.0.0"})
        assert r.json["name"] == "2.0.0"
        r = tester_client.post("/api/sw_builds", data={"name": "2.0.0 "})
        assert r.status_code == 409 and r.json["id"]

    def test_empty_and_unknown(self, tester_client):
        assert tester_client.post("/api/devices", data={"name": " "}).status_code == 400
        assert tester_client.post("/api/planets", data={"name": "x"}).status_code == 404

    def test_restores_archived(self, tester_client):
        b = SWBuild(name="0.9", archived=True)
        db.session.add(b)
        db.session.commit()
        r = tester_client.post("/api/sw_builds", data={"name": "0.9"})
        assert r.status_code == 200 and r.json["restored"]
        assert db.session.get(SWBuild, b.id).archived is False


def test_dashboard(tester_client, tester):
    add_bug(severity="critical", assigned_to_id=tester.id, title="Mine and critical")
    add_bug(status="closed")
    r = tester_client.get("/")
    assert r.status_code == 200
    assert b"Mine and critical" in r.data  # in "Assigned to me"
