-- Seed login-capable users for the Django app
-- Assumes `users` table exists in schema `public` with columns:
--   id SERIAL PRIMARY KEY,
--   username VARCHAR(100) UNIQUE,
--   password TEXT,
--   role VARCHAR(50),
--   created_at TIMESTAMP NULL

BEGIN;

-- Ensure username uniqueness (safe if already present)
CREATE UNIQUE INDEX IF NOT EXISTS users_username_uq ON users (username);

-- Manager user (username: manager, password: manager123)
INSERT INTO users (username, password, role, created_at)
VALUES (
  'manager',
  '$2b$12$dVJeTCqVfkNX0DGep0jtke4WhCTe.7nZ5w6ZWOvtYw4qP8hFMOWR2',
  'Manager',
  NOW()
)
ON CONFLICT (username) DO UPDATE SET
  password = EXCLUDED.password,
  role = EXCLUDED.role;

-- Nurse user (username: test, password: nurse123)
-- Role must be exactly 'Tenaga Kesehatan' to pass login access checks
INSERT INTO users (username, password, role, created_at)
VALUES (
  'test',
  '$2b$12$tqiUTGndtzQjfc9O6/47T.iBJx7Jh4OKjFXRY1GK.C9OcJvP9r65S',
  'Tenaga Kesehatan',
  NOW()
)
ON CONFLICT (username) DO UPDATE SET
  password = EXCLUDED.password,
  role = EXCLUDED.role;

COMMIT;