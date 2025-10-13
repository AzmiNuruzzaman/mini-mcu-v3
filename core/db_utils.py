# core/db_utils.py
from django.db import connection, transaction
from core import core_models


# -----------------------------
# Low-level helpers
# -----------------------------
def execute_raw(sql, params=None):
    """
    Execute a raw SQL command (INSERT/UPDATE/DELETE).
    Example:
        execute_raw("UPDATE users SET role=%s WHERE id=%s", ["Manager", 1])
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
    # Auto-commit is handled by Django unless inside @transaction.atomic


def fetch_one(sql, params=None):
    """
    Fetch a single row from raw SQL.
    Returns dict or None.
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
        if row is None:
            return None
        col_names = [col[0] for col in cursor.description]
        return dict(zip(col_names, row))


def fetch_all(sql, params=None):
    """
    Fetch multiple rows from raw SQL.
    Returns list of dicts.
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        rows = cursor.fetchall()
        col_names = [col[0] for col in cursor.description]
        return [dict(zip(col_names, row)) for row in rows]


# -----------------------------
# ORM wrappers (for convenience)
# -----------------------------
def get_user_by_username(username: str):
    """Get user object or None by username."""
    return core_models.User.objects.filter(username=username).first()


def create_checkup(**kwargs):
    """Insert a new Checkup row using ORM."""
    return core_models.Checkup.objects.create(**kwargs)


def get_checkups_by_uid(uid):
    """Return all checkups for a given Karyawan UID."""
    return core_models.Checkup.objects.filter(uid=uid).order_by("-tanggal_checkup")


def get_karyawan(uid):
    """Get a Karyawan by UID (or None)."""
    return core_models.Karyawan.objects.filter(uid=uid).first()
