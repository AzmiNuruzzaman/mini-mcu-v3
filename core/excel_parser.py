# core/excel_parser.py (V2)
import pandas as pd
import uuid
from core.core_models import Karyawan  # adjust import to your actual model
from utils.validators import normalize_string, validate_lokasi, safe_date

DB_COLUMNS = {
    "nama": ["nama"],
    "jabatan": ["jabatan"],
    "tanggal_lahir": ["tanggal_lahir", "tgl_lahir", "birthdate"]
}

MANDATORY_FIELDS_MASTER = ["nama", "jabatan"]

def map_columns(df: pd.DataFrame):
    """Map uploaded Excel columns to DB schema columns."""
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

def parse_master_karyawan(file_path):
    """
    Upload master karyawan data (V2):
    - Sheet name = lokasi
    - Columns: nama, jabatan, tanggal_lahir
    - tanggal_lahir optional
    - Insert/update into Karyawan DB
    """
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    total_inserted, total_skipped = 0, 0
    batch_id = str(uuid.uuid4())
    skipped_rows = []

    for sheet_name, sheet_df in all_sheets.items():
        # ✅ normalize column names to handle "Tanggal Lahir" → "tanggal_lahir"
        sheet_df.columns = sheet_df.columns.str.strip().str.lower().str.replace(' ', '_')

        lokasi = normalize_string(sheet_name)
        if not validate_lokasi(lokasi):
            # skip entire sheet if lokasi invalid
            total_skipped += len(sheet_df)
            skipped_rows.extend([(sheet_name, i, "Invalid lokasi") for i in range(len(sheet_df))])
            continue

        col_map = map_columns(sheet_df)
        rename_dict = {v: k for k, v in col_map.items() if v}
        sheet_df = sheet_df.rename(columns=rename_dict)

        # Keep only relevant columns
        cols_to_keep = [c for c in DB_COLUMNS.keys() if c in sheet_df.columns]
        sheet_df = sheet_df[cols_to_keep]

        # Drop rows missing mandatory fields
        for idx, row in sheet_df.iterrows():
            nama = normalize_string(row.get("nama"))
            jabatan = normalize_string(row.get("jabatan"))
            tanggal_lahir = safe_date(row.get("tanggal_lahir"))

            if not nama or not jabatan:
                total_skipped += 1
                skipped_rows.append((sheet_name, idx, "Missing nama or jabatan"))
                continue

            uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{nama}-{jabatan}"))

            try:
                Karyawan.objects.update_or_create(
                    uid=uid,
                    defaults={
                        "nama": nama,
                        "jabatan": jabatan,
                        "lokasi": lokasi,
                        "tanggal_lahir": tanggal_lahir,
                        "upload_batch_id": batch_id,
                    }
                )
                total_inserted += 1
            except Exception as e:
                total_skipped += 1
                skipped_rows.append((sheet_name, idx, str(e)))

    return {
        "inserted": total_inserted,
        "skipped": total_skipped,
        "batch_id": batch_id,
        "skipped_rows": skipped_rows
    }

