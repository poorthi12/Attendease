# AttendEase

AttendEase is a student attendance management system for administrators, teachers, and students. Administrators manage accounts, departments, subjects, teaching assignments, and enrollment. Teachers record a complete class roster for an assigned subject. Students see their own subjects, attendance totals, records, and absent dates.

The interface uses a responsive oil-black and white visual system, with shared Jinja templates, HTML forms, and small vanilla JavaScript modules.

## Features

- Separate student, teacher, and administrator sign-in with role and object-level authorization.
- Argon2id password hashes, signed HttpOnly session cookies, CSRF tokens, MongoDB-backed sign-in throttling, and request-size limits.
- Student dashboards and profiles, subject summaries, date and status filters, attendance history, and absent dates.
- Teacher subject rosters, attendance marking with bulk present/absent actions, class history, and Chart.js analytics.
- Administrator tools for student and teacher accounts, subjects, departments, teacher assignments, and student enrollment.
- Attendance sessions and records protected by unique indexes. Finalized sessions cannot be silently overwritten.
- Reusable MongoDB client and connection pool. Synchronous PyMongo operations run in FastAPI’s worker pool; the attendance form explicitly offloads its database work.
- Automated tests use `mongomock` and do not connect to the configured Atlas database.

## Technology

- Python 3.12 or newer (the current environment only had Python 3.13.7 installed; local verification ran on 3.13.7)
- FastAPI, Jinja2, Pydantic, and Pydantic Settings
- MongoDB Atlas through synchronous PyMongo
- Argon2 through `argon2-cffi`
- Vanilla JavaScript and Chart.js
- `uv` for dependency management; `pytest` and FastAPI TestClient for tests

## Architecture

`app/main.py` builds the FastAPI application, middleware, error pages, and startup lifecycle. Routers in `app/routers/` handle role-specific HTTP routes. Business calculations and attendance finalization live in `app/services/`; MongoDB query helpers live in `app/repositories/`; Pydantic request validation lives in `app/schemas/`; document builders live in `app/models/`. Jinja pages are in `templates/`, with shared CSS and JavaScript in `static/`.

Most routes are synchronous `def` endpoints, so FastAPI runs blocking PyMongo calls in its managed worker pool. The application reuses one MongoClient with a 50-connection maximum pool per process. It does not create request-specific threads or rely on process memory for persistent state. On serverless deployments, each warm function instance can have its own pool; size Atlas limits for the expected instance count.

### Collections and indexes

The application uses `users`, `students`, `teachers`, `subjects`, `subject_assignments`, `enrollments`, `attendance_sessions`, `attendance_records`, `audit_logs`, `auth_attempts`, and `departments`.

Startup initializes indexes once per application process. `scripts/create_indexes.py` can also initialize them explicitly. Indexes include unique normalized user email, student USN, subject code, profile-to-user references, teacher/subject assignment, student/subject enrollment, subject/date session, and session/student attendance record keys. Supporting indexes cover teacher, student, subject, and date queries. Sign-in throttle records use a TTL index.

Attendance finalization and multi-document administrator changes use a MongoDB transaction when supported. On a standalone MongoDB deployment, attendance creates a `finalizing` session, inserts all records and an audit event, then changes the session to `finalized`. If a fallback write fails, the application removes partial records and audit data before reporting failure. A later attendance submission cleans up an abandoned `finalizing` session older than 15 minutes. Unique subject/date and session/student indexes prevent duplicate submissions. This fallback is compensating cleanup, not database transaction atomicity. Atlas replica set deployments use the transaction path.

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A MongoDB Atlas database and database user

The repository’s `.python-version` requests Python 3.12. In this development environment, 3.12 was not installed, so validation used the available Python 3.13 interpreter explicitly.

## Install and configure

Run these commands in PowerShell from the project directory:

```powershell
uv python install 3.12
uv sync --all-extras

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}
```

Edit `.env` locally. Do not replace an existing `.env`. The settings layer accepts the existing `MONGODB_URI` name and the documented `MONGODB_URL` name. Set these values:

| Variable | Purpose |
| --- | --- |
| `MONGODB_URL` | MongoDB connection string. Existing `MONGODB_URI` is also accepted. |
| `MONGODB_DATABASE` | Database name; defaults to `attendease`. |
| `SESSION_SECRET` | Random signing secret of at least 32 characters in production. |
| `APP_ENV` | `development`, `test`, or `production`. |
| `COOKIE_SECURE` | Set `true` when serving over HTTPS. Production forces secure cookies. |

Generate a local secret without putting it in source control:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the output into your local `.env` as `SESSION_SECRET=...`. `.env.example` contains placeholders only.

### MongoDB Atlas

Create a database user with access only to the AttendEase database. Use TLS in the connection string and a strong password. Configure Atlas network access for the development host and the production runtime. Prefer a private connection or static egress allow-list when available; serverless outbound addresses can vary. Avoid opening the database to the entire internet unless that is an explicit, reviewed infrastructure decision. The app initializes indexes during startup; the command below can initialize them separately:

```powershell
uv run python scripts/create_indexes.py
```

## Bootstrap the first administrator

There is no public admin registration route. Create the first administrator from a trusted terminal. The script prompts for a password without echoing it; `ADMIN_EMAIL`, `ADMIN_NAME`, and `ADMIN_PASSWORD` may be supplied through the process environment instead.

```powershell
uv run python -m scripts.bootstrap_admin
```

The script refuses to create a second administrator while an active admin exists. Keep admin credentials in a secure credential manager and share temporary passwords through a separate secure channel.

## Run locally

```powershell
uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. Sign-in pages are `/login/student`, `/login/teacher`, and `/login/admin`. The health endpoint at `/health` checks whether the web process is responsive; it does not ping MongoDB.

## Tests and checks

```powershell
uv run pytest
uv run python -m compileall app api scripts tests
```

Tests inject an isolated in-memory MongoDB-compatible database. They cover password hashing, configuration aliases, role checks, student data isolation, teacher subject restrictions, attendance calculations, duplicate prevention, admin enrollment validation, and page rendering. They do not access the Atlas connection configured in `.env`.

## Security and data behavior

- Users are looked up by normalized exact email or student USN; user input is not interpolated into MongoDB selectors or regular expressions.
- A role is reloaded from MongoDB on protected requests. Student pages derive the student profile from the session user ID; teachers must have an active assignment for subject routes.
- State-changing forms require a per-session CSRF token. Logout is POST-only.
- Sessions are signed cookies with HttpOnly and SameSite=Lax. Production requires a strong `SESSION_SECRET` and uses Secure cookies. A development process without a configured secret uses a fresh random secret, so sessions expire when the process restarts.
- Eight failed sign-in attempts within the rolling 15-minute window trigger throttling. Counters are stored in MongoDB and keyed by a hash of the identifier and client address.
- The app caps form request bodies at 1 MiB and adds basic browser security headers.
- Deactivating profiles, subjects, assignments, or enrollments preserves historical attendance records. Deactivated users cannot sign in.
- Finalized attendance is immutable in the current UI. There is no attendance-correction workflow; corrections require a future, explicitly audited feature.
- No password reset or email delivery workflow is included.

## Vercel deployment

`api/index.py` imports the same `app` object used locally. `[tool.vercel].entrypoint` selects that FastAPI application, while `vercel.json` retains `static/` and `templates/` in the function bundle. The app serves static files through its `StaticFiles` mount. Vercel supports FastAPI entrypoint configuration and applies its function limits; review the current [Vercel FastAPI guide](https://vercel.com/docs/frameworks/backend/fastapi) and [Python runtime documentation](https://vercel.com/docs/functions/runtimes/python) when setting up a project. Vercel’s CDN promotion for mounted static files is disabled by top-level middleware unless explicitly enabled, so this deployment keeps the security-header middleware in the request path.

1. Import the repository into a Vercel project (or use the Vercel CLI from the repository root).
2. Add `MONGODB_URL`, `MONGODB_DATABASE`, `SESSION_SECRET`, and `APP_ENV=production` in the project’s Production environment. Set `COOKIE_SECURE=true` if desired; production forces it regardless.
3. Configure Atlas access for the Vercel runtime and use a least-privilege database user.
4. Deploy from the Vercel dashboard or CLI after credentials and environment variables are ready.

The app does not use filesystem persistence, global in-memory sessions, or permanent background threads. Each serverless instance may have an independent MongoDB pool and ephemeral process state. Vercel execution duration, concurrency, bundle, and request limits apply. A deployment was not performed from this workspace.

## Troubleshooting

- **MongoDB unavailable:** Check `MONGODB_URL`/`MONGODB_URI`, Atlas database-user permissions, DNS/network access, and Atlas allow-list settings. The landing page remains available, while database-backed sign-in and pages return a friendly unavailable response.
- **Production import fails:** Set `SESSION_SECRET` to at least 32 characters and provide `MONGODB_URL`.
- **Indexes fail at startup:** Check duplicate data before adding unique indexes. Resolve duplicate email, USN, subject code, assignments, enrollments, or attendance records, then run `uv run python scripts/create_indexes.py`.
- **Admin bootstrap stops:** Verify MongoDB connectivity and ensure there is not already an active administrator.
- **Session invalid after restart:** Development uses an ephemeral signing secret when none is configured. Set a stable local `SESSION_SECRET` to retain sessions across restarts.
- **Attendance date already exists:** A finalized subject/date is unique. The UI does not overwrite a previous class session.

## Repository layout

```text
api/index.py                 Vercel entry point
app/config.py                Environment settings
app/database.py              MongoDB pool and indexes
app/models/                  MongoDB document builders
app/repositories/            Domain query helpers
app/routers/                 Student, teacher, admin, auth, attendance routes
app/schemas/                 Pydantic validation
app/security/                Passwords, sessions, roles, request controls
app/services/                Attendance integrity and calculations
templates/                   Shared and role-specific Jinja pages
static/css/                  Responsive monochrome styles
static/js/                   Navigation, attendance, and chart behavior
scripts/                     Index and administrator bootstrap tools
tests/                       Isolated automated tests
```
#   A t t e n d e a s e  
 