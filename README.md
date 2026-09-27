# Pentecost Attendance — Backend API

Backend REST API for a multi-branch church membership and attendance platform.

---

## Tech stack

| Component | Package | Version |
|---|---|---|
| Web framework | Django | 6.1.1 |
| REST framework | djangorestframework | 3.18.1 |
| Admin UI | django-jazzmin | 3.0.5 |
| API docs | drf-spectacular | 0.30.0 |
| Env var management | python-decouple | 3.8 |
| Image handling | Pillow | 12.3.0 |
| Database (dev) | SQLite | built-in |
| Database (prod) | PostgreSQL via psycopg | 3.3.5 |

---

## Prerequisites

- Python 3.12 (no version pin file in this repo; built and tested on 3.12)
- pip
- PostgreSQL is only needed for production — dev uses SQLite

---

## Setup (local development)

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd pentecost-attendance-backend
```

### 2. Create and activate a virtual environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements/dev.txt
```

`requirements/dev.txt` pulls in everything in `requirements/base.txt` — Django, DRF, Jazzmin, drf-spectacular, Pillow, and python-decouple. No additional packages are needed for local development.

### 4. Configure environment variables

```bash
cp .env.example .env
```

The table below lists every variable the settings files may read. In dev you can leave the file as-is after copying — the dev settings module uses SQLite and provides an insecure fallback secret key so the server starts without changes.

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Optional in dev, **required in prod** | Django secret key. In dev, an insecure fallback is used if this is unset. In prod, startup will fail if it is missing. Generate a value with: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` |
| `DJANGO_SETTINGS_MODULE` | Optional | Selects the settings module. Defaults to `config.settings.dev`. Set to `config.settings.prod` on the server. |
| `ALLOWED_HOSTS` | Prod only | Comma-separated hostnames, e.g. `api.yourdomain.com,www.yourdomain.com` |
| `DB_NAME` | Prod only | PostgreSQL database name (example default: `pentecost_attendance`) |
| `DB_USER` | Prod only | PostgreSQL user (example default: `postgres`) |
| `DB_PASSWORD` | Prod only | PostgreSQL password |
| `DB_HOST` | Prod only | PostgreSQL host (default: `localhost`) |
| `DB_PORT` | Prod only | PostgreSQL port (default: `5432`) |

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Create a superuser

This project uses phone number as the login identity — not a username or email. When you run `createsuperuser`, Django prompts for phone number and password only:

```
$ python manage.py createsuperuser
Phone number: 0201234567
Password:
Password (again):
Superuser created successfully.
```

There is no username or email prompt.

### 7. Start the dev server

```bash
python manage.py runserver
```

The server starts at `http://127.0.0.1:8000/`.

---

## Django admin

Visit `http://127.0.0.1:8000/admin/` and log in with the phone number and password you created in step 6.

The admin uses [Jazzmin](https://django-jazzmin.readthedocs.io/) (Flatly theme, dark mode available via the UI Builder toggle in the top bar). The following models are registered:

**Accounts**
- **Users** — auth identities; phone number, active/staff/superuser flags
- **Assemblies** — church branches; includes district, geofence coordinates, and presiding elder
- **Members** — church-domain profiles: full name, member ID, role, assembly, day-born group, profile photo
- **Elders** — profile extension of a Member for ordained elders; links to office type, contact details, and office hours
- **Elder Office Hours** — per-weekday availability windows for each elder
- **Day-Born Groups** — Akan day-of-birth groups per assembly (up to 7 per assembly)
- **OTP Verifications** — audit log of OTP attempts (login and phone-change flows)
- **Import Batches** — audit trail for CSV bulk member imports

**Attendance**
- **Attendance Sessions** — per-assembly service sessions; opened and closed by staff
- **Attendance Records** — individual check-in records (member × session)
- **Member Attendance Stats** — annual attendance score, sessions attended/possible, and streak per member

**Content**
- **Weekly Schedules** — recurring service schedule entries per assembly
- **Bible Study Weeks** — weekly Bible study content with publish/draft status
- **Events** — one-off events scoped to an assembly or district-wide
- **Notifications** — broadcast messages targeting all members, an assembly, a day-born group, or a single member
- **Notification Reads** — read receipts per member per notification

**Milestones**
- **Spiritual Milestones** — member milestone events (e.g. water baptism, Holy Spirit baptism), with a verifying elder

---

## API documentation

With the dev server running:

| Interface | URL |
|---|---|
| Swagger UI | `http://127.0.0.1:8000/api/docs/` |
| ReDoc | `http://127.0.0.1:8000/api/redoc/` |
| Raw OpenAPI schema | `http://127.0.0.1:8000/api/schema/` |

The raw schema at `/api/schema/` returns the OpenAPI 3 JSON/YAML document — use it to generate a typed API client via tools like `openapi-generator` or `openapi-typescript`.

All endpoints under `/api/v1/` require a token in the `Authorization` header:

```
Authorization: Token <your-token>
```

Obtain a token via the auth endpoint described in the next section.

---

## Authentication — temporary endpoint

> **Important:** The current token endpoint is a temporary stand-in and is **not the final authentication flow.**

`POST /api/v1/auth/token/`

Request body:
```json
{ "phone_number": "0201234567", "password": "your-password" }
```

Response:
```json
{ "token": "abc123...", "user_id": "uuid-here" }
```

This is a plain phone-number/password token endpoint used during development. The production login flow will use a one-time password (OTP) delivered via [Moolre](https://moolre.com/) (a Ghana-based SMS provider). **Do not build client-side logic that assumes this endpoint is permanent** — it will be replaced before launch.

---

## Project structure

```
pentecost-attendance-backend/
├── config/
│   ├── settings/
│   │   ├── base.py      # Shared settings: installed apps, DRF, Jazzmin, drf-spectacular
│   │   ├── dev.py       # Dev overrides: DEBUG=True, SQLite database
│   │   └── prod.py      # Prod overrides: PostgreSQL, HSTS, SSL redirect, strict secret key
│   └── urls.py          # Root URL config
├── core/                # Abstract BaseModel (UUID PK + created_at/updated_at); no API endpoints
├── accounts/            # Custom User (phone-based auth), Member profiles, Assemblies, Elders, Day-Born Groups, OTP, CSV imports
├── attendance/          # Attendance sessions, check-in records, per-member annual stats
├── content/             # Weekly schedules, Bible study weeks, events, push notifications
├── milestones/          # Spiritual milestone events per member
├── manage.py
└── requirements/
    ├── base.txt         # All shared dependencies
    ├── dev.txt          # Includes base.txt — no extras needed for local dev
    └── prod.txt         # Includes base.txt + psycopg[binary] for PostgreSQL
```

---

## Dev vs production settings

`manage.py` sets `DJANGO_SETTINGS_MODULE` to `config.settings.dev` by default via `os.environ.setdefault`. `config/settings/__init__.py` is empty — all selection is controlled by the env variable.

| | Dev (`config.settings.dev`) | Prod (`config.settings.prod`) |
|---|---|---|
| `DEBUG` | `True` | `False` |
| Database | SQLite (`db.sqlite3`, gitignored) | PostgreSQL (from `DB_*` env vars) |
| `SECRET_KEY` | Insecure fallback if unset | **Raises** `UndefinedValueError` if missing |
| `ALLOWED_HOSTS` | `localhost`, `127.0.0.1`, `0.0.0.0` | From `ALLOWED_HOSTS` env var |
| HSTS / SSL redirect | Off | On (`SECURE_SSL_REDIRECT = True`) |

To run with production settings locally (e.g. to test against a local Postgres):

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py runserver
```

Or set `DJANGO_SETTINGS_MODULE=config.settings.prod` in your `.env` file and `source` it.

Production deployment (Gunicorn, Nginx, systemd, etc.) is not yet documented — the deployment pipeline has not been decided.

---

## Repo boundaries

This is the backend-only repository. The mobile/frontend app lives in a separate repo (`Pentecost-Management-App/`). The backend exposes a versioned REST API (`/api/v1/…`) that the mobile app consumes — there is no server-side rendering or shared code between the two repos. Do not make changes to `Pentecost-Management-App/` from within this repo.
