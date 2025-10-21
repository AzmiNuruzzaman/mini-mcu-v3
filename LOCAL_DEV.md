# Local Development Setup

This project is configured to run locally without changing application logic. Follow these steps on Windows:

## Prerequisites
- Python 3.10+
- PostgreSQL (recommended) or access to a remote Railway Postgres

## 1) Create and activate a virtual environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 2) Install dependencies
```powershell
pip install -r requirements.txt
```

## 3) Configure environment
A starter `.env` has been added. It enables local debug, CSRF trust for localhost, media serving, and database selection.

Options:
- Local Postgres: ensure a database named `mini_mcu_v2` exists with required tables (restore `backup.sql`), then keep `DJANGO_USE_LOCAL_DB=True` in `.env`.
- Railway Postgres from local: comment out `DJANGO_USE_LOCAL_DB` and set `DATABASE_PUBLIC_URL` from Railway (append `?sslmode=require`).

## 4) Run the development server
```powershell
python manage.py runserver
```
Open `http://localhost:8000/` and you’ll be redirected to `/accounts/login/`.

## Notes
- Static files are served from `static/` and media/uploads directories are created automatically.
- Models are `managed=False` and expect existing tables (`users`, `lokasi`, `karyawan`, `checkups`). Use `backup.sql` to seed a local Postgres.
- If you plan to generate QR codes, set `APP_BASE_URL` in `.env` to `http://localhost:8000`.