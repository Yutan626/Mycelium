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

Run the backend tests (87 tests, real project settings) with:

```powershell
backend\venv\Scripts\python.exe backend\manage.py test
```

## Production: PostgreSQL on Render (not local dev)

SQLite is the default and is all local development needs. For production:

1. Create a PostgreSQL database on Render and copy its credentials.
2. In the Render dashboard (never in Git), set `DB_ENGINE=postgresql`
   plus `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
   `POSTGRES_HOST`, `POSTGRES_PORT`, along with `DJANGO_SECRET_KEY`,
   `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS` (your domain),
   `FRONTEND_ORIGIN` (your frontend URL), and `DJANGO_SECURE=1`.
3. Deploy, then run migrations once (`python manage.py migrate`).
4. Media: set `CLOUDINARY_URL` so uploads persist; email: set the
   `EMAIL_*` values for Gmail SMTP delivery.

PostgreSQL compatibility has only been statically checked here
(`sqlmigrate` rendering); no live PostgreSQL server was available, so a
live integration test is still required before relying on it.

## Render deployment checklist

1. In Render, choose **New > Blueprint**, connect this repository, and
   deploy the root `render.yaml`. It creates a free backend Web Service,
   generates `DJANGO_SECRET_KEY`, and sets the allowed host automatically.
   The frontend and API share the backend origin. The start command
   applies database migrations before launching the backend.
2. The free Web Service uses SQLite on Render's ephemeral filesystem.
   The database and uploaded local photos can disappear after a restart,
   spin-down, or redeploy. Use this only as a temporary demo; do not store
   family data you need to keep.
3. For persistent photo uploads, add `CLOUDINARY_URL` in the Render
   dashboard. Add `GROQ_API_KEY` there to enable the AI story helper;
   configure `EMAIL_*` only if real email delivery is needed.
4. Smoke test after deploy: HTTPS, login/logout, member create, photo
   download, health endpoint.

### Groq API key (AI story helper)

1. Create a free account at https://console.groq.com, open API Keys,
   and create a key. It stays server-side: set `GROQ_API_KEY` in the
   Render dashboard (locally: `backend/.env`, never committed).
2. The default model is `openai/gpt-oss-20b` (a currently supported Groq
   model; override with `GROQ_MODEL` if Groq retires it). The helper is
   rate-limited to 20 requests/hour per account.
3. Without a key the endpoint honestly answers 503 and the UI explains
   the helper is unconfigured — everything else keeps working.

### Gmail App Passwords (for password reset delivery)

1. Enable 2-Step Verification on the Gmail account, then create an App
   Password (Google Account → Security → App passwords).
2. Set `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`,
   `EMAIL_HOST=smtp.gmail.com`, `EMAIL_PORT=587`,
   `EMAIL_HOST_USER=<address>`,
   `EMAIL_HOST_PASSWORD=<16-char app password>`,
   `DEFAULT_FROM_EMAIL=Mycelium <<address>>` in the Render dashboard.
3. Real delivery is unverified here; send a reset email after deploy and
   confirm receipt before announcing the feature.

### Existing local media on deploy

`backend/media/` is git-ignored and stays on this machine — it is not
deployed. After launch, either re-upload photos (they land in Cloudinary
once `CLOUDINARY_URL` is set) or copy the files into Cloudinary manually.
Do not make the local media directory public.

## Backend implementation status

Done (foundation + family API):

- Django project `config` + app `family`, environment-variable
  configuration, DRF, CORS limited to `FRONTEND_ORIGIN`, media uploads
  directory, and optional `GROQ_API_KEY` (app starts without it).
- `GET /api/health/` liveness endpoint + tests.
- Models: `FamilyMember` (canonical `parents`/`partners` links, derived
  siblings, photo upload, bio), `FamilyEvent` (timeline), `FamilyStory`
  (archive). Migration `family/migrations/0001_initial.py` included.
- Endpoints (trailing slash optional, JSON and multipart form payloads):
  `GET/POST /api/members/`, `GET/PUT/PATCH/DELETE /api/members/<id>/`,
  same shapes for `/api/events/` and `/api/stories/`,
  `GET /api/places/` (birth/lived places resolved through a local
  gazetteer of ~35 cities and ~30 countries; unknown places stay `null`
  and are listed, never plotted), `POST /api/storyhelper/` (Groq-powered;
  honest 503 when no key is configured, key never leaves the backend).
- Relationship handling: `Parent`/`Child`/`Spouse / partner`/`Sibling`/
  `Grandparent` hints derive canonical links idempotently (no duplicates,
  no self-links); ambiguous labels keep the entry hint only.
- 87 backend tests (models, serializers, relationships, API, story
  helper, authentication incl. login throttling and password reset,
  ownership isolation, relative connections incl. grants and shared
  viewing, photo privacy incl. missing files and failed replacement,
  seed commands), run against the project's actual SQLite settings.
  PostgreSQL is the production database
  (`DB_ENGINE=postgresql`) but has not had a live integration run here.

Done (accounts and private trees):

- Session-based registration/login/logout (`/api/auth/register`,
  `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`,
  `/api/auth/csrf/`); frontend serves login/register views from the
  existing design with CSRF protection and narrow CORS.
- Every member, event, and story belongs to one account (`owner`);
  all endpoints are owner-scoped on the backend (cross-account reads
  404, anonymous access 403). A client-supplied owner is always ignored.
- Each account has one `FamilyTree` (auto-created) with a designatable
  center person (`GET/POST /api/center/`; "Make this the center of my
  tree" button in member profiles).
- Member photos download only through ownership-checked
  `GET /api/photos/<id>/`; no public media URLs are served.
- Minimal relative-connection threads (`GET/POST /api/connections/`,
  approve/reject/revoke) between exact usernames: no directory, no
  auto-merge. The recipient may grant read-only tree viewing
  (`grants_view`); the requester can then open the shared tree from the
  Connections view (`GET /api/shared/<username>/members|events|stories|places/`,
  viewer-checked photo downloads). Grants never propagate, revoking ends
  access, and records always stay owned by their own accounts.
- Password reset via `/accounts/password_reset/` (Django views + email;
  console backend locally, Gmail SMTP in production).
- `seed_sample_family --username <name>` seeds a demo family owned by
  that existing account (idempotent, per user). Records created before
  ownership are ownerless and hidden; the owner can explicitly run
  `assign_legacy_records --username <name>` once to claim them
  (documented; never automatic).

Frontend integration (all live, verified against the API):

- Member/event/story creation forms, member/event/story edit and delete
  (with confirmation), family tree + profiles with photo display,
  relationship selectors, timeline (dated/undated), story archive,
  globe places, AI story helper, and login/register/logout flows.
- Login attempts are throttled (5 failures per IP per 5 minutes, 429);
  for multi-process production use django-axes/Redis instead.
- Email uses the console backend locally; set `EMAIL_HOST` etc. and a
  real `DJANGO_EMAIL_BACKEND` before any password-reset feature.
- Browser end-to-end testing has not been performed here; see the manual
  checklist in the project handoff before demoing.

## Known setup limitations

- PostgreSQL has only been statically checked (migration SQL
  rendering); SQLite is tested and is the local default.
- Authentication is session-based with cache-backed login throttling
  (single-process safe; use django-axes/Redis for multi-process
  production). There is no per-user API rate limiting yet.
- Password reset is implemented (`/accounts/password_reset/`); real
  delivery needs Gmail SMTP credentials (App Password, 2-Step Verification
  on) — unverified here, no key configured.
- The API has no per-user rate limits; media is served only through the
  ownership-checked photo endpoint in development — production must not
  serve `MEDIA_ROOT` publicly.
- Family data is private per account. Limited read-only sharing exists
  only through explicit per-connection viewing grants (see above); there
  are no per-record permissions beyond that.
- An unrelated `install.cmd` (Claude Code bootstrap script) sits untracked
  in the repo root; it is not part of this project.
- `test-key.js` reads `GROQ_API_KEY` from the environment and contains no
  hardcoded secret.
