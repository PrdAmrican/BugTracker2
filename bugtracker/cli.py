# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Command-line helpers:  flask --app bugtracker <command>"""

import os

import click
from sqlalchemy import func

from .extensions import db
from .models import User
from .services import MIN_PASSWORD_LENGTH


def _password_option():
    return click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
                        help=f"At least {MIN_PASSWORD_LENGTH} characters.")


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @_password_option()
    def create_admin(email, name, password):
        """Create an admin, or promote an existing tester with this email."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise click.ClickException(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if user is None:
            user = User(name=name, email=email)
            db.session.add(user)
        user.role, user.active = "admin", True
        user.set_password(password)
        db.session.commit()
        click.echo(f"{email} is now an admin.")

    @app.cli.command("set-password")
    @click.option("--email", prompt=True)
    @_password_option()
    def set_password(email, password):
        """Reset someone's password (e.g. a locked-out admin)."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise click.ClickException(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        user = User.query.filter(func.lower(User.email) == email.lower()).first()
        if user is None:
            raise click.ClickException(f"No tester with email {email}.")
        user.set_password(password)
        user.active = True
        db.session.commit()
        click.echo(f"Password updated for {email}.")

    @app.cli.command("backup")
    @click.argument("path", type=click.Path(dir_okay=False, writable=True))
    def backup_command(path):
        """Write a full backup ZIP (data + attachments) to PATH."""
        from .backup import write_full_backup
        with open(path, "wb") as fh:
            missing = write_full_backup(fh)
        click.echo(f"Wrote {path}" + (f" ({missing} attachment files were missing)" if missing else ""))

    @app.cli.command("restore")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
    def restore_command(path, yes):
        """Replace ALL data with a JSON or full-backup ZIP file."""
        from .backup import ImportErrorList, import_data, read_backup_file, save_snapshot
        if not yes:
            click.confirm("This replaces all current data. Continue?", abort=True)
        with open(path, "rb") as fh:
            try:
                data, files = read_backup_file(fh, os.path.basename(path))
                snapshot = save_snapshot("pre-import")
                warnings, _ = import_data(data, files)
            except ImportErrorList as e:
                for err in e.errors:
                    click.echo(f"  - {err}", err=True)
                raise click.ClickException("Import failed — nothing was changed.")
        click.echo(f"Restored. Previous data saved to {snapshot}")
        for w in warnings:
            click.echo(f"  ! {w}")
        if not User.query.filter(User.role == "admin", User.password_hash.isnot(None)).first():
            click.echo("No admin can sign in yet: open the app to create one, "
                       "or run `flask --app bugtracker create-admin`.")
