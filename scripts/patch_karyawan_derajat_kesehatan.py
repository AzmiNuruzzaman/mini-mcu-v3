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
COLUMN_NAME = "derajat_kesehatan"

SQL_CHECK_EXISTS = f"""
SELECT 1
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = '{TABLE_NAME}'
  AND column_name = '{COLUMN_NAME}';
"""

SQL_ADD_COLUMN = f"""
ALTER TABLE public.{TABLE_NAME}
ADD COLUMN {COLUMN_NAME} VARCHAR(10) NULL;
"""


def main():
    print(f"Patching table '{TABLE_NAME}' to ensure column '{COLUMN_NAME}' exists...")
    with connection.cursor() as cursor:
        cursor.execute(SQL_CHECK_EXISTS)
        exists = cursor.fetchone() is not None
        if exists:
            print(f"Column '{COLUMN_NAME}' already exists on '{TABLE_NAME}'.")
            return
        print(f"Adding column '{COLUMN_NAME}' to '{TABLE_NAME}' ...")
        cursor.execute(SQL_ADD_COLUMN)
        print("Done.")


if __name__ == "__main__":
    main()