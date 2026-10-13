# Mycelium — Family History Tracker

Build your family tree, save stories, and explore where your family came from
on a 3D globe.

- Frontend: `index.html`, `style.css`, `script.js` (vanilla JS + Globe.gl).
  Open `index.html` directly or serve the folder statically.
- Backend: Django + Django REST Framework API in `backend/`
  (in progress — see below).

## Backend setup (Django)

Prerequisites:

- Python 3.14 (the existing `backend/venv` was created with Python 3.14.6).
- No database server needed: the project uses SQLite by default
  (`backend/db.sqlite3`, created automatically, git-ignored).

1. Create and activate the virtual environment (already present as
   `backend/venv`; to recreate: `python -m venv backend\venv`):

   ```powershell
   backend\venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation scripts, do **not** weaken the global
   execution policy. Instead call the venv Python directly, e.g.
   `backend\venv\Scripts\python.exe -m pip ...`.

2. Install dependencies:

   ```powershell
   backend\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
   ```

3. Create the local environment file (already present as `backend/.env`;
   to recreate: copy `backend/.env.example` to `backend/.env`).
   `backend/.env` is git-ignored — never commit it. No database
   credentials are needed for the default SQLite setup.

4. Run Django checks:

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py check
   ```

5. Apply migrations (creates `backend/db.sqlite3` on first run):

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py migrate
   ```

6. Start the development server:

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py runserver
   ```

7. Health check: `GET http://127.0.0.1:8000/api/health/` should return
   `{"status": "ok", "service": "mycelium-backend", "version": "0.1.0"}`.
   It needs no database and exposes no configuration or secrets.

Run the backend tests (39 tests, real project settings) with:

```powershell
backend\venv\Scripts\python.exe backend\manage.py test
```

## Optional: MySQL instead of SQLite

SQLite is the default and is all local development needs. If you later
want MySQL (e.g. for deployment parity):

1. Install and start a MySQL 8+ server and create the database:

   ```sql
   CREATE DATABASE mycelium_db CHARACTER SET utf8mb4;
   ```

2. In `backend/.env`, set `DB_ENGINE=mysql` and fill in `DB_NAME`,
   `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`.
3. `mysqlclient` is already pinned in `requirements.txt` (Windows wheel
   for Python 3.14 included).
4. Re-run `check`, `migrate`, and `test` as above.

The MySQL path is implemented in `backend/config/settings.py` but has
not been integration-tested on this machine (no MySQL server here yet).

## Backend implementation status

Done (foundation + family API):

- Django project `config` + app `family`, configured for MySQL via
  environment variables, DRF, CORS limited to `FRONTEND_ORIGIN`, media
  uploads directory, and optional `GROQ_API_KEY` (app starts without it).
- `GET /api/health/` liveness endpoint + tests.
- Models: `FamilyMember` (canonical `parents`/`partners` links, derived
  siblings, photo upload, bio), `FamilyEvent` (timeline), `FamilyStory`
  (archive). Migration `family/migrations/0001_initial.py` included.
- Endpoints (trailing slash optional, JSON and multipart form payloads):
  `GET/POST /api/members/`, `GET/PUT/PATCH/DELETE /api/members/<id>/`,
  same shapes for `/api/events/` and `/api/stories/`,
  `GET /api/places/` (birth/lived places; `lat`/`lng` null until
  geocoding lands), `POST /api/storyhelper/` (Groq-powered; honest 503
  when no key is configured, key never leaves the backend).
- Relationship handling: `Parent`/`Child`/`Spouse / partner`/`Sibling`/
  `Grandparent` hints derive canonical links idempotently (no duplicates,
  no self-links); ambiguous labels keep the entry hint only.
- 39 backend tests (models, serializers, relationships, API, story
  helper), run against the project's actual SQLite settings. MySQL
  remains available as an opt-in (`DB_ENGINE=mysql`) but has not had a
  real integration run on this machine.

Not yet implemented (later steps):

- Frontend integration (the UI still uses sample data and placeholder
  form messages; that wiring is a separately verified step).
- Geocoding for globe coordinates.
- Photo display from `photoUrl` in the tree.

## Known setup limitations

- The opt-in MySQL path has not been integration-tested here (no MySQL
  server on this machine); SQLite is tested and is the default.
- An unrelated `install.cmd` (Claude Code bootstrap script) sits untracked
  in the repo root; it is not part of this project.
- `test-key.js` reads `GROQ_API_KEY` from the environment and contains no
  hardcoded secret.
