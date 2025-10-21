# core/queries.py
import os
import uuid
import bcrypt
import pandas as pd
from django.db import transaction
from django.db import connection
from django.db.models import Count, Max
from core import core_models
from core.db_utils import fetch_all, fetch_one, execute_raw
from django.conf import settings
import json
from datetime import datetime

# --- Expected schema for checkups table ---
CHECKUP_COLUMNS = [
    "tanggal_checkup", "lingkar_perut",
    "gula_darah_puasa", "cholesterol", "asam_urat", "status",
    "tanggal_lahir", "umur", "gula_darah_sewaktu", "lokasi"
]

# --- Numeric columns centralized for rounding ---
NUMERIC_COLS = [
    "tinggi", "berat", "lingkar_perut", "bmi",
    "gula_darah_puasa", "gula_darah_sewaktu",
    "cholesterol", "asam_urat"
]

# --- Utility: enforce rounding on numeric cols ---
def _round_numeric_cols(df: pd.DataFrame, cols=None, decimals=2) -> pd.DataFrame:
    if cols is None:
        cols = NUMERIC_COLS
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).round(decimals)
    return df

# Add a safe DB introspection helper to avoid selecting non-existent columns on unmanaged tables
def _db_has_column(table_name: str, column_name: str) -> bool:
    try:
        with connection.cursor() as cursor:
            cols = connection.introspection.get_table_description(cursor, table_name)
            return any(getattr(c, "name", None) == column_name for c in cols)
    except Exception as e:
        print(f"DEBUG: Introspection failed for {table_name}.{column_name}: {e}")
        return False

# -------------------------
# Karyawan
# -------------------------
def get_employees() -> pd.DataFrame:
    """Return all employees as a DataFrame with properly formatted dates."""
    # Build field list dynamically to avoid selecting columns that don't exist in the DB
    fields = [
        "uid", "nama", "jabatan", "lokasi", "tanggal_lahir",
        "tanggal_MCU", "expired_MCU", "derajat_kesehatan",
        # Include anthropometric master data for dashboard display
        "tinggi", "berat", "bmi",
        # BMI category label from XLS
        "bmi_category",
    ]
    if _db_has_column("karyawan", "umur"):
        fields.insert(5, "umur")  # keep umur near tanggal_lahir for template expectations

    qs = core_models.Karyawan.objects.all().values(*fields)
    df = pd.DataFrame(list(qs))

    # Ensure umur column exists for templates (pass-through only; no auto-compute)
    if "umur" not in df.columns:
        df["umur"] = None
    
    if not df.empty:
        # Round anthropometric numeric columns for clean display
        df = _round_numeric_cols(df, cols=["tinggi", "berat", "bmi"])  # safe: only rounds if columns exist

        # Do NOT auto-compute umur. Use value from DB/XLS as-is.
        # Format date fields as YYYY-MM-DD strings if present
        for col in ["tanggal_lahir", "tanggal_MCU", "expired_MCU"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime('%Y-%m-%d')
    
    return df


def get_employee_by_uid(uid):
    """Safely fetch a single employee by UID using explicit column selection."""
    # Build field list dynamically to avoid selecting columns that don't exist in the DB
    fields = [
        "uid", "nama", "jabatan", "lokasi", "tanggal_lahir",
        "tanggal_MCU", "expired_MCU", "derajat_kesehatan",
        # Include anthropometric master data for profile/edit views
        "tinggi", "berat", "bmi", "bmi_category",
    ]
    if _db_has_column("karyawan", "umur"):
        fields.insert(5, "umur")

    obj = core_models.Karyawan.objects.filter(uid=uid).values(*fields).first()
    if obj:
        # Maintain key presence for templates; do not compute umur
        obj["umur"] = obj.get("umur", None)
    return obj if obj else None

def add_employee_if_missing(username, jabatan, lokasi, tanggal_lahir=None, batch_id=None):
    """
    Add employee only if nama+jabatan already exists in XLS/master.
    Reject if not found (do not auto-create new UID).
    """
    existing = core_models.Karyawan.objects.filter(nama=username, jabatan=jabatan).first()
    if existing:
        return existing.uid
    # Reject if nama+jabatan combination does not exist
    raise ValueError(f"Karyawan '{username}' with jabatan '{jabatan}' not found in master data.")

# Alias for manager_views.py compatibility
add_employee_if_exists = add_employee_if_missing


def add_employee_from_sheet(username, jabatan, sheet_name, tanggal_lahir=None, batch_id=None):
    existing = core_models.Karyawan.objects.filter(nama=username, jabatan=jabatan).first()
    if existing:
        return existing.uid
    raise ValueError(f"Karyawan '{username}' with jabatan '{jabatan}' not found in master data.")

def get_karyawan_uid_bulk(df: pd.DataFrame):
    """
    Optimized bulk lookup of Karyawan UIDs from uploaded XLS.
    """
    keys = df[["nama", "jabatan", "lokasi", "tanggal_lahir"]].drop_duplicates().to_dict(orient="records")
    mapping = {}
    for row in keys:
        qs = core_models.Karyawan.objects.filter(nama=row["nama"])
        if row.get("jabatan"):
            qs = qs.filter(jabatan=row["jabatan"])
        if row.get("lokasi"):
            qs = qs.filter(lokasi=row["lokasi"])
        if row.get("tanggal_lahir"):
            qs = qs.filter(tanggal_lahir=row["tanggal_lahir"])
        obj = qs.first()
        if obj:
            mapping[(row["nama"], row.get("jabatan"), row.get("lokasi"), row.get("tanggal_lahir"))] = obj.uid
    return mapping

# -------------------------
# Checkups
# -------------------------
def load_checkups():
    qs = core_models.Checkup.objects.select_related("uid").order_by("-tanggal_checkup").values(
        "checkup_id", "uid_id", "tanggal_checkup", "tanggal_lahir", "umur",
        "tinggi", "berat", "lingkar_perut", "bmi",
        "gula_darah_puasa", "gula_darah_sewaktu", "cholesterol", "asam_urat",
        "tekanan_darah", "derajat_kesehatan", "lokasi",
        "uid__nama", "uid__jabatan", "uid__lokasi"
    )
    df = pd.DataFrame(list(qs))
    # Normalize related field names
    df = df.rename(columns={
        "uid__nama": "nama",
        "uid__jabatan": "jabatan",
        "uid__lokasi": "lokasi",
        "uid_id": "uid",
    })
    df = _round_numeric_cols(df)
    for col in ["tanggal_checkup", "tanggal_lahir"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df

def save_checkups(df: pd.DataFrame):
    missing_cols = [col for col in CHECKUP_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    df = _round_numeric_cols(df)
    records = df.to_dict(orient="records")
    # Normalize foreign key field: use uid_id for FK
    normalized = []
    for rec in records:
        if "uid" in rec and "uid_id" not in rec:
            rec["uid_id"] = rec.pop("uid")
        normalized.append(rec)
    objs = [core_models.Checkup(**rec) for rec in normalized]
    core_models.Checkup.objects.bulk_create(objs, ignore_conflicts=True)

def save_uploaded_checkups(df: pd.DataFrame):
    required_cols = [
        "nama", "jabatan", "lokasi", "tanggal_checkup", "tanggal_lahir",
        "lingkar_perut", "umur",
        "gula_darah_puasa", "gula_darah_sewaktu", "cholesterol", "asam_urat"
    ]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Parse dates
    df["tanggal_checkup"] = pd.to_datetime(df["tanggal_checkup"], errors="coerce").dt.date
    df["tanggal_lahir"] = pd.to_datetime(df["tanggal_lahir"], errors="coerce").dt.date

    # Round numeric columns
    df = _round_numeric_cols(df)

    # Bulk UID mapping
    uid_map = get_karyawan_uid_bulk(df)
    df["uid"] = df.apply(
        lambda row: uid_map.get(
            (row["nama"], row.get("jabatan"), row.get("lokasi"), row.get("tanggal_lahir"))
        ),
        axis=1
    )

    # Keep only rows with valid UID
    df = df[df["uid"].notnull()].copy()
    if not df.empty:
        save_checkups(df)

def get_medical_checkups_by_uid(uid: str):
    qs = core_models.Checkup.objects.filter(uid_id=uid).order_by("-tanggal_checkup")
    df = pd.DataFrame(list(qs.values()))
    return _round_numeric_cols(df)

def insert_medical_checkup(**kwargs):
    """Create a Checkup record.
    Accepts either uid_id (preferred) or uid (string), and normalizes to uid_id to satisfy the ForeignKey.
    """
    uid = kwargs.pop("uid", None)
    if uid is not None and "uid_id" not in kwargs:
        # Normalize raw UID string to ForeignKey field name
        kwargs["uid_id"] = uid
    return core_models.Checkup.objects.create(**kwargs)

def delete_checkup(checkup_id: str):
    core_models.Checkup.objects.filter(checkup_id=checkup_id).delete()

def get_latest_medical_checkup(uid: str = None):
    if uid:
        qs = core_models.Checkup.objects.filter(uid_id=uid).order_by("-tanggal_checkup")
    else:
        print("DEBUG: Getting latest medical checkups for all employees")
        latest_dates = core_models.Checkup.objects.values("uid").annotate(latest=Max("tanggal_checkup"))
        print(f"DEBUG: Found {len(latest_dates)} latest dates")
        qs = core_models.Checkup.objects.filter(
            uid_id__in=[row["uid"] for row in latest_dates],
            tanggal_checkup__in=[row["latest"] for row in latest_dates]
        )
        print(f"DEBUG: Found {qs.count()} latest checkups")
    
    # Convert queryset to DataFrame
    df = pd.DataFrame(list(qs.values()))
    
    # Rename uid_id to uid if present
    if not df.empty and 'uid_id' in df.columns:
        df = df.rename(columns={'uid_id': 'uid'})
    
    print(f"DEBUG: DataFrame has {len(df)} rows")
    return _round_numeric_cols(df)

def delete_all_checkups():
    core_models.Checkup.objects.all().delete()

# -------------------------
# Users
# -------------------------
def get_users():
    qs = core_models.User.objects.all().values("id", "username", "role")
    return pd.DataFrame(list(qs))


def get_user_by_username(username):
    return core_models.User.objects.filter(username=username).first()

def add_user(username, password, role):
    # Enforce role caps: Manager max 5, Tenaga Kesehatan (Nurse) max 10, Karyawan no limit
    if role == "Manager" and count_users_by_role("Manager") >= 5:
        raise ValueError("Limit akun Manager telah mencapai 5. Tidak dapat menambah lagi.")
    if role == "Tenaga Kesehatan" and count_users_by_role("Tenaga Kesehatan") >= 10:
        raise ValueError("Limit akun Tenaga Kesehatan telah mencapai 10. Tidak dapat menambah lagi.")

    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode("utf-8")
    core_models.User.objects.create(username=username, password=hashed_pw, role=role)

def delete_user_by_id(user_id: int):
    """
    Remove a user given their primary key (ID).
    """
    core_models.User.objects.filter(id=user_id).delete()

def reset_user_password(username: str, new_password: str):
    hashed_pw = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode("utf-8")
    core_models.User.objects.filter(username=username).update(password=hashed_pw)

def count_users_by_role(role: str) -> int:
    return core_models.User.objects.filter(role=role).count()

def get_upload_history() -> pd.DataFrame:
    records = []
    for fname in os.listdir(settings.UPLOAD_DIR):
        path = os.path.join(settings.UPLOAD_DIR, fname)
        if os.path.isfile(path):
            size_kb = round(os.path.getsize(path) / 1024, 2)
            created_at = pd.to_datetime(os.path.getctime(path), unit="s")
            records.append({"filename": fname, "size_kb": size_kb, "created_at": created_at})
    return pd.DataFrame(records)

# -------------------------
# Karyawan manual edits
# -------------------------

def delete_employee_by_uid(uid: str):
    """Delete a single Karyawan by UID."""
    # Use raw SQL to avoid ORM selecting non-existent columns in some DBs
    execute_raw("DELETE FROM karyawan WHERE uid=%s", [uid])


def save_manual_karyawan_edits(df: pd.DataFrame):
    if df.empty:
        return 0
    for _, row in df.iterrows():
        uid = row.get("uid")
        if not uid:
            continue
        # Exclude 'umur' to match legacy DB schemas where Karyawan table has no 'umur' column
        updates = {col: row[col] for col in row.index if col not in ("uid", "umur") and pd.notna(row[col])}
        if updates:
            core_models.Karyawan.objects.filter(uid=uid).update(**updates)
    return len(df)

def reset_karyawan_data():
    # Use raw SQL to avoid ORM SELECT of non-existent columns (e.g., umur) on managed=False models
    execute_raw("DELETE FROM karyawan")


def change_username(old_username: str, new_username: str):
    """Change a user's username ensuring uniqueness and non-empty value."""
    if new_username is None or not str(new_username).strip():
        raise ValueError("Username baru tidak boleh kosong.")
    new_username = str(new_username).strip()
    # Check if the new username is already taken
    if core_models.User.objects.filter(username=new_username).exists():
        raise ValueError("Username baru sudah digunakan.")
    # Perform the update
    core_models.User.objects.filter(username=old_username).update(username=new_username)


def write_checkup_upload_log(filename: str, result: dict):
    """Write a JSON log entry for a checkup upload result."""
    os.makedirs(settings.UPLOAD_LOG_DIR, exist_ok=True)
    log_entry = {
        "filename": filename,
        "inserted": int(result.get("inserted", 0)),
        "skipped_count": int(len(result.get("skipped", [])) if isinstance(result.get("skipped"), list) else result.get("skipped", 0)),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "inserted_ids": result.get("inserted_ids", []),
    }
    # Use timestamp + filename for uniqueness
    safe_name = os.path.basename(filename)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(settings.UPLOAD_LOG_DIR, f"checkups-{ts}-{safe_name}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, ensure_ascii=False, indent=2)
    return log_path


def get_checkup_upload_history() -> pd.DataFrame:
    """Return DataFrame of checkup upload logs by reading JSON files from UPLOAD_LOG_DIR."""
    os.makedirs(settings.UPLOAD_LOG_DIR, exist_ok=True)
    records = []
    for fname in os.listdir(settings.UPLOAD_LOG_DIR):
        if not fname.startswith("checkups-") or not fname.endswith(".json"):
            continue
        path = os.path.join(settings.UPLOAD_LOG_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                records.append({
                    "filename": data.get("filename"),
                    "inserted": int(data.get("inserted", 0)),
                    "skipped_count": int(data.get("skipped_count", 0)),
                    "timestamp": pd.to_datetime(data.get("timestamp")),
                    "log_file": fname,
                    "inserted_ids": data.get("inserted_ids", []),
                })
        except Exception:
            # Skip malformed logs
            continue
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("timestamp", ascending=False)
    return df
