from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = "Add bmi_category column to karyawan table (safe patch)."

    def handle(self, *args, **options):
        table = "karyawan"
        column = "bmi_category"
        vendor = connection.vendor

        self.stdout.write(self.style.NOTICE(f"DB vendor: {vendor}"))

        # Check if column already exists
        exists = False
        with connection.cursor() as cursor:
            try:
                if vendor == "sqlite":
                    cursor.execute(f"PRAGMA table_info({table})")
                    rows = cursor.fetchall()
                    cols = [row[1] for row in rows]
                    exists = column in cols
                elif vendor == "postgresql":
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
                        [table]
                    )
                    rows = cursor.fetchall()
                    cols = [row[0] for row in rows]
                    exists = column in cols
                elif vendor == "mysql":
                    cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                    rows = cursor.fetchall()
                    cols = [row[0] for row in rows]
                    exists = column in cols
                else:
                    # Fallback: attempt select and inspect description
                    cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                    cols = [desc[0] for desc in cursor.description]
                    exists = column in cols
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not introspect columns: {e}"))
                exists = False

        if exists:
            self.stdout.write(self.style.SUCCESS(f"Column '{column}' already exists on '{table}'. No action taken."))
            return

        # Build ALTER TABLE statement per vendor
        if vendor == "sqlite":
            sql = f"ALTER TABLE {table} ADD COLUMN {column} TEXT"
        elif vendor == "postgresql":
            sql = f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(30) NULL"
        elif vendor == "mysql":
            sql = f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(30) NULL"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR(30)"

        # Execute patch
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
            self.stdout.write(self.style.SUCCESS(f"Added column '{column}' to '{table}'."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to add column '{column}' to '{table}': {e}"))