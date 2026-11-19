# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
from bugtracker.extensions import db
from bugtracker.models import User

from conftest import PASSWORD, add_user, login


class TestFirstRun:
    def test_everything_redirects_to_setup_without_admin(self, client):
        for url in ("/", "/bugs", "/login", "/backup/"):
            r = client.get(url)
            assert r.status_code == 302 and r.location.endswith("/setup"), url

    def test_setup_creates_admin_and_signs_in(self, client):
        r = client.post("/setup", data={"name": "Ann", "email": "ann@example.com",
                                        "password": PASSWORD, "confirm": PASSWORD})
        assert r.status_code == 302
        user = User.query.one()
        assert user.is_admin and user.check_password(PASSWORD)
        assert client.get("/").status_code == 200

    def test_setup_validates(self, client):
        r = client.post("/setup", data={"name": "Ann", "email": "ann@example.com",
                                        "password": "short", "confirm": "short"})
        assert r.status_code == 200 and b"at least 8" in r.data
        r = client.post("/setup", data={"name": "Ann", "email": "ann@example.com",
                                        "password": PASSWORD, "confirm": PASSWORD + "x"})
        assert b"match" in r.data
        assert User.query.count() == 0

    def test_setup_promotes_existing_tester_with_same_email(self, client):
        add_user("Old Record", "Ann@Example.com", password=None)
        client.post("/setup", data={"name": "Ann", "email": "ann@example.com",
                                    "password": PASSWORD, "confirm": PASSWORD})
        assert User.query.count() == 1
        assert User.query.one().is_admin

    def test_setup_closed_once_admin_exists(self, client, admin):
        r = client.post("/setup", data={"name": "Eve", "email": "eve@example.com",
                                        "password": PASSWORD, "confirm": PASSWORD})
        assert r.status_code == 302 and r.location.endswith("/login")
        assert User.query.filter_by(email="eve@example.com").first() is None


class TestLogin:
    def test_requires_login(self, client, admin):
        r = client.get("/bugs")
        assert r.status_code == 302 and "/login" in r.location

    def test_login_success_and_logout(self, client, admin):
        r = login(client, "ADMIN@example.com")  # email is case-insensitive
        assert r.status_code == 302
        assert client.get("/").status_code == 200
        assert db.session.get(User, admin.id).last_login_at is not None
        client.post("/logout")
        assert client.get("/").status_code == 302

    def test_wrong_password(self, client, admin):
        r = login(client, admin.email, "nope")
        assert r.status_code == 200 and b"incorrect" in r.data

    def test_inactive_and_passwordless_users_cannot_sign_in(self, client, admin):
        add_user("Off", "off@example.com", active=False)
        add_user("NoLogin", "nologin@example.com", password=None)
        for email in ("off@example.com", "nologin@example.com"):
            assert b"incorrect" in login(client, email).data

    def test_deactivated_user_is_signed_out(self, client, admin, tester):
        login(client, tester.email)
        tester.active = False
        db.session.commit()
        assert client.get("/").status_code == 302

    def test_next_redirect_only_to_local_paths(self, client, admin):
        r = client.post("/login?next=/bugs/new", data={"email": admin.email, "password": PASSWORD})
        assert r.location.endswith("/bugs/new")
        client.post("/logout")
        r = client.post("/login?next=https://evil.example/", data={"email": admin.email, "password": PASSWORD})
        assert "evil" not in r.location
        client.post("/logout")
        r = client.post("/login?next=//evil.example/", data={"email": admin.email, "password": PASSWORD})
        assert "evil" not in r.location


class TestAccount:
    def test_change_password(self, tester_client, tester):
        r = tester_client.post("/account", data={"action": "password", "current_password": PASSWORD,
                                                  "new_password": "new-password", "confirm_password": "new-password"})
        assert r.status_code == 302
        assert db.session.get(User, tester.id).check_password("new-password")

    def test_change_password_needs_current(self, tester_client, tester):
        tester_client.post("/account", data={"action": "password", "current_password": "wrong",
                                             "new_password": "new-password", "confirm_password": "new-password"})
        assert db.session.get(User, tester.id).check_password(PASSWORD)

    def test_rename_self(self, tester_client, tester):
        tester_client.post("/account", data={"action": "profile", "name": "Thomas"})
        assert db.session.get(User, tester.id).name == "Thomas"


class TestSecurity:
    def test_csrf_enforced(self, make_app):
        app = make_app(WTF_CSRF_ENABLED=True)
        with app.app_context():
            add_user("Ann", "admin@example.com", role="admin")
        client = app.test_client()
        r = client.post("/login", data={"email": "admin@example.com", "password": PASSWORD})
        assert r.status_code == 400

    def test_security_headers(self, admin_client):
        r = admin_client.get("/")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"

    def test_secret_key_generated_and_persisted(self, tmp_path, monkeypatch):
        from bugtracker.config import build_config
        monkeypatch.delenv("BUGTRACKER_SECRET_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        first = build_config({"DATA_DIR": str(tmp_path)})["SECRET_KEY"]
        second = build_config({"DATA_DIR": str(tmp_path)})["SECRET_KEY"]
        assert first == second and len(first) == 64
        assert first != "change-me-in-production"


def test_footer_credits_author_and_links_source(admin_client, app):
    html = admin_client.get("/").data
    assert b"PrdAmrican" in html and b"GNU AGPL v3" in html
    assert b'href="https://github.com/PrdAmrican/BugTracker2"' in html
    app.config["SOURCE_URL"] = "https://example.com/my-fork"
    app.jinja_env.globals["SOURCE_URL"] = app.config["SOURCE_URL"]
    assert b"https://example.com/my-fork" in admin_client.get("/").data


class TestAbout:
    def test_public_with_license_and_source(self, client, admin):
        r = client.get("/about")
        assert r.status_code == 200
        for text in (b"PrdAmrican", b"GNU Affero General Public License", b"2.0.0",
                     b"github.com/PrdAmrican/BugTracker2", b"Flask"):
            assert text in r.data
        assert b"admins only" not in r.data

    def test_reachable_before_setup(self, client):
        assert client.get("/about").status_code == 200

    def test_license_text(self, client, admin):
        r = client.get("/about/license")
        assert r.mimetype == "text/plain" and b"GNU AFFERO GENERAL PUBLIC LICENSE" in r.data

    def test_system_info_for_admins_only(self, admin_client):
        r = admin_client.get("/about")
        assert b"admins only" in r.data and b"Schema version" in r.data

    def test_hidden_from_testers(self, tester_client):
        assert b"Schema version" not in tester_client.get("/about").data

    def test_in_nav(self, tester_client):
        assert b'href="/about"' in tester_client.get("/").data
