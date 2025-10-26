# core/helpers.py
from core.queries import get_employees, get_latest_medical_checkup
try:
    import pandas as pd
except Exception:
    pd = None

# ---------------------------
# Lokasi Helpers
# ---------------------------

def get_all_lokasi():
    """
    Return a list of all lokasi names.
    Prefer the Lokasi table if available; fallback to unique lokasi from employees.
    """
    try:
        # Prefer dedicated Lokasi table
        from core.core_models import Lokasi
        names = [row["nama"] for row in Lokasi.objects.all().values("nama")]
        if names:
            return sorted([str(n) for n in names if n is not None and str(n).strip()])
    except Exception:
        # If Lokasi table not available or any error occurs, fallback to employees
        pass

    # Fallback: derive unique lokasi from employees
    employees_df = get_employees()
    if employees_df is not None and not employees_df.empty and "lokasi" in employees_df.columns:
        return sorted(employees_df["lokasi"].dropna().unique().tolist())
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
        if getattr(df_safe[col], 'dtype', None) == 'object':
            df_safe[col] = df_safe[col].apply(lambda x: str(x) if x is not None else '')

        # Convert datetime/date objects to string
        try:
            if pd and pd.api.types.is_datetime64_any_dtype(df_safe[col]):
                # Format tanggal_checkup specifically as DD/MM/YY
                if col == 'tanggal_checkup':
                    df_safe[col] = df_safe[col].apply(lambda x: x.strftime('%d/%m/%y') if (pd and pd.notna(x)) else '')
                else:
                    df_safe[col] = df_safe[col].apply(lambda x: x.strftime('%Y-%m-%d') if (pd and pd.notna(x)) else '')
        except Exception:
            # Fallback: attempt formatting if values look like datetime
            try:
                if col == 'tanggal_checkup':
                    df_safe[col] = df_safe[col].apply(lambda x: x.strftime('%d/%m/%y') if hasattr(x, 'strftime') else (str(x) if x is not None else ''))
                else:
                    df_safe[col] = df_safe[col].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else (str(x) if x is not None else ''))
            except Exception:
                pass

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

# New helper: BMI category (display-only)
def compute_bmi_category(bmi_value):
    try:
        # Avoid pandas dependency; safely coerce to float
        bmi = float(bmi_value)
    except Exception:
        bmi = None
    if bmi is None:
        return None
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"

# ---------------------------
# Dashboard / Tab Helpers
# ---------------------------

def get_dashboard_checkup_data(employees_df=None, checkups_df=None):
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

        # Resolve duplicate columns introduced by merge
        # Prefer employee anthropometrics and umur; prefer checkup for lingkar_perut and tanggal_checkup
        prefer_employee_cols = ['bmi', 'bmi_category', 'tinggi', 'berat', 'umur']
        for col in prefer_employee_cols:
            x, y = f"{col}_x", f"{col}_y"
            if col not in df_combined.columns and (x in df_combined.columns or y in df_combined.columns):
                df_combined[col] = df_combined[x] if x in df_combined.columns else df_combined.get(y)
            drop_cols = []
            if x in df_combined.columns:
                drop_cols.append(x)
            if y in df_combined.columns:
                drop_cols.append(y)
            if drop_cols:
                df_combined = df_combined.drop(columns=drop_cols)

        prefer_checkup_cols = ['lingkar_perut', 'tanggal_checkup']
        for col in prefer_checkup_cols:
            x, y = f"{col}_x", f"{col}_y"
            if col not in df_combined.columns and (x in df_combined.columns or y in df_combined.columns):
                df_combined[col] = df_combined[y] if y in df_combined.columns else df_combined.get(x)
            drop_cols = []
            if x in df_combined.columns:
                drop_cols.append(x)
            if y in df_combined.columns:
                drop_cols.append(y)
            if drop_cols:
                df_combined = df_combined.drop(columns=drop_cols)

        # For tanggal_lahir, prefer employee (master) value
        tl_x, tl_y = 'tanggal_lahir_x', 'tanggal_lahir_y'
        if 'tanggal_lahir' not in df_combined.columns and (tl_x in df_combined.columns or tl_y in df_combined.columns):
            df_combined['tanggal_lahir'] = df_combined[tl_x] if tl_x in df_combined.columns else df_combined.get(tl_y)
        drop_cols = []
        if tl_x in df_combined.columns:
            drop_cols.append(tl_x)
        if tl_y in df_combined.columns:
            drop_cols.append(tl_y)
        if drop_cols:
            df_combined = df_combined.drop(columns=drop_cols)
        
        # Prefer checkup derajat_kesehatan; fallback to employee baseline
        dk_x, dk_y = 'derajat_kesehatan_x', 'derajat_kesehatan_y'
        if 'derajat_kesehatan' not in df_combined.columns and (dk_x in df_combined.columns or dk_y in df_combined.columns):
            if dk_y in df_combined.columns and dk_x in df_combined.columns:
                df_combined['derajat_kesehatan'] = df_combined[dk_y]
                mask = df_combined['derajat_kesehatan'].isna() | (df_combined['derajat_kesehatan'] == '')
                df_combined.loc[mask, 'derajat_kesehatan'] = df_combined[dk_x]
            else:
                df_combined['derajat_kesehatan'] = df_combined[dk_y] if dk_y in df_combined.columns else df_combined.get(dk_x)
        drop_cols = []
        if dk_x in df_combined.columns:
            drop_cols.append(dk_x)
        if dk_y in df_combined.columns:
            drop_cols.append(dk_y)
        if drop_cols:
            df_combined = df_combined.drop(columns=drop_cols)
        
        # Compute health status for employees with checkup data
        df_combined['status'] = df_combined.apply(compute_status, axis=1)

        # BMI category is provided by master XLS as 'bmi_category'
    
    # Only create empty medical columns if there's no checkup data
    if checkups_df.empty:
        empty_medical_cols = [
            'tanggal_checkup', 'tinggi', 'berat', 'bmi', 'bmi_category', 'lingkar_perut',
            'gula_darah_puasa', 'gula_darah_sewaktu', 'cholesterol', 'asam_urat',
            'tekanan_darah', 'derajat_kesehatan', 'umur', 'status', 'tanggal_MCU', 'expired_MCU'
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

    # Ensure placeholder columns for MCU display exist
    for col in ['tanggal_MCU', 'expired_MCU']:
        if col not in df_combined.columns:
            df_combined[col] = None

    # Format MCU dates consistently (dd/mm/yy) if present
    for col in ['tanggal_MCU', 'expired_MCU']:
        if col in df_combined.columns:
            try:
                df_combined[col] = pd.to_datetime(df_combined[col], errors='coerce').dt.strftime('%d/%m/%y')
            except Exception:
                # If conversion fails, leave values as-is
                pass

    # Reorder columns for clean dashboard display
    preferred_order = [
        'uid', 'nama', 'jabatan', 'lokasi', 'tanggal_lahir', 'umur',
        'tanggal_checkup', 'tinggi', 'berat', 'bmi', 'bmi_category', 'lingkar_perut',
        'gula_darah_puasa', 'gula_darah_sewaktu', 'cholesterol', 'asam_urat',
        'tekanan_darah', 'derajat_kesehatan', 'tanggal_MCU', 'expired_MCU', 'status', 'bulan', 'tahun'
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


# ---------------------------
# MCU Expiry Helpers
# ---------------------------

def get_mcu_expiry_alerts(window_days: int = 30) -> dict:
    """
    Compute MCU expiry alerts across all employees.
    Returns a dict with counts:
      - expired: expired before today
      - due_soon: expiring within next `window_days`
      - total: expired + due_soon
    """
    try:
        df = get_employees()
    except Exception:
        df = None

    if df is None or df.empty:
        return {"expired": 0, "due_soon": 0, "total": 0}

    # Parse expiry dates safely
    exp_series = pd.to_datetime(df.get('expired_MCU'), errors='coerce') if 'expired_MCU' in df.columns else pd.Series([])
    if exp_series is None or getattr(exp_series, 'empty', True):
        return {"expired": 0, "due_soon": 0, "total": 0}

    today = pd.Timestamp.today().normalize()
    window_end = today + pd.Timedelta(days=window_days)

    expired_mask = (exp_series < today) & exp_series.notna()
    due_soon_mask = (exp_series >= today) & (exp_series <= window_end) & exp_series.notna()

    expired_count = int(expired_mask.sum())
    due_soon_count = int(due_soon_mask.sum())

    return {
        "expired": expired_count,
        "due_soon": due_soon_count,
        "total": expired_count + due_soon_count,
    }

