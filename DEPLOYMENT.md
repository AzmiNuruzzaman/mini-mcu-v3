# Deployment Guide (Railway + Django)

This project uses Django with unmanaged models (`managed=False`). The app expects the Postgres tables to already exist in the target database. On a fresh Railway database, you must restore your local `public` schema or manually create tables and seed login-capable users before testing `/accounts/login/`.

## Prerequisites
- Python 3.10+
- PostgreSQL client tools available (`psql`, `pg_dump`)
- Access to Railway project with the following environment variables:
  - `DATABASE_URL` (internal Railway host)
  - `DATABASE_PUBLIC_URL` (public proxy host, for local tools)

## Environment
- The app reads `DATABASE_URL` when deployed and enforces `search_path=public`.
- Use `DATABASE_PUBLIC_URL` for local import/export and PG clients: append `?sslmode=require`.

## Railway Start Command
Railway uses `Procfile` for the start command:
```
web: python manage.py collectstatic --noinput && gunicorn mini_mcu.wsgi:application --bind 0.0.0.0:$PORT --workers 3
```
Note: With `managed=False` models and no migrations, `migrate` is a no-op and not required here.

## Tables Required (schema `public`)
Create or restore these tables with exact lowercase names:
- `users`: `id serial pk`, `username varchar(100) unique`, `password text`, `role varchar(50)`, `created_at timestamp null`
- `lokasi`: `nama text pk`
- `karyawan`: `uid uuid pk`, `nama text`, `jabatan text`, `lokasi text`, `tanggal_lahir date null`, `uploaded_at timestamp null`, `upload_batch_id uuid null`
- `checkups`: `checkup_id serial pk`, `uid uuid references karyawan(uid) on delete cascade`, plus health metric columns (`tanggal_checkup`, `tanggal_lahir`, `umur`, `tinggi`, `berat`, `lingkar_perut`, `bmi`, `gula_darah_puasa`, `gula_darah_sewaktu`, `cholesterol`, `asam_urat`, `status`, `lokasi`, `derajat_kesehatan`)

## Import Local DB into Railway
Export local `public` schema:
```
pg_dump -h localhost -U postgres -d mini_mcu_v2 --schema=public --no-owner --no-privileges -f backup.sql
```
Restore to Railway (public proxy):
```
psql "postgresql://postgres:<password>@<public-host>:<port>/railway?sslmode=require" -f backup.sql
```
Stream directly (no file):
```
pg_dump -h localhost -U postgres -d mini_mcu_v2 --schema=public --no-owner --no-privileges | \
psql "postgresql://postgres:<password>@<public-host>:<port>/railway?sslmode=require"
```

## Seed Users (bcrypt)
Roles allowed to log in: `Master`, `Manager`, `Tenaga Kesehatan`.
Hashes provided for convenience:
- Manager `manager123` → `$2b$12$dVJeTCqVfkNX0DGep0jtke4WhCTe.7nZ5w6ZWOvtYw4qP8hFMOWR2`
- Nurse `nurse123` → `$2b$12$tqiUTGndtzQjfc9O6/47T.iBJx7Jh4OKjFXRY1GK.C9OcJvP9r65S`

Run `seed_users.sql` against your Railway DB (schema `public`):
```
psql "postgresql://postgres:<password>@<public-host>:<port>/railway?sslmode=require" -f seed_users.sql
```

## Verification
- Confirm tables exist: `\dt public.*`
- Check users: `SELECT id, username, role FROM users;`
- Test login at `/accounts/login/` with:
  - Manager: `manager` / `manager123` → redirects to `/manager/`
  - Nurse: `test` / `nurse123` → redirects to `/nurse/`

## Notes
- Ensure all tables live in `public` and names are lowercase (unquoted). Mixed case or non-public schema will break ORM access.
- For app-based seeding, `/master/login/` (`developer` / `supersecretpassword`) can create Manager/Nurse accounts via the dashboard.