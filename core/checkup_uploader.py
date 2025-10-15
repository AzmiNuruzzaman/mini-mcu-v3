# core/checkup_uploader.py
import pandas as pd
import uuid
from utils.validators import normalize_string, safe_float, safe_date
from core.queries import get_employee_by_uid, insert_medical_checkup
from core.core_models import Karyawan

# -----------------------------
# Columns mapping (all V2 checkup_data fields)
# -----------------------------
CHECKUP_COLUMNS = {
    "uid": ["uid", "employee_id", "karyawan_uid"],
    "tanggal_checkup": ["tanggal_checkup", "date", "checkup_date"],
    "tanggal_lahir": ["tanggal_lahir", "birthdate", "dob", "tgl_lahir"],
    "umur": ["umur", "age"],
    "tinggi": ["tinggi", "tinggi_badan", "height", "tb"],
    "berat": ["berat", "berat_badan", "weight", "bb"],
    "lingkar_perut": ["lingkar_perut", "waist", "lp"],
    "bmi": ["bmi", "body_mass_index"],
    "gula_darah_puasa": ["gula_darah_puasa", "gdp", "blood_sugar_fasting"],
    "gula_darah_sewaktu": ["gula_darah_sewaktu", "gds", "blood_sugar_random"],
    "cholesterol": ["cholesterol", "kolesterol", "chol"],
    "asam_urat": ["asam_urat", "urat", "uric_acid"],
    "lokasi": ["lokasi", "location", "site"],
    "keterangan": ["keterangan", "notes", "remark"],
    "derajat_kesehatan": ["derajat_kesehatan", "derajat kesehatan", "derajat"],
}

MANDATORY_CHECKUP_FIELDS = ["uid", "tanggal_checkup"]

# -----------------------------
# Helpers
# -----------------------------
def map_checkup_columns(df: pd.DataFrame):
    lower_cols = {c.lower().strip(): c for c in df.columns}
    mapped = {}
    for db_col, aliases in CHECKUP_COLUMNS.items():
        for alias in aliases:
            if alias.lower().strip() in lower_cols:
                mapped[db_col] = lower_cols[alias.lower().strip()]
                break
        else:
            mapped[db_col] = None
    return mapped

# -----------------------------
# Main parser
# -----------------------------
def parse_checkup_xls(file_path):
    all_sheets = pd.read_excel(file_path, sheet_name=None, dtype=str)  # read all as str
    inserted = 0
    inserted_ids = []
    skipped = []

    for sheet_name, df in all_sheets.items():
        # Map columns using the defined mappings
        column_mapping = map_checkup_columns(df)
        
        # Rename columns based on mapping
        rename_dict = {v: k for k, v in column_mapping.items() if v is not None}
        df = df.rename(columns=rename_dict)
        
        # Check for required columns
        if 'uid' not in df.columns:
            skipped.append({'row': 'all', 'reason': 'Required column "uid" not found in sheet'})
            continue

        # Fill missing 'lokasi' with sheet name
        if 'lokasi' not in df.columns or df['lokasi'].isnull().all():
            df['lokasi'] = sheet_name

        # Fill missing 'tanggal_checkup' with today
        if 'tanggal_checkup' not in df.columns:
            df['tanggal_checkup'] = pd.Timestamp.today().date()

        # Clean UID
        df['uid'] = df['uid'].astype(str).str.strip()
        df = df[df['uid'].notna() & (df['uid'] != 'nan')]

        # Convert text columns
        for col in ['nama', 'jabatan', 'lokasi']:
            if col in df.columns:
                df[col] = df[col].apply(normalize_string)

        # Normalize derajat_kesehatan to uppercase P1..P7 without extra spaces
        if 'derajat_kesehatan' in df.columns:
            df['derajat_kesehatan'] = df['derajat_kesehatan'].astype(str).str.strip().str.upper()

        # Convert numeric fields
        numeric_cols = ['tinggi','berat','lingkar_perut','gula_darah_puasa','gula_darah_sewaktu',
                        'cholesterol','asam_urat','umur','bmi']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].str.replace(',', '.').apply(safe_float)

        # Convert dates
        for col in ['tanggal_lahir', 'tanggal_checkup']:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: safe_date(pd.to_datetime(x, dayfirst=True, errors='coerce')))

        # Iterate rows
        for idx, row in df.iterrows():
            row_dict = row.to_dict()
            uid = row_dict.get('uid')
            
            # Get Karyawan instance
            karyawan = Karyawan.objects.filter(uid=uid).first()
            if not karyawan:
                skipped.append({'row': idx+2, 'reason': 'UID not found in database'})
                continue

            try:
                tinggi_cm = row_dict.get('tinggi')
                berat = row_dict.get('berat')
                tinggi_m = (tinggi_cm / 100) if tinggi_cm else None
                bmi = round(berat / (tinggi_m ** 2), 2) if berat and tinggi_m else row_dict.get('bmi')

                checkup_data = {
                    'uid': karyawan,  # Pass Karyawan instance instead of UID string
                    'tanggal_checkup': row_dict.get('tanggal_checkup') or pd.Timestamp.today().date(),
                    'tanggal_lahir': row_dict.get('tanggal_lahir'),
                    'umur': row_dict.get('umur'),
                    'tinggi': tinggi_cm,
                    'berat': berat,
                    'lingkar_perut': row_dict.get('lingkar_perut'),
                    'bmi': bmi,
                    'gula_darah_puasa': row_dict.get('gula_darah_puasa'),
                    'gula_darah_sewaktu': row_dict.get('gula_darah_sewaktu'),
                    'cholesterol': row_dict.get('cholesterol'),
                    'asam_urat': row_dict.get('asam_urat'),
                    'lokasi': row_dict.get('lokasi') or sheet_name,
                    'derajat_kesehatan': row_dict.get('derajat_kesehatan'),
                }
                obj = insert_medical_checkup(**checkup_data)
                inserted_ids.append(obj.checkup_id)
                inserted += 1
            except Exception as e:
                skipped.append({'row': idx+2, 'reason': str(e)})

    return {'inserted': inserted, 'skipped': skipped, 'inserted_ids': inserted_ids}
