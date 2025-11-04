## Quick orientation for AI coding agents

This repository is a Django web app (project: `mini_mcu`) with a small front-end in `static/` (JS/CSS) and conventional Django templates under `mini_mcu/templates` and each app's `templates/`.

Key places to read first:
- `mini_mcu/settings.py` — central config (DB selection via `DATABASE_URL` / `DJANGO_USE_LOCAL_DB` / `DJANGO_USE_SQLITE`, `STATIC_ROOT`, `MEDIA_ROOT`, installed apps).
- `LOCAL_DEV.md` and `DEPLOYMENT.md` — step-by-step developer and deployment workflows.
- `Procfile` — production start command (collectstatic + gunicorn).
- apps: `core/`, `accounts/`, and `users_ui/` (umbrella app with `karyawan`, `nurse`, `manager`, `master`, `qr`).

Architecture & important constraints
- Apps: `users_ui` is the umbrella app. Sub-apps are registered individually in `INSTALLED_APPS` (e.g., `users_ui.nurse`). Follow this pattern when adding features.
- Models: project expects existing DB tables (many models use `managed=False`). See `DEPLOYMENT.md` and `LOCAL_DEV.md` — do NOT assume migrations will create tables on deploy.
- DB: code uses `dj_database_url` and a normalization helper in `mini_mcu/settings.py` to handle special characters in `DATABASE_URL`. When running locally, set `DJANGO_USE_LOCAL_DB` or `DJANGO_USE_SQLITE` in `.env` per `LOCAL_DEV.md`.
- Static & Media: static files live in `static/`, collected to `staticfiles/` (Whitenoise used in prod). Media/uploads created under `media/uploads` (check `settings.py` for exact paths).

Developer workflows (explicit commands)
- Create virtualenv (Windows PowerShell):
  python -m venv .venv
  .\\.venv\\Scripts\\Activate.ps1
- Install deps:
  pip install -r requirements.txt
- Run dev server (default uses `mini_mcu.settings`):
  python manage.py runserver
- Run production-like start (same as Procfile):
  python manage.py collectstatic --noinput && gunicorn mini_mcu.wsgi:application --bind 0.0.0.0:$PORT --workers 3

Project-specific patterns & examples
- Context processors: menu/notification injection is app-specific — check `users_ui.manager.context_processors.manager_menu` and `users_ui.nurse.context_processors.nurse_menu` for how menus are assembled.
- Login flow: `LOGIN_URL = 'accounts:login'` and `LOGIN_REDIRECT_URL = '/manager/'` in `settings.py`. Tests/fixes that change auth redirects should update these values.
- DB schema expectations: the app uses the `public` schema and lower-case, unquoted table names (see `DEPLOYMENT.md`). If you add queries or migrations, ensure schema and names match.
- Front-end assets: `static/js/app.js` and `static/js/components/` hold UI logic (lightweight Vue/JS components). Keep edits consistent with existing patterns and avoid adding a full build pipeline unless requested.

Integration & external dependencies
- Postgres (psycopg2) and dj-database-url are used; env vars include `DATABASE_URL`, `DATABASE_PUBLIC_URL`, `DJANGO_USE_LOCAL_DB`, `DJANGO_USE_SQLITE`.
- `.env` is loaded with `python-dotenv`. Look at `mini_mcu/settings.py` for env toggles (`DEBUG`, `SERVE_MEDIA`, `APP_BASE_URL`).
- Whitenoise serves static files in production; gunicorn is used as WSGI server.

Tips for safe edits
- Don't assume migrations will run in production. If you introduce new models, coordinate schema changes with DB migration/restore scripts and update `DEPLOYMENT.md`.
- When changing DB connection logic, preserve the `_normalize_database_url` helper behavior — it handles special characters in passwords.
- If touching uploads/static, run `collectstatic` and verify `MEDIA_ROOT`/`STATIC_ROOT` creation paths.

Files worth referencing when coding:
- `mini_mcu/settings.py`, `LOCAL_DEV.md`, `DEPLOYMENT.md`, `Procfile`, `requirements.txt`, `seed_users.sql`, `backup_V4.sql`.

If anything in these notes is unclear or you want more detail on a specific area (DB schema, a particular app, or front-end assets), ask and I will expand or tighten this guidance.
