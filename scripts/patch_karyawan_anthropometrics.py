import os
import sys
import traceback

# Setup Django
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mini_mcu.settings")
try:
    import django
    django.setup()
except Exception:
    print("[ERROR] Failed to setup Django:")
    traceback.print_exc()
    sys.exit(1)

from django.db import connection

TABLE_NAME = "karyawan"
COLUMNS = [
    ("tinggi", "NUMERIC(6,2)", "DECIMAL(6,2)", "REAL"),
    ("berat",  "NUMERIC(6,2)", "DECIMAL(6,2)", "REAL"),
    ("bmi",    "NUMERIC(6,2)", "DECIMAL(6,2)", "REAL"),
]


def postgres_column_exists(cursor, column_name):
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        [TABLE_NAME, column_name]
    )
    return cursor.fetchone() is not None


def mysql_column_exists(cursor, column_name):
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        [TABLE_NAME, column_name]
    )
    return cursor.fetchone() is not None


def sqlite_column_exists(cursor, column_name):
    cursor.execute("PRAGMA table_info(%s);" % TABLE_NAME)
    rows = cursor.fetchall()
    for row in rows:
        # row: (cid, name, type, notnull, dflt_value, pk)
        if len(row) >= 2 and str(row[1]).lower() == column_name.lower():
            return True
    return False


def patch():
    vendor = connection.vendor  # 'postgresql', 'mysql', 'sqlite'
    print(f"[INFO] Connected DB vendor: {vendor}")
    try:
        with connection.cursor() as cursor:
            for col_name, pg_type, my_type, sqlite_type in COLUMNS:
                print(f"[CHECK] Ensuring column '{col_name}' exists on '{TABLE_NAME}'...")
                # Check existence per vendor
                if vendor == 'postgresql':
                    exists = postgres_column_exists(cursor, col_name)
                elif vendor == 'mysql':
                    exists = mysql_column_exists(cursor, col_name)
                elif vendor == 'sqlite':
                    exists = sqlite_column_exists(cursor, col_name)
                else:
                    print(f"[WARN] Unsupported vendor '{vendor}'. Skipping column '{col_name}'.")
                    continue

                if exists:
                    print(f"[SKIP] Column '{col_name}' already exists.")
                    continue

                # Add column per vendor
                print(f"[ADD] Adding column '{col_name}' to table '{TABLE_NAME}'...")
                if vendor == 'postgresql':
                    cursor.execute(f"ALTER TABLE public.{TABLE_NAME} ADD COLUMN {col_name} {pg_type} NULL;")
                elif vendor == 'mysql':
                    cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col_name} {my_type} NULL;")
                elif vendor == 'sqlite':
                    cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col_name} {sqlite_type};")
                print(f"[DONE] Added column '{col_name}'.")

        print("[SUCCESS] Karyawan anthropometric columns ensured (tinggi, berat, bmi).")
    except Exception:
        print("[ERROR] Failed to patch DB:")
        traceback.print_exc()
        sys.exit(3)


if __name__ == '__main__':
    patch()