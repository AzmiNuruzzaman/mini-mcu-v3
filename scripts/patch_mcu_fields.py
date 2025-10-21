import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mini_mcu.settings')
django.setup()

from django.db import connection
from django.conf import settings


def column_exists_postgres(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'karyawan'
          AND column_name = %s
        LIMIT 1
        """,
        [column_name],
    )
    return cursor.fetchone() is not None


def patch_postgres(cursor):
    # Use quoted identifiers to preserve case-sensitive column names
    cursor.execute(
        'ALTER TABLE public.karyawan ADD COLUMN IF NOT EXISTS "tanggal_MCU" DATE;'
    )
    cursor.execute(
        'ALTER TABLE public.karyawan ADD COLUMN IF NOT EXISTS "expired_MCU" DATE;'
    )


def main():
    engine = settings.DATABASES['default']['ENGINE']
    with connection.cursor() as cursor:
        if 'postgresql' in engine:
            before = {
                'tanggal_MCU': column_exists_postgres(cursor, 'tanggal_MCU'),
                'expired_MCU': column_exists_postgres(cursor, 'expired_MCU'),
            }
            patch_postgres(cursor)
            after = {
                'tanggal_MCU': column_exists_postgres(cursor, 'tanggal_MCU'),
                'expired_MCU': column_exists_postgres(cursor, 'expired_MCU'),
            }
            print(f"Patched Postgres. Before: {before} After: {after}")
        else:
            print(f"Unsupported DB engine for this patch: {engine}")


if __name__ == '__main__':
    main()