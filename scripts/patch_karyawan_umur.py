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
COLUMN_NAME = "umur"


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
            # Check existence per vendor
            if vendor == 'postgresql':
                exists = postgres_column_exists(cursor, COLUMN_NAME)
            elif vendor == 'mysql':
                exists = mysql_column_exists(cursor, COLUMN_NAME)
            elif vendor == 'sqlite':
                exists = sqlite_column_exists(cursor, COLUMN_NAME)
            else:
                print(f"[WARN] Unsupported vendor '{vendor}'. Aborting.")
                sys.exit(2)

            if exists:
                print(f"[SKIP] Column '{COLUMN_NAME}' already exists on '{TABLE_NAME}'.")
            else:
                print(f"[ADD] Adding column '{COLUMN_NAME}' to table '{TABLE_NAME}'...")
                if vendor == 'postgresql':
                    cursor.execute(f"ALTER TABLE public.{TABLE_NAME} ADD COLUMN {COLUMN_NAME} INTEGER NULL;")
                elif vendor == 'mysql':
                    cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} INT NULL;")
                elif vendor == 'sqlite':
                    cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {COLUMN_NAME} INTEGER;")
                print(f"[DONE] Added column '{COLUMN_NAME}'.")

        print("[SUCCESS] Ensured 'umur' column exists on 'karyawan'.")
    except Exception:
        print("[ERROR] Failed to patch DB:")
        traceback.print_exc()
        sys.exit(3)


if __name__ == '__main__':
    patch()