# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 PrdAmrican <https://github.com/PrdAmrican>
"""Entry point.

    python app.py                         development server on :5000
    waitress-serve --port=5000 app:app    production (Windows or Linux)
    gunicorn -w 4 -b 0.0.0.0:5000 app:app production (Linux)
"""

import os

from bugtracker import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("BUGTRACKER_HOST", "127.0.0.1"),
        port=int(os.environ.get("BUGTRACKER_PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
