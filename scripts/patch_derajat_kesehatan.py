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


def column_exists_postgres(cursor):
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'checkups'
          AND column_name = 'derajat_kesehatan'
        LIMIT 1
        """
    )
    return cursor.fetchone() is not None


def column_exists_mysql(cursor):
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = 'checkups'
          AND column_name = 'derajat_kesehatan'
        LIMIT 1
        """
    )
    return cursor.fetchone() is not None


def column_exists_sqlite(cursor):
    cursor.execute("PRAGMA table_info(checkups);")
    rows = cursor.fetchall()
    for row in rows:
        # row: (cid, name, type, notnull, dflt_value, pk)
        if len(row) >= 2 and str(row[1]).lower() == 'derajat_kesehatan':
            return True
    return False


def patch():
    vendor = connection.vendor  # 'postgresql', 'mysql', 'sqlite'
    print(f"[INFO] DB vendor: {vendor}")
    with connection.cursor() as cursor:
        try:
            # Check existence first to be idempotent
            exists = False
            if vendor == 'postgresql':
                exists = column_exists_postgres(cursor)
            elif vendor == 'mysql':
                exists = column_exists_mysql(cursor)
            elif vendor == 'sqlite':
                exists = column_exists_sqlite(cursor)
            else:
                print(f"[ERROR] Unsupported DB vendor: {vendor}")
                sys.exit(2)

            # If exists, ensure type/length is appropriate; else add with correct type
            if exists:
                if vendor == 'postgresql':
                    cursor.execute("ALTER TABLE checkups ALTER COLUMN derajat_kesehatan TYPE VARCHAR(10);")
                    cursor.execute("ALTER TABLE checkups ALTER COLUMN derajat_kesehatan DROP NOT NULL;")
                    print("[DONE] Ensured 'derajat_kesehatan' is VARCHAR(10) NULL on Postgres.")
                elif vendor == 'mysql':
                    cursor.execute("ALTER TABLE checkups MODIFY COLUMN derajat_kesehatan VARCHAR(10) NULL;")
                    print("[DONE] Ensured 'derajat_kesehatan' is VARCHAR(10) NULL on MySQL.")
                elif vendor == 'sqlite':
                    print("[OK] SQLite column exists; type is flexible (TEXT/VARCHAR). No changes needed.")
                return

            # Add column per vendor with preferred type/length
            if vendor == 'postgresql':
                cursor.execute("ALTER TABLE checkups ADD COLUMN derajat_kesehatan VARCHAR(10);")
            elif vendor == 'mysql':
                cursor.execute("ALTER TABLE checkups ADD COLUMN derajat_kesehatan VARCHAR(10) NULL;")
            elif vendor == 'sqlite':
                cursor.execute("ALTER TABLE checkups ADD COLUMN derajat_kesehatan TEXT;")

            print("[DONE] Added column 'derajat_kesehatan' to table 'checkups' with preferred type.")
        except Exception as e:
            print("[ERROR] Failed to patch DB:")
            traceback.print_exc()
            sys.exit(3)


if __name__ == '__main__':
    patch()