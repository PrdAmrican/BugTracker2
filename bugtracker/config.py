# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Configuration, read from environment variables with sensible defaults.

Every setting can be overridden with an environment variable, so the same
code runs unchanged in development, tests and production.

    BUGTRACKER_DATA_DIR     where bugs.db, uploads/ and backups/ live
                            (default: the project folder, same as v1)
    DATABASE_URL            SQLAlchemy URL (default: sqlite in DATA_DIR)
    BUGTRACKER_UPLOAD_DIR   attachment folder (default: DATA_DIR/uploads)
    BUGTRACKER_SECRET_KEY   session signing key (default: generated once and
                            saved to DATA_DIR/.secret_key)
    BUGTRACKER_MAX_UPLOAD_MB  per-request upload limit (default: 25)
    BUGTRACKER_SECURE_COOKIES set to 1 when served over HTTPS
    BUGTRACKER_SOURCE_URL   where users can get this version's source code
                            (shown in the footer, as the AGPL requires;
                            change it if you run a modified copy)
"""

import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _load_secret_key(data_dir: Path) -> str:
    env_key = os.environ.get("BUGTRACKER_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = data_dir / ".secret_key"
    if key_file.exists() and key_file.read_text().strip():
        return key_file.read_text().strip()
    # Several workers may start at once: create the file atomically so they
    # all end up with the same key.
    key = secrets.token_hex(32)
    tmp = data_dir / f".secret_key.{os.getpid()}.tmp"
    tmp.write_text(key)
    try:
        tmp.chmod(0o600)
    except OSError:  # Windows / restricted filesystems
        pass
    try:
        os.link(tmp, key_file)  # fails if another worker won the race
    except FileExistsError:
        pass
    except OSError:  # filesystem without hard links
        if not key_file.exists():
            os.replace(tmp, key_file)
    finally:
        if tmp.exists():
            tmp.unlink()
    return key_file.read_text().strip()


def build_config(overrides: dict | None = None) -> dict:
    overrides = dict(overrides or {})
    data_dir = Path(
        overrides.pop("DATA_DIR", None)
        or os.environ.get("BUGTRACKER_DATA_DIR")
        or PROJECT_ROOT
    ).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    upload_dir = Path(
        overrides.get("UPLOAD_DIR")
        or os.environ.get("BUGTRACKER_UPLOAD_DIR")
        or data_dir / "uploads"
    ).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    backup_dir = data_dir / "backups"

    max_mb = int(os.environ.get("BUGTRACKER_MAX_UPLOAD_MB", "25"))

    config = {
        "DATA_DIR": str(data_dir),
        "UPLOAD_DIR": str(upload_dir),
        "BACKUP_DIR": str(backup_dir),
        "SQLALCHEMY_DATABASE_URI": os.environ.get("DATABASE_URL")
        or "sqlite:///" + str(data_dir / "bugs.db"),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "MAX_CONTENT_LENGTH": max_mb * 1024 * 1024,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": _truthy(os.environ.get("BUGTRACKER_SECURE_COOKIES", "0")),
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SAMESITE": "Lax",
        "REMEMBER_COOKIE_SECURE": _truthy(os.environ.get("BUGTRACKER_SECURE_COOKIES", "0")),
        "WTF_CSRF_TIME_LIMIT": None,  # token lives as long as the session
        "BUGS_PER_PAGE": 50,
        "SOURCE_URL": os.environ.get("BUGTRACKER_SOURCE_URL")
        or "https://github.com/PrdAmrican/BugTracker2",
    }
    if "SECRET_KEY" not in overrides:
        config["SECRET_KEY"] = _load_secret_key(data_dir)
    config.update(overrides)
    return config
