# Bug Tracker – Deployment Guide

## Part 1: Setting up a production server

### Prerequisites

- Python 3.10+
- A Windows or Linux machine reachable by your testers

### Step 1: Install

```bash
cd BugTracker2
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux
pip install -r requirements.txt
pip install waitress           # production server (Windows & Linux)
```

### Step 2: Configure (optional)

v2 needs no code edits. The session secret key is generated on first start and saved to `.secret_key` in the data folder — keep that file with your data. To manage it yourself, set `BUGTRACKER_SECRET_KEY` instead:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Other useful settings (all environment variables — see the README for the full list):

- `BUGTRACKER_DATA_DIR` — keep `bugs.db`, `uploads/` and `backups/` outside the code folder, e.g. `/var/lib/bugtracker` or `C:\BugTrackerData`. Makes code upgrades a simple file swap.
- `BUGTRACKER_SECURE_COOKIES=1` — when the site is served over HTTPS.
- `BUGTRACKER_MAX_UPLOAD_MB` — upload limit (default 25).

### Step 3: Run with a production server

Don't use `python app.py` in production — it's Flask's development server.

**Waitress (Windows or Linux)**

```bash
waitress-serve --host=0.0.0.0 --port=5000 app:app
```

**Gunicorn (Linux)**

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Open the site and create the admin account on the first visit (or run `flask --app bugtracker create-admin`).

### Step 4: Run as a background service

**Windows — NSSM**

```powershell
nssm install BugTracker "C:\apps\BugTracker2\venv\Scripts\waitress-serve.exe" "--host=0.0.0.0 --port=5000 app:app"
nssm set BugTracker AppDirectory "C:\apps\BugTracker2"
nssm set BugTracker AppEnvironmentExtra BUGTRACKER_DATA_DIR=C:\BugTrackerData
nssm start BugTracker
```

**Linux — systemd** (`/etc/systemd/system/bugtracker.service`)

```ini
[Unit]
Description=Bug Tracker
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/BugTracker2
Environment=BUGTRACKER_DATA_DIR=/var/lib/bugtracker
Environment=BUGTRACKER_SECURE_COOKIES=1
ExecStart=/opt/BugTracker2/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/bugtracker && sudo chown www-data /var/lib/bugtracker
sudo systemctl daemon-reload
sudo systemctl enable --now bugtracker
```

### Step 5: (Optional) HTTPS with Nginx

```nginx
server {
    listen 443 ssl;
    server_name bugs.example.com;
    # ssl_certificate / ssl_certificate_key …

    client_max_body_size 25M;

    location /backup/import {
        client_max_body_size 1024M;   # full backups include attachments
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Step 6: Scheduled backups

```bash
# Linux crontab: nightly full backup at 2:15
15 2 * * * cd /opt/BugTracker2 && BUGTRACKER_DATA_DIR=/var/lib/bugtracker venv/bin/flask --app bugtracker backup /backups/bugtracker_$(date +\%F).zip
```

On Windows, create a Task Scheduler job that runs `venv\Scripts\flask.exe --app bugtracker backup D:\Backups\bugtracker.zip` in the app folder.

---

## Part 2: Upgrading from v1

1. Stop the service and copy `bugs.db` and `uploads/` somewhere safe.
2. Get the v2 code from https://github.com/PrdAmrican/BugTracker2 and copy it over the old files (`app.py`, `bugtracker/`, `requirements.txt`, the start/stop scripts; the old `models.py`, `templates/` and `static/` folders can be deleted). Or put it in a new folder and copy `bugs.db` and `uploads/` across.
3. `pip install -r requirements.txt`
4. Start the service. The database is upgraded in place on first start.
5. Open the site, create the admin using your own tester email, then give passwords to the testers who should sign in.

If you want the data outside the code folder, move `bugs.db` and `uploads/` into the new data folder and set `BUGTRACKER_DATA_DIR` before starting.

---

## Part 3: Moving to another server

### Method 1: Full backup ZIP (recommended)

1. Old server: **Backup → Full backup (ZIP)** (or `flask --app bugtracker backup bugtracker.zip`).
2. New server: install as in Part 1 and start the app once.
3. Create a temporary admin on the setup page, then **Backup → Restore** with the ZIP. All bugs, comments, history, people (with their passwords) and attachment files come across.

For very large backups, use the command line instead of the browser: `flask --app bugtracker restore bugtracker.zip`.

### Method 2: Copy the data folder

Stop the app and copy `bugs.db`, `uploads/` and `.secret_key` from the data folder to the same place on the new server. Install the code, start the app.

### What to copy

| Item | Needed? | Notes |
|------|---------|-------|
| `app.py`, `bugtracker/`, `requirements.txt` | Yes | The application |
| `bugs.db` | Yes* | *or restore a backup instead |
| `uploads/` | Yes* | *included in a full backup ZIP |
| `.secret_key` | Optional | Without it everyone just signs in again |
| `backups/` | Optional | Automatic pre-restore snapshots |
| `venv/`, `__pycache__/` | No | Recreate on the new server |

---

## Quick reference

| Task | Command |
|------|---------|
| Development server | `python app.py` |
| Production (Windows/Linux) | `waitress-serve --host=0.0.0.0 --port=5000 app:app` |
| Production (Linux) | `gunicorn -w 4 -b 0.0.0.0:5000 app:app` |
| Create / promote admin | `flask --app bugtracker create-admin` |
| Reset a password | `flask --app bugtracker set-password` |
| Full backup | `flask --app bugtracker backup file.zip` |
| Restore | `flask --app bugtracker restore file.zip` |
| Start over | Stop the app, delete `bugs.db` and `uploads/`, start again |
