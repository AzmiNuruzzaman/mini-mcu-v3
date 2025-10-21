# core/excel_parser.py (V2)
import pandas as pd
import uuid
import re
import logging
from core.core_models import Karyawan  # adjust import to your actual model
from utils.validators import normalize_string, validate_lokasi, safe_date, safe_float
from core.queries import get_karyawan_uid_bulk, insert_medical_checkup
from django.db import connection

logger = logging.getLogger(__name__)

DB_COLUMNS = {
    # Expand aliases to robustly map common header variants
    "uid": ["uid", "employee_id", "karyawan_uid", "nik", "employee_number"],
    "nama": ["nama", "nama_karyawan", "employee_name", "karyawan"],
    "jabatan": ["jabatan", "posisi", "position", "title"],
    "lokasi": ["lokasi", "location", "site"],
    "tanggal_lahir": ["tanggal_lahir", "tgl_lahir", "birthdate", "tanggal_lahir", "tanggal lahir", "dob"],
    "umur": ["umur", "age"],
    # Manual MCU fields (no computation; pass-through from XLS if present)
    "tanggal_MCU": ["tanggal_mcu", "tgl_mcu", "mcu_date", "tanggal MCU", "tanggal_mcu"],
    "expired_MCU": ["expired_mcu", "mcu_expired", "expiry_date", "mcu_expiry", "expired MCU", "expired_mcu"],
    # NEW: allow master to carry derajat_kesehatan baseline per karyawan
    "derajat_kesehatan": ["derajat_kesehatan", "derajat kesehatan", "derajat"],
    # NEW: anthropometrics moved to master upload
    "tinggi": ["tinggi", "tinggi_badan", "height", "tb"],
    "berat": ["berat", "berat_badan", "weight", "bb"],
    "bmi": ["bmi", "body_mass_index", "imt"],
    "bmi_category": ["bmi_category", "bmi_kategori", "kategori_bmi", "bmi category"],
}

# At minimum, require UID or Name to create a row (schema permits nulls for other fields)
MANDATORY_FIELDS_MASTER = ["uid_or_nama"]

def _normalize_header(s: str) -> str:
    s = s.strip().lower()
    # Replace non-alphanumeric with space, collapse spaces
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def map_columns(df: pd.DataFrame):
    """Map uploaded Excel columns to DB schema columns with tolerant matching.
    First try exact alias match; then token-contains fallback.
    """
    # Keep original names mapped by normalized form
    lower_cols = {c.lower().strip(): c for c in df.columns}
    normalized_to_original = { _normalize_header(c): c for c in df.columns }

    mapped = {}
    for db_col, aliases in DB_COLUMNS.items():
        # 1) Exact alias matching on simple lowercase
        found = None
        for alias in aliases:
            key = alias.lower().strip()
            if key in lower_cols:
                found = lower_cols[key]
                break
        if found:
            mapped[db_col] = found
            continue
        
        # 2) Fallback: token contains matching (e.g., "Nama (Karyawan)" → nama)
        for header_norm, original in normalized_to_original.items():
            for alias in aliases:
                alias_norm = _normalize_header(alias)
                alias_tokens = set(alias_norm.split())
                header_tokens = set(header_norm.split())
                # if all alias tokens present in header tokens, consider it a match
                if alias_tokens.issubset(header_tokens):
                    found = original
                    break
            if found:
                break
        mapped[db_col] = found
    return mapped


# Helper: discover actual DB columns for unmanaged table
_def_db_cols_cache = {}

def _get_db_columns(table_name: str):
    if table_name in _def_db_cols_cache:
        return _def_db_cols_cache[table_name]
    try:
        with connection.cursor() as cursor:
            desc = connection.introspection.get_table_description(cursor, table_name)
            cols = {col.name for col in desc}
            _def_db_cols_cache[table_name] = cols
            return cols
    except Exception:
        return set()

# Helper: parse age robustly from numeric or mixed strings (e.g., '33 tahun')
def _parse_age(val):
    if val is None:
        return None
    try:
        # Try to coerce numeric via safe_float first
        f = safe_float(val)
        if f is not None and not pd.isna(f):
            return int(f)
    except Exception:
        pass
    # Fallback: extract first integer sequence from string
    try:
        s = str(val)
        m = re.search(r"(\d+)", s)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def parse_master_karyawan(file_path):
    """
    Upload master karyawan data (V2):
    - Prefer a 'lokasi' column per row; fallback to sheet name
    - Columns: uid (optional), nama, jabatan, tanggal_lahir, tanggal_MCU, expired_MCU, derajat_kesehatan
    - Insert/update into Karyawan DB, adhering to schema (most fields nullable)
    """
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    total_inserted, total_skipped = 0, 0
    batch_id = str(uuid.uuid4())
    skipped_rows = []
    db_cols = _get_db_columns('karyawan')  # only write columns that actually exist

    for sheet_name, sheet_df in all_sheets.items():
        # ✅ normalize column names to handle variants robustly
        sheet_df.columns = sheet_df.columns.str.strip()
        # Default lokasi from sheet name (used as fallback only)
        sheet_lokasi = normalize_string(sheet_name)

        col_map = map_columns(sheet_df)
        print(f"Master upload: sheet='{sheet_name}' mapped columns: {col_map}")
        rename_dict = {v: k for k, v in col_map.items() if v}
        sheet_df = sheet_df.rename(columns=rename_dict)

        # Keep only relevant columns
        cols_to_keep = [c for c in DB_COLUMNS.keys() if c in sheet_df.columns]
        sheet_df = sheet_df[cols_to_keep]
        print(f"Master upload: sheet='{sheet_name}' columns after keep-filter: {list(sheet_df.columns)}")

        # Iterate rows and apply schema-adhering conversions
        for idx, row in sheet_df.iterrows():
            # Prefer UID from file if present
            uid_value = normalize_string(row.get("uid")) if "uid" in sheet_df.columns else ""
            nama = normalize_string(row.get("nama"))
            jabatan = normalize_string(row.get("jabatan"))
            tanggal_lahir = safe_date(row.get("tanggal_lahir"))
            tanggal_mcu = safe_date(row.get("tanggal_MCU"))
            expired_mcu = safe_date(row.get("expired_MCU"))
            # Normalize derajat_kesehatan to uppercase P1..P7 without extra spaces
            derajat_kesehatan = row.get("derajat_kesehatan")
            if derajat_kesehatan is not None:
                try:
                    derajat_kesehatan = str(derajat_kesehatan).strip().upper()
                except Exception:
                    derajat_kesehatan = None
            # Anthropometrics
            tinggi = safe_float(row.get("tinggi")) if "tinggi" in sheet_df.columns else None
            berat = safe_float(row.get("berat")) if "berat" in sheet_df.columns else None
            bmi = safe_float(row.get("bmi")) if "bmi" in sheet_df.columns else None
            bmi_category = normalize_string(row.get("bmi_category")) if "bmi_category" in sheet_df.columns else None
            # Age from XLS (no auto-calculation)
            umur = _parse_age(row.get("umur")) if "umur" in sheet_df.columns else None

            # Determine lokasi: prefer column value; fallback to sheet name
            lokasi_cell = normalize_string(row.get("lokasi")) if "lokasi" in sheet_df.columns else ""
            lokasi = lokasi_cell if validate_lokasi(lokasi_cell) else sheet_lokasi

            # Minimal requirement: have UID or Name to create a record
            if not uid_value and not nama:
                total_skipped += 1
                skipped_rows.append((sheet_name, idx, "Missing uid and nama"))
                continue

            # If neither column nor sheet provided a valid lokasi, fallback to sheet name anyway (do not skip)
            if not validate_lokasi(lokasi):
                lokasi = sheet_lokasi

            # Determine UID
            uid = uid_value if uid_value else str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{nama}-{jabatan}"))

            # Build all possible updates then filter by actual DB columns
            defaults = {
                "nama": nama or None,
                "jabatan": jabatan or None,
                "lokasi": lokasi,
                "tanggal_lahir": tanggal_lahir,
                "umur": umur,
                "tanggal_MCU": tanggal_mcu,
                "expired_MCU": expired_mcu,
                "derajat_kesehatan": derajat_kesehatan,
                "tinggi": tinggi,
                "berat": berat,
                "bmi": bmi,
                "bmi_category": bmi_category,
                # don't include upload_batch_id if DB doesn't have it
                "upload_batch_id": batch_id,
            }
            safe_updates = {k: v for k, v in defaults.items() if k in db_cols}

            try:
                # Avoid update_or_create to prevent ORM selecting non-existent columns on unmanaged tables
                if Karyawan.objects.filter(uid=uid).exists():
                    Karyawan.objects.filter(uid=uid).update(**safe_updates)
                else:
                    create_data = {"uid": uid}
                    create_data.update(safe_updates)
                    Karyawan.objects.create(**create_data)
                total_inserted += 1
            except Exception as e:
                total_skipped += 1
                skipped_rows.append((sheet_name, idx, str(e)))
        if skipped_rows:
            print(f"Master upload: sheet='{sheet_name}' skipped_rows example: {skipped_rows[:3]}")

    print(f"Master upload: total_inserted={total_inserted}, total_skipped={total_skipped}")
    return {
        "inserted": total_inserted,
        "skipped": total_skipped,
        "batch_id": batch_id,
        "skipped_rows": skipped_rows
    }

# -----------------------------
# Extended preview-only parsing (display more columns without logic changes)
# -----------------------------
EXTENDED_PREVIEW_COLUMNS = {
    # Master data
    "uid": ["uid", "employee_id", "karyawan_uid"],
    "nama": ["nama"],
    "jabatan": ["jabatan"],
    "lokasi": ["lokasi", "location", "site"],
    "tanggal_lahir": ["tanggal_lahir", "birthdate", "dob", "tgl_lahir"],
    # Manual MCU dates
    "tanggal_MCU": ["tanggal_mcu", "tgl_mcu", "mcu_date", "tanggal MCU"],
    "expired_MCU": ["expired_mcu", "mcu_expired", "expiry_date", "mcu_expiry", "expired MCU"],
    # Checkup/health metrics
    "tanggal_checkup": ["tanggal_checkup", "date", "checkup_date"],
    "umur": ["umur", "age"],
    "tinggi": ["tinggi", "tinggi_badan", "height", "tb"],
    "berat": ["berat", "berat_badan", "weight", "bb"],
    "lingkar_perut": ["lingkar_perut", "waist", "lp"],
    "bmi": ["bmi", "body_mass_index"],
    "bmi_category": ["bmi_category", "bmi_kategori", "kategori_bmi", "bmi category"],
    "gula_darah_puasa": ["gula_darah_puasa", "gdp", "blood_sugar_fasting"],
    "gula_darah_sewaktu": ["gula_darah_sewaktu", "gds", "blood_sugar_random"],
    "cholesterol": ["cholesterol", "kolesterol", "chol"],
    "tekanan_darah": ["tekanan_darah", "blood_pressure", "td", "tensi", "tekanan darah"],
    "asam_urat": ["asam_urat", "urat", "uric_acid"],
    "derajat_kesehatan": ["derajat_kesehatan", "derajat kesehatan", "derajat"],
    "keterangan": ["keterangan", "notes", "remark"],
}


def _map_extended_columns(df: pd.DataFrame):
    lower_cols = {c.lower().strip(): c for c in df.columns}
    normalized_to_original = { _normalize_header(c): c for c in df.columns }
    mapped = {}
    for db_col, aliases in EXTENDED_PREVIEW_COLUMNS.items():
        found = None
        for alias in aliases:
            key = alias.lower().strip()
            if key in lower_cols:
                found = lower_cols[key]
                break
        if found:
            mapped[db_col] = found
            continue
        # Fallback: token contains
        for header_norm, original in normalized_to_original.items():
            for alias in aliases:
                alias_norm = _normalize_header(alias)
                alias_tokens = set(alias_norm.split())
                header_tokens = set(header_norm.split())
                if alias_tokens.issubset(header_tokens):
                    found = original
                    break
            if found:
                break
        mapped[db_col] = found
    return mapped


def parse_master_preview(file_obj):
    """
    Read the uploaded Excel and return a DataFrame containing extended columns for display.
    - No auto-calculation for umur or BMI (uses values from Excel as-is)
    - Does not alter DB insert/update logic
    - Fills missing 'lokasi' with sheet name for display consistency
    """
    all_sheets = pd.read_excel(file_obj, sheet_name=None, dtype=str)

    frames = []
    for sheet_name, df in all_sheets.items():
        # Normalize original headers for mapping
        df.columns = df.columns.str.strip()
        mapping = _map_extended_columns(df)
        rename_dict = {v: k for k, v in mapping.items() if v}
        df = df.rename(columns=rename_dict)

        # Ensure lokasi filled for display
        if "lokasi" not in df.columns or df["lokasi"].isnull().all():
            df["lokasi"] = normalize_string(sheet_name)

        # Keep only known extended columns in a preferred order
        preferred_order = [
            "uid", "nama", "jabatan", "lokasi", "tanggal_lahir",
            "tanggal_MCU", "expired_MCU",
            "tanggal_checkup", "umur", "tinggi", "berat", "bmi", "bmi_category", "lingkar_perut",
            "gula_darah_puasa", "gula_darah_sewaktu", "cholesterol", "tekanan_darah", "asam_urat",
            "derajat_kesehatan", "keterangan",
        ]
        cols_present = [c for c in preferred_order if c in df.columns]
        df = df[cols_present]

        # Display-only: keep everything as strings, do not compute
        df = df.fillna("")
        frames.append(df)

    if frames:
        preview_df = pd.concat(frames, ignore_index=True)
    else:
        preview_df = pd.DataFrame(columns=[
            "uid", "nama", "jabatan", "lokasi", "tanggal_lahir",
            "tanggal_MCU", "expired_MCU",
            "tanggal_checkup", "umur", "tinggi", "berat", "bmi", "bmi_category", "lingkar_perut",
            "gula_darah_puasa", "gula_darah_sewaktu", "cholesterol", "tekanan_darah", "asam_urat",
            "derajat_kesehatan", "keterangan",
        ])

    return preview_df


def parse_checkup_anthropometric(file_obj):
    """
    Parse and save anthropometric checkup data (tinggi, berat, bmi) via Excel parser.
    - Maps extended columns and normalizes headers
    - Fills missing 'lokasi' with sheet name
    - Does not compute BMI; uses XLS-provided value as-is
    - Saves rows using insert_medical_checkup
    Returns dict with inserted count, skipped details, and inserted IDs.
    """
    all_sheets = pd.read_excel(file_obj, sheet_name=None, dtype=str)
    inserted = 0
    inserted_ids = []
    skipped = []

    for sheet_name, df in all_sheets.items():
        try:
            # Normalize original headers for mapping
            df.columns = df.columns.str.strip().str.lower()
            mapping = _map_extended_columns(df)
            rename_dict = {v: k for k, v in mapping.items() if v}
            # Fallback substring-based renaming to catch unit-suffixed headers
            auto_map = {}
            for col in df.columns:
                if col in rename_dict.values():
                    continue
                c = str(col).strip().lower().replace(' ', '_')
                if ('tinggi' in c) or ('height' in c) or c.startswith('tb'):
                    auto_map[col] = 'tinggi'
                elif ('berat' in c) or ('weight' in c) or c.startswith('bb'):
                    auto_map[col] = 'berat'
                elif ('bmi' in c) or ('imt' in c) or ('body_mass_index' in c):
                    auto_map[col] = 'bmi'
            if auto_map:
                df = df.rename(columns=auto_map)
            # Apply explicit mapping after fallback to ensure canonical keys
            df = df.rename(columns=rename_dict)

            # Ensure lokasi filled
            sheet_lokasi = normalize_string(sheet_name)
            if "lokasi" not in df.columns or df["lokasi"].isnull().all():
                df["lokasi"] = sheet_lokasi

            # Ensure tanggal_checkup; fall back to 'tanggal_MCU' if present
            if "tanggal_checkup" not in df.columns:
                if "tanggal_MCU" in df.columns:
                    df["tanggal_checkup"] = df["tanggal_MCU"]
                else:
                    df["tanggal_checkup"] = pd.Timestamp.today().date()

            # Type safety for dates (day-first) and normalize via safe_date
            for col in ["tanggal_lahir", "tanggal_checkup"]:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: safe_date(pd.to_datetime(x, dayfirst=True, errors="coerce")))

            # Clean anthropometric numerics
            for col in ["tinggi", "berat", "bmi"]:
                if col in df.columns:
                    df[col] = df[col].apply(safe_float)

            # No BMI auto-calculation; use XLS-provided value as-is

            # Determine UID mapping if not provided
            if "uid" not in df.columns:
                # Require at least nama and jabatan for mapping
                if not {"nama", "jabatan"}.issubset(df.columns):
                    skipped.append({"sheet": sheet_name, "row": "all", "reason": "Missing nama/jabatan for UID mapping"})
                    continue
                try:
                    # Normalize text keys to match master DB values
                    for col in ["nama", "jabatan", "lokasi"]:
                        if col in df.columns:
                            df[col] = df[col].apply(normalize_string)
                    uid_map = get_karyawan_uid_bulk(df)
                    def _map_uid(row):
                        key = (
                            row.get("nama"),
                            row.get("jabatan"),
                            row.get("lokasi"),
                            row.get("tanggal_lahir")
                        )
                        return uid_map.get(key)
                    df["uid"] = df.apply(_map_uid, axis=1)
                except Exception as e:
                    skipped.append({"sheet": sheet_name, "row": "all", "reason": f"UID mapping failed: {e}"})
                    continue

            # Iterate rows and insert
            for idx, row in df.iterrows():
                uid_val = row.get("uid")
                if not uid_val or str(uid_val).lower() == "nan":
                    skipped.append({"sheet": sheet_name, "row": idx + 2, "reason": "UID missing"})
                    continue
                try:
                    record = {
                        "uid_id": str(uid_val),  # pass FK raw ID for Checkup.uid
                        "tanggal_checkup": row.get("tanggal_checkup") or pd.Timestamp.today().date(),
                        "tanggal_lahir": row.get("tanggal_lahir"),
                        "umur": safe_float(row.get("umur")) if "umur" in df.columns else None,
                        "lokasi": row.get("lokasi") or sheet_lokasi,
                        # Anthropometrics
                        "tinggi": row.get("tinggi"),
                        "berat": row.get("berat"),
                        "bmi": row.get("bmi"),
                        # Optional baseline health grade
                        "derajat_kesehatan": row.get("derajat_kesehatan"),
                    }
                    obj = insert_medical_checkup(**record)
                    inserted_ids.append(obj.checkup_id)
                    inserted += 1
                except Exception as e:
                    skipped.append({"sheet": sheet_name, "row": idx + 2, "reason": str(e)})
        except Exception as e:
            skipped.append({"sheet": sheet_name, "row": "all", "reason": str(e)})
            continue

    return {"inserted": inserted, "skipped": skipped, "inserted_ids": inserted_ids}

