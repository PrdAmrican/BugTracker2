# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
from bugtracker.extensions import db
from bugtracker.models import Bug, Comment, Device, SWBuild, User

from conftest import PASSWORD, add_bug, add_user, login


class TestPermissions:
    def test_tester_cannot_reach_admin_pages(self, tester_client, tester):
        for url in ("/settings/", "/backup/", "/backup/export.json", "/backup/full.zip",
                    f"/people/{tester.id}/edit"):
            assert tester_client.get(url).status_code == 403, url
        assert tester_client.post("/people/", data={"name": "x", "email": "x@x.com"}).status_code == 403
        assert tester_client.post("/settings/devices/add", data={"names": "x"}).status_code == 403

    def test_tester_can_view_people(self, tester_client):
        assert tester_client.get("/people/").status_code == 200


class TestPeople:
    def test_add_with_and_without_login(self, admin_client):
        admin_client.post("/people/", data={"name": "Pat", "email": "pat@example.com",
                                            "role": "tester", "password": "temp-pass1"})
        admin_client.post("/people/", data={"name": "Rec", "email": "rec@example.com", "role": "tester"})
        pat = User.query.filter_by(email="pat@example.com").one()
        rec = User.query.filter_by(email="rec@example.com").one()
        assert pat.can_login and not rec.can_login

    def test_duplicate_email_case_insensitive(self, admin_client, tester):
        admin_client.post("/people/", data={"name": "Dup", "email": "TOM@example.com", "role": "tester"})
        assert User.query.count() == 2

    def test_short_password_rejected(self, admin_client):
        admin_client.post("/people/", data={"name": "P", "email": "p@example.com", "role": "tester",
                                            "password": "short"})
        assert User.query.filter_by(email="p@example.com").first() is None

    def test_edit_role_and_reset_password(self, admin_client, tester):
        r = admin_client.post(f"/people/{tester.id}/edit", data={
            "name": "Tom", "email": tester.email, "role": "admin", "active": "1", "password": "reset-pass1"})
        assert r.status_code == 302
        tom = db.session.get(User, tester.id)
        assert tom.is_admin and tom.check_password("reset-pass1")

    def test_cannot_remove_last_admin(self, admin_client, admin):
        r = admin_client.post(f"/people/{admin.id}/edit", data={
            "name": admin.name, "email": admin.email, "role": "tester", "active": "1"})
        assert r.status_code == 400
        assert db.session.get(User, admin.id).is_admin

    def test_cannot_delete_self(self, admin_client, admin):
        admin_client.post(f"/people/{admin.id}/delete")
        assert db.session.get(User, admin.id) is not None

    def test_delete_keeps_bugs_and_comments(self, admin_client, tester):
        bug = add_bug(reported_by_id=tester.id, assigned_to_id=tester.id)
        db.session.add(Comment(bug=bug, author_id=tester.id, body="hello"))
        db.session.commit()
        admin_client.post(f"/people/{tester.id}/delete")
        assert db.session.get(User, tester.id) is None
        bug = db.session.get(Bug, bug.id)
        assert bug.reported_by_id is None and bug.assigned_to_id is None
        assert Comment.query.one().author_id is None
        assert admin_client.get(f"/bugs/{bug.id}").status_code == 200


class TestSettings:
    def test_add_several(self, admin_client):
        admin_client.post("/settings/sw_builds/add", data={"names": "1.0\n1.1\n\n1.0\n"})
        assert sorted(b.name for b in SWBuild.query) == ["1.0", "1.1"]

    def test_rename_and_clash(self, admin_client, lookups):
        admin_client.post(f"/settings/sw_builds/{lookups['build']}/rename", data={"name": "1.1.0"})
        assert db.session.get(SWBuild, lookups["build"]).name == "1.0.0"
        admin_client.post(f"/settings/sw_builds/{lookups['build']}/rename", data={"name": "1.0.0-rc"})
        assert db.session.get(SWBuild, lookups["build"]).name == "1.0.0-rc"

    def test_archive_hides_from_new_bug_form(self, admin_client, lookups):
        admin_client.post(f"/settings/devices/{lookups['device']}/archive")
        assert db.session.get(Device, lookups["device"]).archived
        assert b">Phone X<" not in admin_client.get("/bugs/new").data
        # …but an existing bug that uses it still shows it when edited
        bug = add_bug(device_id=lookups["device"])
        assert b"Phone X (archived)" in admin_client.get(f"/bugs/{bug.id}/edit").data

    def test_delete_only_when_unused(self, admin_client, lookups):
        add_bug(fixed_in_build_id=lookups["build2"])
        admin_client.post(f"/settings/sw_builds/{lookups['build2']}/delete")
        assert db.session.get(SWBuild, lookups["build2"]) is not None
        admin_client.post(f"/settings/sw_builds/{lookups['build']}/delete")
        assert db.session.get(SWBuild, lookups["build"]) is None

    def test_settings_page_renders_each_kind(self, admin_client, lookups):
        add_bug(device_id=lookups["device"], sw_build_id=lookups["build"], mode_id=lookups["mode"])
        for kind in ("devices", "sw_builds", "modes"):
            assert admin_client.get(f"/settings/?kind={kind}").status_code == 200
