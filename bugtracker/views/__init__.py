# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
def register_blueprints(app):
    from . import about, auth, backup, bugs, dashboard, people, settings

    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(bugs.bp)
    app.register_blueprint(people.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(backup.bp)
    app.register_blueprint(about.bp)
