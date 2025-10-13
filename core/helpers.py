# core/helpers.py
from core.queries import get_employees, get_latest_medical_checkup
import pandas as pd

# ---------------------------
# Lokasi Helpers
# ---------------------------

def get_all_lokasi():
    """
    Return a list of all lokasi names in the database, sorted alphabetically.
    """
    employees_df = get_employees()
    if 'lokasi' in employees_df.columns:
        return sorted(employees_df['lokasi'].dropna().unique().tolist())
    return []

def validate_lokasi(lokasi_name: str) -> bool:
    """
    Check if the given lokasi is non-empty.
    Returns True if valid, False otherwise.
    """
    return bool(lokasi_name and lokasi_name.strip())

# ---------------------------
# DataFrame Helpers
# ---------------------------

def sanitize_df_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare DataFrame for display.
    Converts UUIDs, dates, and other non-serializable types to strings.
    """
    df_safe = df.copy()

    for col in df_safe.columns:
        # Convert UUID-like objects to string
        if df_safe[col].dtype == 'object':
            df_safe[col] = df_safe[col].apply(lambda x: str(x) if x is not None else '')

        # Convert datetime/date objects to string
        if pd.api.types.is_datetime64_any_dtype(df_safe[col]):
            df_safe[col] = df_safe[col].apply(lambda x: x.strftime('%Y-%m-%d') if pd.notna(x) else '')

    return df_safe

def compute_status(row):
    """
    Compute health status based on medical checkup values.
    Returns 'Unwell' if any values exceed thresholds, 'Well' otherwise.
    """
    if ((row.get("gula_darah_puasa", 0) > 120) or
        (row.get("gula_darah_sewaktu", 0) > 200) or
        (row.get("cholesterol", 0) > 240) or
        (row.get("asam_urat", 0) > 7) or
        (row.get("bmi", 0) >= 30)):
        return "Unwell"
    return "Well"

# ---------------------------
# Dashboard / Tab Helpers
# ---------------------------

def get_dashboard_checkup_data() -> pd.DataFrame:
    """
    Return the employee base data merged with their latest medical checkup data.
    """
    employees_df = get_employees()

    # Handle empty employee list
    if employees_df is None or employees_df.empty:
        return pd.DataFrame()

    # Initialize combined DataFrame with employee data
    df_combined = employees_df.copy()

    # Get latest checkup data for all employees
    checkups_df = get_latest_medical_checkup()
    
    # If we have checkup data, merge it with employee data
    if not checkups_df.empty:
        # Drop employee columns from checkups to avoid duplicates
        checkup_cols = [col for col in checkups_df.columns if col not in ['nama', 'jabatan', 'lokasi']]
        
        # Ensure we don't have duplicate uid columns
        if 'uid_id' in checkups_df.columns:
            checkups_df = checkups_df.rename(columns={'uid_id': 'uid'})
        
        # Ensure tanggal_checkup is datetime for proper sorting
        if 'tanggal_checkup' in checkups_df.columns:
            checkups_df['tanggal_checkup'] = pd.to_datetime(checkups_df['tanggal_checkup'], errors='coerce')
        
        # Deduplicate to keep only the latest checkup per uid
        if {'uid', 'tanggal_checkup'}.issubset(checkups_df.columns):
            checkups_df = (checkups_df
                           .sort_values(['uid', 'tanggal_checkup'], ascending=[True, False])
                           .drop_duplicates(subset=['uid'], keep='first'))
        
        # Select only needed columns from checkups
        checkups_df = checkups_df[['uid'] + [col for col in checkup_cols if col != 'uid']]
        
        # Merge employee data with checkup data
        df_combined = df_combined.merge(checkups_df, on='uid', how='left')
        
        # Compute health status for employees with checkup data
        df_combined['status'] = df_combined.apply(compute_status, axis=1)
    
    # Only create empty medical columns if there's no checkup data
    if checkups_df.empty:
        empty_medical_cols = [
            'tanggal_checkup', 'tinggi', 'berat', 'bmi', 'lingkar_perut',
            'gula_darah_puasa', 'gula_darah_sewaktu', 'cholesterol', 'asam_urat',
            'tekanan_darah', 'derajat_kesehatan', 'umur', 'status'
        ]
        for col in empty_medical_cols:
            if col not in df_combined.columns:
                df_combined[col] = None

    # Handle tanggal_lahir format if present (dd/mm/yy)
    if "tanggal_lahir" in df_combined.columns:
        df_combined["tanggal_lahir"] = pd.to_datetime(
            df_combined["tanggal_lahir"], errors="coerce"
        ).dt.strftime("%d/%m/%y")

    # Add month/year columns based on checkup dates if we have checkup data
    if not checkups_df.empty:
        df_combined['bulan'] = pd.to_datetime(df_combined['tanggal_checkup']).dt.month.fillna(0)
        df_combined['tahun'] = pd.to_datetime(df_combined['tanggal_checkup']).dt.year.fillna(0)
    else:
        df_combined['bulan'] = 0
        df_combined['tahun'] = 0

    # Reorder columns for clean dashboard display
    preferred_order = [
        'uid', 'nama', 'jabatan', 'lokasi', 'tanggal_lahir', 'umur',
        'tanggal_checkup', 'tinggi', 'berat', 'bmi', 'lingkar_perut',
        'gula_darah_puasa', 'gula_darah_sewaktu', 'cholesterol', 'asam_urat',
        'tekanan_darah', 'derajat_kesehatan', 'status', 'bulan', 'tahun'
    ]
    
    # Ensure all columns exist before reordering
    for col in preferred_order:
        if col not in df_combined.columns:
            df_combined[col] = None
            
    df_combined = df_combined.reindex(columns=preferred_order)

    return df_combined


def get_medical_checkups_by_uid(uid: str) -> pd.DataFrame:
    """
    Fetch all medical checkups for a given employee UID.
    Returns a DataFrame filtered for that UID only.
    """
    df = get_dashboard_checkup_data()
    if 'uid' in df.columns:
        df = df[df['uid'] == uid].copy()
    else:
        df = pd.DataFrame()
    return df

# ---------------------------
# Menu State Helper
# ---------------------------

def get_active_menu_for_view(view_name: str) -> str:
    """
    Map a view name to its sidebar menu key.
    Used to highlight the active menu and include the correct content.
    """
    mapping = {
        "dashboard": "dashboard",
        "user_management": "user",
        "qr_codes": "qr",
        "upload_master_karyawan_xls": "data",
        "data_management": "data",
        "edit_karyawan": "edit",
    }
    return mapping.get(view_name, "")

