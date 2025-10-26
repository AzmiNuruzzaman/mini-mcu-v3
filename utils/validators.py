# utils/validators.py
try:
    import pandas as pd
except Exception:
    class _PDStub:
        class DataFrame:
            pass
        class Timestamp:
            def __init__(self, *args, **kwargs):
                pass
        @staticmethod
        def isna(x):
            return x is None
        @staticmethod
        def notna(x):
            return x is not None
        @staticmethod
        def to_datetime(val, errors='coerce', dayfirst=False, origin=None, unit=None, format=None):
            try:
                from datetime import datetime
                if isinstance(val, (int, float)):
                    return None
                if isinstance(val, str):
                    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
                        try:
                            return datetime.strptime(val, fmt)
                        except ValueError:
                            continue
                return None
            except Exception:
                return None
    pd = _PDStub()
from datetime import datetime

# -----------------------------
# Lokasi validator
# -----------------------------
def validate_lokasi(lokasi: str) -> bool:
    """
    Simple lokasi validator.
    For now just ensures lokasi is not None/empty.
    Later can extend to check against DB (Lokasi table).
    """
    if not lokasi or not str(lokasi).strip():
        return False
    return True


# -----------------------------
# String Normalization
# -----------------------------
def normalize_string(val):
    """Normalize strings (strip + lowercase)."""
    if isinstance(val, str):
        return val.strip().lower()
    elif pd.notna(val):
        return str(val).strip().lower()
    return ''


# -----------------------------
# Safe numeric conversions
# -----------------------------
def safe_float(val):
    """Convert to float safely (handles comma decimals, NaN)."""
    try:
        if pd.notna(val):
            if isinstance(val, str):
                val = val.replace(",", ".")
            return float(val)
    except Exception:
        pass
    return None


# -----------------------------
# Safe date conversions
# -----------------------------
def safe_date(val):
    """Convert to datetime.date safely. Handles Excel serials, strings, and rejects invalid years."""
    import numpy as np
    try:
        if val is None or pd.isna(val):
            return None

        # Excel serial (numeric)
        if isinstance(val, (int, float, np.integer, np.floating)):
            try:
                dt = pd.to_datetime(val, origin="1899-12-30", unit="D")
                return dt.date() if dt.year >= 1901 else None
            except Exception:
                return None

        # Datetime or Timestamp
        if isinstance(val, (datetime, pd.Timestamp)):
            return val.date() if val.year >= 1901 else None

        # String formats
        if isinstance(val, str):
            val = val.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
                try:
                    dt = datetime.strptime(val, fmt)
                    return dt.date() if dt.year >= 1901 else None
                except ValueError:
                    continue
            # fallback to pandas parser
            dt = pd.to_datetime(val, errors="coerce", dayfirst=True)
            if pd.notna(dt) and dt.year >= 1901:
                return dt.date()
    except Exception:
        return None
    return None



# -----------------------------
# Column mapping helpers (Excel → DB fields)
# -----------------------------
DB_COLUMNS = {
    "nama": ["nama", "employee_name", "karyawan"],
    "jabatan": ["jabatan", "position", "title"],
    "lokasi": ["lokasi", "location", "site"],
    "tanggal_lahir": ["tanggal_lahir", "tgl_lahir", "tanggal lahir", "birthdate", "dob"],
}

MANDATORY_FIELDS_MASTER = ["nama", "jabatan", "tanggal_lahir"]

def map_columns(df: pd.DataFrame):
    """
    Map uploaded Excel columns to DB schema columns.
    Returns dict: {db_col: actual_col_name or None}
    """
    lower_cols = {c.lower().strip(): c for c in df.columns}
    mapped = {}
    for db_col, aliases in DB_COLUMNS.items():
        for alias in aliases:
            if alias.lower().strip() in lower_cols:
                mapped[db_col] = lower_cols[alias.lower().strip()]
                break
        else:
            mapped[db_col] = None
    return mapped
