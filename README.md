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
- A local MySQL server (MySQL 8+ recommended). It must be installed,
  running, and have an empty database created for this project.

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
   to recreate: copy `backend/.env.example` to `backend/.env`) and fill in
   your local MySQL credentials. `backend/.env` is git-ignored — never
   commit it.

4. Create the MySQL database and user, then match them in `backend/.env`:

   ```sql
   CREATE DATABASE mycelium_db CHARACTER SET utf8mb4;
   ```

5. Run Django checks:

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py check
   ```

   Note: with no MySQL server running, the stock `check` command fails at
   the database-connection stage (`Can't connect to server`). That is an
   environment limitation, not a code failure — the full check suite passes
   once MySQL is reachable.

6. Apply migrations (requires a running MySQL server):

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py migrate
   ```

7. Start the development server:

   ```powershell
   backend\venv\Scripts\python.exe backend\manage.py runserver
   ```

8. Health check: `GET http://127.0.0.1:8000/api/health/` should return
   `{"status": "ok", "service": "mycelium-backend", "version": "0.1.0"}`.
   It needs no database and exposes no configuration or secrets.

Run the backend tests with:

```powershell
backend\venv\Scripts\python.exe backend\manage.py test
```

## Backend implementation status

Done (foundation):

- Django project `config` + app `family`, configured for MySQL via
  environment variables, DRF, CORS limited to `FRONTEND_ORIGIN`, media
  uploads directory, and optional `GROQ_API_KEY` (app starts without it).
- `GET /api/health/` liveness endpoint + tests.

Not yet implemented (later steps):

- `FamilyMember` / relationships / `FamilyEvent` / `FamilyStory` models.
- `/api/members/`, `/api/places/`, `/api/events/`, `/api/stories/`,
  `/api/storyhelper/` endpoints. The frontend still uses sample data and
  placeholder form messages until these land.

## Known setup limitations

- MySQL is the intended database and is **not** installed/configured on
  every machine yet; install it locally and create `mycelium_db` first.
- `mysqlclient` needs a prebuilt wheel on Windows; `requirements.txt` pins
  a version that provides one for Python 3.14.
- An unrelated `install.cmd` (Claude Code bootstrap script) sits untracked
  in the repo root; it is not part of this project.
- `test-key.js` reads `GROQ_API_KEY` from the environment and contains no
  hardcoded secret.
