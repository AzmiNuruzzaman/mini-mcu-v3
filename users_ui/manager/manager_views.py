# users_interface/manager/manager_views.py
import io
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
try:
    import pandas as pd
except Exception:
    pd = None
from datetime import datetime
from django.conf import settings
import base64
from users_ui.qr.qr_utils import generate_qr_bytes
import uuid
import os
from utils.validators import safe_date, validate_lokasi, normalize_string, safe_float

from core.queries import (
    get_users,
    add_user,
    get_employees,
    add_employee_if_exists,
    reset_karyawan_data,
    get_employee_by_uid,
    get_medical_checkups_by_uid,
    insert_medical_checkup,
    save_manual_karyawan_edits,
    get_latest_medical_checkup,
    delete_user_by_id,
    count_users_by_role,
    reset_user_password as core_reset_user_password,
    get_user_by_username,
    change_username as core_change_username,
    write_checkup_upload_log,
    get_checkup_upload_history,
    load_checkups,
    get_manual_input_logs,
    write_manual_input_log,
)

from core.helpers import (
    get_all_lokasi,
    sanitize_df_for_display,
    get_dashboard_checkup_data,
    get_active_menu_for_view,
    compute_status,
)

import plotly.graph_objects as go
import plotly.io as pio
from core import excel_parser, checkup_uploader
from utils.export_utils import generate_karyawan_template_excel, export_checkup_data_excel as build_checkup_excel, export_checkup_data_pdf as build_checkup_pdf
from users_ui.qr.qr_views import qr_detail_view, qr_bulk_download_view

# -------------------------
# Tab 1: Dashboard
# -------------------------
def dashboard(request):
    """
    Manager dashboard showing:
    - Total users by role
    - Recent medical checkups
    - Quick stats
    """
    if not request.session.get("authenticated") or request.session.get("user_role") not in ["Manager", "Tenaga Kesehatan"]:
        return redirect("accounts:login")

    active_menu = "dashboard"  # Changed to match the mapping in get_active_menu_for_view
    active_submenu = request.GET.get('submenu', 'data')
    # Path-based override to allow nurse routes to open grafik tabs directly
    path_str = request.path or ''
    forced_subtab = None
    if 'grafik/kesehatan' in path_str or 'dashboard/grafik/kesehatan' in path_str:
        active_submenu = 'grafik'
        forced_subtab = 'grafik_kesehatan'
    elif 'grafik/well_unwell' in path_str or 'dashboard/grafik/well_unwell' in path_str:
        active_submenu = 'grafik'
        forced_subtab = 'well_unwell'

    # [DEBUG] STEP 3 — Backend parameter trace
    try:
        print("[DEBUG] Incoming GET params:", request.GET)
    except Exception:
        pass
    try:
        lokasi_filter = request.GET.get("lokasi", "").strip()
        print("[DEBUG] lokasi_filter value:", lokasi_filter)
    except Exception:
        pass
    
    # Grafik JSON API: return processed data for chart overhaul
    if active_submenu == 'grafik' and request.GET.get('grafik_json') == '1':
        # Build JSON payload based on month range and UID filters
        try:
            df_json = load_checkups()
        except Exception:
            df_json = pd.DataFrame()
        # Fallback to latest dashboard data if historical checkups are unavailable
        if not hasattr(df_json, 'empty') or df_json.empty:
            try:
                df_json = get_dashboard_checkup_data()
            except Exception:
                df_json = pd.DataFrame()
        now = pd.Timestamp.now()
        default_end_month_dt = pd.Timestamp(year=now.year, month=now.month, day=1)
        default_start_month_dt = default_end_month_dt - pd.offsets.DateOffset(months=5)
        # Choose date column (fallback to synthetic current month if absent)
        date_col = None
        if not df_json.empty and 'tanggal_MCU' in df_json.columns:
            # Robust parse: handle day-first and common dd/mm/yy formats
            df_json['tanggal_MCU_raw'] = df_json['tanggal_MCU']
            df_json['tanggal_MCU'] = pd.to_datetime(df_json['tanggal_MCU'], errors='coerce', dayfirst=True)
            if df_json['tanggal_MCU'].isna().all():
                df_json['tanggal_MCU'] = pd.to_datetime(df_json['tanggal_MCU_raw'], format='%d/%m/%y', errors='coerce')
            date_col = 'tanggal_MCU'
        elif not df_json.empty and 'tanggal_checkup' in df_json.columns:
            df_json['tanggal_checkup'] = pd.to_datetime(df_json['tanggal_checkup'], errors='coerce', dayfirst=True)
            date_col = 'tanggal_checkup'
        else:
            # Synthesize a month column using current month so aggregated view still works
            df_json = df_json.copy()
            df_json['synthetic_month'] = now.strftime('%Y-%m')
        # Ensure status
        try:
            if 'status' not in df_json.columns or df_json['status'].isna().any():
                df_json['status'] = df_json.apply(compute_status, axis=1)
        except Exception:
            df_json['status'] = df_json.get('status', '')
        # Filters
        uid = request.GET.get('uid', 'all')
        start_month = request.GET.get('start_month', '')
        end_month = request.GET.get('end_month', '')
        start_dt = pd.to_datetime(start_month + '-01', errors='coerce') if start_month else default_start_month_dt
        end_dt = pd.to_datetime(end_month + '-01', errors='coerce') if end_month else default_end_month_dt
        end_dt_end = (end_dt + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
        df_filt = df_json.copy()
        df_filt = df_filt.dropna(subset=[date_col])
        df_filt = df_filt[(df_filt[date_col] >= start_dt) & (df_filt[date_col] <= end_dt_end)]
        if uid and uid != 'all':
            df_uid = df_filt[df_filt['uid'].astype(str) == str(uid)].copy().sort_values(by=[date_col])
            def to_float_safe(val):
                try:
                    return float(val)
                except Exception:
                    return None
            def parse_systolic(val):
                if pd.isna(val):
                    return None
                s = str(val)
                if '/' in s:
                    try:
                        return float(s.split('/')[0])
                    except Exception:
                        return None
                try:
                    return float(s)
                except Exception:
                    return None
            if df_uid.empty:
                x_dates = []
                series = {}
                summary = {'total_employees':0,'well_count':0,'unwell_count':0}
            else:
                x_dates = df_uid[date_col].dt.strftime('%Y-%m-%d').fillna('').tolist()
                series = {
                    'gula_darah_puasa': df_uid.get('gula_darah_puasa', pd.Series([None]*len(df_uid))).apply(to_float_safe).tolist(),
                    'gula_darah_sewaktu': df_uid.get('gula_darah_sewaktu', pd.Series([None]*len(df_uid))).apply(to_float_safe).tolist(),
                    'tekanan_darah_sistole': df_uid.get('tekanan_darah', pd.Series([None]*len(df_uid))).apply(parse_systolic).tolist(),
                    'lingkar_perut': df_uid.get('lingkar_perut', pd.Series([None]*len(df_uid))).apply(to_float_safe).tolist(),
                    'cholesterol': df_uid.get('cholesterol', pd.Series([None]*len(df_uid))).apply(to_float_safe).tolist(),
                    'asam_urat': df_uid.get('asam_urat', pd.Series([None]*len(df_uid))).apply(to_float_safe).tolist(),
                }
                latest_row = df_uid.iloc[-1]
                latest_status = latest_row.get('status')
                summary = {
                    'total_employees': 1,
                    'well_count': 1 if latest_status == 'Well' else 0,
                    'unwell_count': 1 if latest_status == 'Unwell' else 0,
                }
            return JsonResponse({'mode':'individual','x_dates':x_dates,'series':series,'summary':summary})
        else:
            if df_filt.empty:
                # If no filtered historical data, fall back to current latest data grouped into the current month
                months_sorted = [now.strftime('%Y-%m')]
                try:
                    latest_df = get_dashboard_checkup_data()
                    latest_df = latest_df.copy()
                    if 'status' not in latest_df.columns:
                        latest_df['status'] = latest_df.apply(compute_status, axis=1)
                    total_employees = int(latest_df['uid'].nunique()) if not latest_df.empty else 0
                    well_count = int((latest_df['status'] == 'Well').sum()) if not latest_df.empty else 0
                    unwell_count = int((latest_df['status'] == 'Unwell').sum()) if not latest_df.empty else 0
                    return JsonResponse({'mode':'aggregate','months':months_sorted,'well':[well_count],'unwell':[unwell_count],'summary':{'total_employees':total_employees,'well_count':well_count,'unwell_count':unwell_count}})
                except Exception:
                    return JsonResponse({'mode':'aggregate','months':[],'well':[],'unwell':[],'summary':{'total_employees':0,'well_count':0,'unwell_count':0}})
            df_filt['month'] = (df_filt[date_col].dt.to_period('M').astype(str) if date_col else df_filt.get('synthetic_month', now.strftime('%Y-%m')))
            df_filt = df_filt.sort_values(by=['uid'] + ([date_col] if date_col else []))
            latest_per_uid_month = df_filt.groupby(['month','uid']).tail(1)
            monthly_counts = latest_per_uid_month.groupby(['month','status']).size().reset_index(name='count')
            months_sorted = sorted(monthly_counts['month'].unique())
            well_counts = []
            unwell_counts = []
            for m in months_sorted:
                sub = monthly_counts[monthly_counts['month'] == m]
                well_counts.append(int(sub[sub['status'] == 'Well']['count'].sum()))
                unwell_counts.append(int(sub[sub['status'] == 'Unwell']['count'].sum()))
            latest_per_uid_range = df_filt.groupby('uid').tail(1)
            total_employees = int(latest_per_uid_range['uid'].nunique()) if not latest_per_uid_range.empty else 0
            well_count = int((latest_per_uid_range['status'] == 'Well').sum()) if not latest_per_uid_range.empty else 0
            unwell_count = int((latest_per_uid_range['status'] == 'Unwell').sum()) if not latest_per_uid_range.empty else 0
            return JsonResponse({'mode':'aggregate','months':months_sorted,'well':well_counts,'unwell':unwell_counts,'summary':{'total_employees':total_employees,'well_count':well_count,'unwell_count':unwell_count}})

    # Get the default dashboard dataset (latest checkup per employee)
    df_latest = get_dashboard_checkup_data()

    # Month range filter for Data Karyawan (table & stats)
    start_month = request.GET.get('start_month', '').strip()
    end_month = request.GET.get('end_month', '').strip()
    df = df_latest.copy()
    if start_month and end_month:
        try:
            # Load full historical checkups
            hist = load_checkups()
        except Exception:
            hist = None
        try:
            import pandas as _pd
            if hist is not None and hasattr(hist, 'empty') and not hist.empty:
                # Parse dates
                if 'tanggal_checkup' in hist.columns:
                    hist['tanggal_checkup'] = _pd.to_datetime(hist['tanggal_checkup'], errors='coerce', dayfirst=True)
                # Compute status if missing
                try:
                    if 'status' not in hist.columns or hist['status'].isna().any():
                        hist['status'] = hist.apply(compute_status, axis=1)
                except Exception:
                    hist['status'] = hist.get('status', '')

                # Build date range
                start_dt = _pd.to_datetime(start_month + '-01', errors='coerce')
                end_dt = _pd.to_datetime(end_month + '-01', errors='coerce')
                # Inclusive to end of month
                if _pd.notnull(end_dt):
                    end_dt_end = (end_dt + _pd.offsets.MonthBegin(1)) - _pd.Timedelta(days=1)
                else:
                    end_dt_end = end_dt

                # Filter within range
                if _pd.notnull(start_dt):
                    hist = hist[hist['tanggal_checkup'] >= start_dt]
                if _pd.notnull(end_dt_end):
                    hist = hist[hist['tanggal_checkup'] <= end_dt_end]

                # Latest checkup per uid within range
                if not hist.empty and 'uid' in hist.columns:
                    hist = hist.sort_values(by=['uid', 'tanggal_checkup'])
                    latest_in_range = hist.groupby('uid').tail(1).set_index('uid')
                    # Columns to overwrite from historical latest
                    check_cols = [
                        'tanggal_checkup','tinggi','berat','lingkar_perut','bmi','umur',
                        'gula_darah_puasa','gula_darah_sewaktu','cholesterol','asam_urat',
                        'tekanan_darah','derajat_kesehatan','status','tanggal_MCU','expired_MCU','bmi_category'
                    ]
                    for col in check_cols:
                        if col not in df.columns:
                            df[col] = None
                    # Blank out existing checkup-related fields (so only range data shows)
                    df[check_cols] = None
                    # Apply latest-in-range values per uid
                    for uid, row in latest_in_range.iterrows():
                        if 'uid' not in df.columns:
                            continue
                        # Find indices of this uid in df
                        idxs = df.index[df['uid'].astype(str) == str(uid)].tolist()
                        if not idxs:
                            continue
                        for idx in idxs:
                            for col in check_cols:
                                if col in latest_in_range.columns:
                                    df.at[idx, col] = row.get(col, None)
        except Exception:
            # If anything goes wrong, df remains as latest
            pass

    # Ensure expected columns exist to avoid KeyError after backup restores
    for col in ['lokasi', 'status', 'nama', 'jabatan']:
        if col not in df.columns:
            df[col] = ''

    # Normalize 'jabatan' to remove duplicates caused by spacing/casing differences
    if not df.empty and 'jabatan' in df.columns:
        df['jabatan_clean'] = df['jabatan'].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
        df['jabatan_key'] = df['jabatan_clean'].str.lower()
    else:
        df['jabatan_clean'] = ''
        df['jabatan_key'] = ''
    
    # Get all available locations before filtering (exclude empty values)
    try:
        emps_df = get_employees()
        all_lokasi = sorted([loc for loc in emps_df['lokasi'].dropna().unique().tolist() if str(loc).strip()]) if hasattr(emps_df, 'empty') and not emps_df.empty else []
    except Exception:
        all_lokasi = sorted([loc for loc in df['lokasi'].dropna().unique().tolist() if str(loc).strip()])
    
    # Make an unfiltered copy for card totals (keep cards constant when filters change)
    df_all = df.copy()
    
    # Get filter parameters
    filters = {
        'nama': request.GET.get('nama', ''),
        'jabatan': request.GET.get('jabatan', ''),
        'lokasi': request.GET.get('lokasi', ''),  # Single location selection
        'status': request.GET.get('status', ''),  # Well/Unwell
        'expiry': request.GET.get('expiry', ''),  # Expiry warning toggle (≤60 hari)
        'start_month': start_month,
        'end_month': end_month,
    }
    
    # Apply filters
    if filters['nama']:
        df = df[df['nama'].astype(str).str.contains(filters['nama'], case=False, na=False)]
    if filters['jabatan']:
        # Normalize filter to match jabatan_key
        filt_clean = ' '.join(filters['jabatan'].split()).strip().lower()
        df = df[df['jabatan_key'] == filt_clean]
    if filters['lokasi']:  # Filter by selected location
        df = df[df['lokasi'] == filters['lokasi']]
    if filters['status']:  # Filter by Well/Unwell status
        df = df[df['status'] == filters['status']]
    # Compute MCU expiry flags for styling and filtering
    try:
        if 'expired_MCU' in df.columns:
            expired_dt = pd.to_datetime(df['expired_MCU'], format='%d/%m/%y', errors='coerce')
            today = pd.Timestamp.today().normalize()
            warn_deadline = today + pd.Timedelta(days=60)
            df['mcu_is_expired'] = expired_dt.notna() & (expired_dt < today)
            df['mcu_is_warning'] = expired_dt.notna() & (expired_dt >= today) & (expired_dt <= warn_deadline)
        else:
            df['mcu_is_expired'] = False
            df['mcu_is_warning'] = False
    except Exception:
        df['mcu_is_expired'] = False
        df['mcu_is_warning'] = False
    # Apply expiry warning filter (checkbox toggles only warnings)
    if filters.get('expiry'):
        val = str(filters['expiry']).lower()
        if val == 'expired':
            df = df[df['mcu_is_expired']]
        else:
            df = df[df['mcu_is_warning']]
    
    # Get unique values for dropdowns from filtered data
    # Build a mapping of normalized key -> cleaned display value to dedupe case/spacing
    jabatan_map = {}
    if not df.empty and 'jabatan_key' in df.columns and 'jabatan_clean' in df.columns:
        for key, val in zip(df['jabatan_key'], df['jabatan_clean']):
            if key and key not in jabatan_map:
                jabatan_map[key] = val
    available_jabatan = sorted(jabatan_map.values())
    # Use all locations for lokasi dropdown
    available_lokasi = all_lokasi
    # Status options are fixed
    available_status = ['Well', 'Unwell']
    
    # Calculate Well/Unwell counts from filtered data (only rows with a checkup/status)
    total_karyawan = int(df_all['uid'].nunique()) if not df_all.empty else 0
    total_well = int((df['status'] == 'Well').sum()) if not df.empty else 0
    total_unwell = int((df['status'] == 'Unwell').sum()) if not df.empty else 0
    
    # Pagination
    items_per_page = 10
    total_items = len(df)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    current_page = int(request.GET.get('page', 1))
    current_page = max(1, min(current_page, total_pages))  # Ensure page is within bounds
    
    start_index = (current_page - 1) * items_per_page
    end_index = start_index + items_per_page
    
    # Slice the DataFrame for current page
    df_page = df.iloc[start_index:end_index]
    # Sanitize page slice to avoid NaT/UUID issues in templates
    try:
        df_page = sanitize_df_for_display(df_page)
    except Exception:
        pass
    
    # Convert DataFrame to list of dictionaries for template
    employees = df_page.to_dict('records')
    
    # Get dashboard statistics
    users_df = get_users()
    checkups_today = 0  # Will be updated when checkup data is uploaded
    active_nurses = len(users_df[users_df['role'] == 'nurse']) if not users_df.empty else 0
    pending_reviews = 0  # Will be updated when checkup data is uploaded

    # Legacy grafik server-rendered code removed. Client-side Plotly fetch + render is now used via JSON API.
    
    # Initialize chart placeholders
    checkup_dates = []
    checkup_counts = []
    # Department counts for donut/bar (existing)
    dept_names = []
    dept_counts = []
    if not df.empty and 'jabatan' in df.columns:
        dept_counts_series = df['jabatan'].value_counts()
        dept_names = dept_counts_series.index.tolist()
        dept_counts = dept_counts_series.values.tolist()
    
    # Compute latest upload info for tooltip
    latest_check_date_disp = None
    if 'tanggal_checkup' in df_all.columns and not df_all.empty:
        dt_series = pd.to_datetime(df_all['tanggal_checkup'], errors='coerce')
        dt_max = dt_series.max()
        # Format date as dd/mm/yy per request
        latest_check_date_disp = dt_max.strftime('%d/%m/%y') if pd.notnull(dt_max) else None
    try:
        hist_df = get_checkup_upload_history()
        if hasattr(hist_df, 'empty') and not hist_df.empty:
            latest = hist_df.iloc[0]
            ts_val = latest.get('timestamp', None)
            # Format timestamp as dd/mm/yy HH:MM per request
            ts_disp = ts_val.strftime('%d/%m/%y %H:%M') if pd.notnull(ts_val) else '-'
            filename = latest.get('filename', '')
            inserted = int(latest.get('inserted', 0))
            skipped = int(latest.get('skipped_count', 0))
            if start_month and end_month:
                # Show selected range
                latest_checkup_display = f"Range {start_month} s/d {end_month} • {filename} • Inserted: {inserted} • Skipped: {skipped}"
            elif latest_check_date_disp:
                latest_checkup_display = f"{latest_check_date_disp} • {filename} • Inserted: {inserted} • Skipped: {skipped}"
            else:
                latest_checkup_display = f"{ts_disp} • {filename} • Inserted: {inserted} • Skipped: {skipped}"
        else:
            latest_checkup_display = latest_check_date_disp
    except Exception:
        latest_checkup_display = latest_check_date_disp
    
    # Grafik filter defaults and UID options
    available_uids = []
    try:
        # Prefer historical checkups dataset
        all_checkups_df_for_uids = load_checkups()
        if hasattr(all_checkups_df_for_uids, 'empty') and not all_checkups_df_for_uids.empty and 'uid' in all_checkups_df_for_uids.columns:
            available_uids = [str(u) for u in all_checkups_df_for_uids['uid'].dropna().unique().tolist()]
    except Exception:
        pass
    # Fallbacks if none found
    if not available_uids:
        try:
            df_latest = get_dashboard_checkup_data()
            if hasattr(df_latest, 'empty') and not df_latest.empty and 'uid' in df_latest.columns:
                available_uids = [str(u) for u in df_latest['uid'].dropna().unique().tolist()]
        except Exception:
            pass
    if not available_uids:
        try:
            df_emps = get_employees()
            if hasattr(df_emps, 'empty') and not df_emps.empty and 'uid' in df_emps.columns:
                available_uids = [str(u) for u in df_emps['uid'].dropna().unique().tolist()]
        except Exception:
            pass
    available_uids = sorted(set(available_uids))
    now2 = pd.Timestamp.now()
    default_end_month = now2.strftime('%Y-%m')
    default_start_month = (now2 - pd.offsets.DateOffset(months=5)).strftime('%Y-%m')

    # Grafik subtab simplified for Vue-based Grafik (legacy Plotly subtabs removed)
    grafik_subtab = 'grafik' if active_submenu == 'grafik' else None
    grafik_start_month = request.GET.get('start_month', default_start_month)
    grafik_end_month = request.GET.get('end_month', default_end_month)

    context = {
        'active_menu': active_menu,
        'active_submenu': active_submenu,
        'employees': employees,
        'total_karyawan': total_items,
        'total_well': total_well,
        'total_unwell': total_unwell,
        'current_page': current_page,
        'total_pages': total_pages,
        'start_index': start_index,
        'filters': filters,
        'available_jabatan': available_jabatan,
        'available_lokasi': available_lokasi,
        'available_status': available_status,  # Add status options to context
        'checkups_today': checkups_today,
        'active_nurses': active_nurses,
        'pending_reviews': pending_reviews,
        'checkup_dates': checkup_dates,
        'checkup_counts': checkup_counts,
        'dept_names': dept_names,
        'dept_counts': dept_counts,
        'latest_checkup_display': latest_checkup_display,
        'available_uids': available_uids,
        'default_start_month': default_start_month,
        'default_end_month': default_end_month,
        # Grafik context
        'grafik_subtab': grafik_subtab,
        'grafik_start_month': grafik_start_month,
        'grafik_end_month': grafik_end_month,
    }

    # Legacy server-rendered Plotly grafik removed. Vue-based GrafikManager handles rendering.
    context['grafik_chart_html'] = None

    # Upload History context
    if active_submenu == 'upload_history':
        try:
            hist_df = get_checkup_upload_history()
            upload_history = hist_df.to_dict('records') if hasattr(hist_df, 'empty') and not hist_df.empty else []
        except Exception:
            upload_history = []
        context['upload_history'] = upload_history
        context['MEDIA_URL'] = settings.MEDIA_URL

    # Success/Error notifications
    success_message = request.session.pop('success_message', None)
    error_message = request.session.pop('error_message', None)
    if success_message:
        context['success_message'] = success_message
    if error_message:
        context['error_message'] = error_message
    
    return render(request, 'manager/dashboard.html', context)

# -------------------------
# Tab 2: User Management
# -------------------------
def add_new_user(request):
    """Add new user form and list."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        role = request.POST.get("role")
        
        try:
            # Normalize role values from form to canonical names
            role_map = {
                "manager": "Manager",
                "Manager": "Manager",
                "nurse": "Tenaga Kesehatan",
                "Tenaga Kesehatan": "Tenaga Kesehatan",
            }
            canonical_role = role_map.get(role)
            if not username or not password or not canonical_role:
                request.session['error_message'] = "Username, password, dan role valid diperlukan."
            else:
                add_user(username, password, canonical_role)
                request.session['success_message'] = f"User {username} added successfully"
        except Exception as e:
            request.session['error_message'] = f"Failed to add user: {e}"
        
        # Redirect preserving submenu to Add/Remove
        return redirect(reverse("manager:user_management") + "?submenu=add_remove")

    # Fetch all users
    users_df = get_users()
    
    # Map DB role names to simplified keys
    users_df['role_key'] = users_df['role'].str.lower().replace({
        'manager': 'manager',
        'tenaga kesehatan': 'nurse'
    })
    
    # Filter only manager and nurse users
    filtered_users = users_df[users_df['role_key'].isin(['manager', 'nurse'])]

    # Determine submenu selection
    active_submenu = request.GET.get('submenu', 'add_remove')

    context = {
        "users": filtered_users.to_dict('records'),
        "active_menu": "user",
        "active_submenu": active_submenu,
    }
    
    return render(request, "manager/user_management.html", context)

def remove_user(request, user_id):
    try:
        delete_user_by_id(user_id)
        request.session['success_message'] = "User removed successfully"
    except Exception as e:
        request.session['error_message'] = f"Failed to remove user: {e}"
    
    return redirect(reverse("manager:user_management") + "?submenu=add_remove")

@require_http_methods(["POST"])
def update_user_role(request, user_id):
    """Update user role from Manage Roles submenu."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    new_role = request.POST.get('role')
    try:
        from core.core_models import User
        from core.queries import count_users_by_role
        user = User.objects.get(id=user_id)

        # Enforce caps when promoting to Manager or Tenaga Kesehatan
        if new_role == "Manager" and count_users_by_role("Manager") >= 5 and user.role != "Manager":
            request.session['error_message'] = "Limit akun Manager sudah 5. Tidak dapat mempromosikan lagi."
            return redirect(reverse("manager:user_management") + "?submenu=manage_roles")
        if new_role == "Tenaga Kesehatan" and count_users_by_role("Tenaga Kesehatan") >= 10 and user.role != "Tenaga Kesehatan":
            request.session['error_message'] = "Limit akun Tenaga Kesehatan sudah 10. Tidak dapat mempromosikan lagi."
            return redirect(reverse("manager:user_management") + "?submenu=manage_roles")

        user.role = new_role
        user.save()
        request.session['success_message'] = "Role updated"
    except Exception as e:
        request.session['error_message'] = f"Failed to update role: {e}"
    
    return redirect(reverse("manager:user_management") + "?submenu=manage_roles")

@require_http_methods(["POST"]) 
def change_username(request, user_id):
    """Change a user's username from Add/Remove submenu."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    new_username = request.POST.get("new_username")
    try:
        from core.core_models import User
        user = User.objects.get(id=user_id)
        old_username = user.username
        core_change_username(old_username, new_username)
        # If the manager is renaming their own account, update the session immediately
        current_username = request.session.get("username") or getattr(getattr(request, "user", None), "username", None)
        if current_username == old_username:
            request.session["username"] = new_username
        # Migrate existing avatar files from old username to new username across known roles
        try:
            avatar_root = os.path.join(settings.MEDIA_ROOT, "avatars")
            for sub in ["manager", "nurse"]:
                dir_path = os.path.join(avatar_root, sub)
                if os.path.isdir(dir_path):
                    for ext in ["jpg", "jpeg", "png", "webp", "gif"]:
                        old_path = os.path.join(dir_path, f"{old_username}.{ext}")
                        if os.path.exists(old_path):
                            new_path = os.path.join(dir_path, f"{new_username}.{ext}")
                            try:
                                os.replace(old_path, new_path)
                            except Exception:
                                pass
                            break
        except Exception:
            # Non-fatal: avatar migration failures shouldn't block username change
            pass
        request.session['success_message'] = "Username berhasil diubah"
    except Exception as e:
        request.session['error_message'] = f"Gagal mengubah username: {e}"

    return redirect(reverse("manager:user_management") + "?submenu=add_remove")

@require_http_methods(["POST"])
def reset_user_password(request, user_id):
    """Reset a user's password from Add/Remove submenu."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    new_password = request.POST.get("new_password")
    try:
        from core.core_models import User
        user = User.objects.get(id=user_id)
        if not new_password or not str(new_password).strip():
            raise ValueError("Password baru tidak boleh kosong.")
        core_reset_user_password(user.username, new_password)
        request.session['success_message'] = "Password berhasil direset"
    except Exception as e:
        request.session['error_message'] = f"Gagal mereset password: {e}"

    return redirect(reverse("manager:user_management") + "?submenu=add_remove")

# -------------------------
# Avatar Upload (Manager)
# -------------------------
@require_http_methods(["POST"])
def upload_avatar(request):
    # Only Manager can upload own avatar
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    file = request.FILES.get("avatar")
    if not file:
        request.session["error_message"] = "Tidak ada file yang diunggah."
        return redirect(reverse("manager:dashboard"))

    # Validate content type and size (max 2MB)
    allowed_types = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    content_type = getattr(file, "content_type", "")
    ext = allowed_types.get(content_type)
    if not ext:
        request.session["error_message"] = "Tipe file tidak didukung. Gunakan JPG, PNG, WEBP, atau GIF."
        return redirect(reverse("manager:dashboard"))
    max_size = 2 * 1024 * 1024
    if getattr(file, "size", 0) > max_size:
        request.session["error_message"] = "Ukuran file terlalu besar (maks 2MB)."
        return redirect(reverse("manager:dashboard"))

    # Determine username
    username = request.session.get("username") or getattr(getattr(request, "user", None), "username", None)
    if not username:
        request.session["error_message"] = "Tidak dapat menentukan pengguna untuk avatar."
        return redirect(reverse("manager:dashboard"))

    # Prepare directories
    target_dir = os.path.join(settings.MEDIA_ROOT, "avatars", "manager")
    os.makedirs(target_dir, exist_ok=True)

    # Remove existing avatars for this user across supported extensions
    for old_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
        old_path = os.path.join(target_dir, f"{username}.{old_ext}")
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass

    # Save new file
    target_path = os.path.join(target_dir, f"{username}.{ext}")
    try:
        with open(target_path, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)
        request.session["success_message"] = "Foto profil berhasil diperbarui."
    except Exception as e:
        request.session["error_message"] = f"Gagal menyimpan avatar: {e}"

    return redirect(reverse("manager:dashboard"))

# -------------------------
# Tab 3: QR Codes
# -------------------------
def qr_manager_interface(request):
    """QR code generation interface."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    
    # Get all employees from database and convert to list of dicts
    employees_df = get_employees()
    
    # Check if DataFrame is empty or doesn't have required columns
    if employees_df is None or employees_df.empty or not all(col in employees_df.columns for col in ['uid', 'nama']):
        employees = []
    else:
        employees = employees_df.to_dict('records')
    
    # Handle bulk export
    if request.GET.get("bulk") == "1":
        return qr_bulk_download_view(request)
    
    context = {
        "employees": employees,
        "active_menu": "qr",
    }
    
    # Handle inline single QR preview
    uid = request.GET.get("uid")
    if uid:
        # Find selected employee
        selected = None
        for emp in employees:
            if str(emp.get('uid')) == str(uid):
                selected = emp
                break
        
        if selected:
            # Build QR URL
            from django.utils.http import urlencode
            server_url = getattr(settings, "APP_BASE_URL", os.getenv("APP_BASE_URL", "")) or request.build_absolute_uri("/").rstrip("/")
            qr_url = f"{server_url}/karyawan/?uid={selected['uid']}"
            # Generate QR bytes and base64
            qr_bytes = generate_qr_bytes(qr_url)
            qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
            context.update({
                "selected_name": selected.get('nama'),
                "selected_uid": selected.get('uid'),
                "qr_base64": qr_base64,
            })
        else:
            context.update({
                "error": "UID karyawan tidak ditemukan.",
            })
    
    return render(request, "manager/qr_codes.html", context)

# -------------------------
# Tab 4: Upload & Export Data
# -------------------------
def download_karyawan_template(request):
    """Download employee checkup template with real UID, nama, jabatan, lokasi, and tanggal_lahir."""
    try:
        excel_file = generate_karyawan_template_excel()
        response = HttpResponse(
            excel_file,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response['Content-Disposition'] = 'attachment; filename="Template_Checkup.xlsx"'
        return response
    except Exception as e:
        request.session['error_message'] = f"Failed to generate template: {e}"
        return redirect(reverse("manager:dashboard"))

def download_checkup_template(request):
    """
    Download Excel template containing master employee data 
    plus all medical checkup columns (like in V2).
    """
    try:
        # Use the same template generator as master karyawan
        excel_file = generate_karyawan_template_excel()
        response = HttpResponse(
            excel_file,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="Checkup_Template.xlsx"'
        return response

    except Exception as e:
        request.session["error_message"] = f"Failed to generate checkup template: {e}"
        return redirect(reverse("manager:upload_export"))



def upload_master_karyawan_xls(request):
    # Get first employee UID for Edit Karyawan menu
    employees_df = get_employees()
    default_uid = str(employees_df.iloc[0]['uid']) if not employees_df.empty else None

    menu_items = [
        {"key": "dashboard", "name": "Dashboard", "url": reverse("manager:dashboard"), "icon": "chart-line"},
        {"key": "user", "name": "User Management", "url": reverse("manager:user_management"), "icon": "users"},
        {"key": "qr", "name": "QR Codes", "url": reverse("manager:qr_codes"), "icon": "qrcode"},
        {"key": "data", "name": "Upload & Export", "url": reverse("manager:upload_export"), "icon": "upload"},
        {"key": "hapus_data_karyawan", "name": "Hapus Data Karyawan", "url": reverse("manager:hapus_data_karyawan"), "icon": "database"},
        {"key": "edit_karyawan", "name": "Edit Master Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
    ]
    
    if request.method == "POST" and request.FILES.get("file"):
        try:
            # Parse and save master karyawan data using core.excel_parser
            result = excel_parser.parse_master_karyawan(request.FILES["file"])
            # Build preview DataFrame without changing logic or computing BMI/umur
            preview_df = excel_parser.parse_master_preview(request.FILES["file"]) 

            preview_df = sanitize_df_for_display(preview_df)
            preview_cols = list(preview_df.columns)
            # Build a matrix for template rendering without custom filters
            preview_rows = [[str(row.get(col, "")) for col in preview_cols] for _, row in preview_df.iterrows()]
            request.session['success_message'] = f"{result['inserted']} karyawan berhasil diupload, {result['skipped']} dilewati."
            return render(request, "manager/upload_export.html", {
                "active_menu": "data",
                "menu_items": menu_items,
                "preview_cols": preview_cols,
                "preview_rows": preview_rows,
            })
        except Exception as e:
            request.session['error_message'] = f"Upload failed: {e}"
            return render(request, "manager/upload_export.html", {
                "active_menu": "data",
                "menu_items": menu_items,
            })
    
    return render(request, "manager/upload_export.html", {
        "active_menu": "data",
        "menu_items": menu_items
    })

def upload_medical_checkup_xls(request):
    """Upload medical checkup data from Excel."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    # Get first employee UID for Edit Karyawan menu
    employees_df = get_employees()
    default_uid = str(employees_df.iloc[0]['uid']) if not employees_df.empty else None

    menu_items = [
        {"key": "dashboard", "name": "Dashboard", "url": reverse("manager:dashboard"), "icon": "chart-line"},
        {"key": "user", "name": "User Management", "url": reverse("manager:user_management"), "icon": "users"},
        {"key": "qr", "name": "QR Codes", "url": reverse("manager:qr_codes"), "icon": "qrcode"},
        {"key": "data", "name": "Upload & Export", "url": reverse("manager:upload_export"), "icon": "upload"},
        {"key": "hapus_data_karyawan", "name": "Hapus Data Karyawan", "url": reverse("manager:hapus_data_karyawan"), "icon": "database"},
        {"key": "edit_karyawan", "name": "Edit Master Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
    ]
    
    if request.method == "POST" and request.FILES.get("file"):
        try:
            uploaded_file = request.FILES["file"]
            os.makedirs(settings.UPLOAD_CHECKUPS_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            original_name = os.path.basename(uploaded_file.name)
            save_path = os.path.join(settings.UPLOAD_CHECKUPS_DIR, f"{ts}-{original_name}")
            with open(save_path, "wb+") as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)

            # Parse medical checkup XLS (anthropometrics excluded; handled in master)
            result = checkup_uploader.parse_checkup_xls(save_path)
            # Write log entry for this upload
            write_checkup_upload_log(original_name, result)
            inserted = int(result.get('inserted', 0)) if isinstance(result, dict) else 0
            skipped = len(result.get('skipped', [])) if isinstance(result, dict) else 0
            request.session['success_message'] = f"Excel berhasil di upload! {inserted} checkup disimpan, {skipped} baris dilewati."
        except Exception as e:
            request.session['error_message'] = f"Upload failed: {e}"
        return redirect(reverse("manager:dashboard"))
    
    return render(request, "manager/upload_export.html", {
        "active_menu": "data",
        "menu_items": menu_items
    })

# -------------------------
# Upload Log Management
# -------------------------
@require_http_methods(["POST"]) 
def delete_upload_log(request):
    """Delete a single upload log JSON file and associated checkup records."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    log_file = request.POST.get("log_file", "").strip()
    redirect_url = reverse("manager:hapus_data_karyawan") + "?subtab=upload_history"

    if not log_file:
        request.session["error_message"] = "Tidak ada file log untuk dihapus."
        return redirect(redirect_url)

    safe_name = os.path.basename(log_file)
    if safe_name != log_file:
        request.session["error_message"] = "Nama file log tidak valid."
        return redirect(redirect_url)

    log_dir = getattr(settings, "UPLOAD_LOG_DIR", None)
    if not log_dir:
        request.session["error_message"] = "Direktori log tidak ditemukan."
        return redirect(redirect_url)

    base_dir = os.path.abspath(log_dir)
    target_path = os.path.abspath(os.path.join(base_dir, safe_name))
    if not target_path.startswith(base_dir + os.sep):
        request.session["error_message"] = "Akses direktori log tidak valid."
        return redirect(redirect_url)

    if os.path.isfile(target_path):
        deleted_checkups = 0
        try:
            # Read log to get inserted checkup IDs
            from core.queries import delete_checkup
            import json as _json
            with open(target_path, "r", encoding="utf-8") as f:
                data = _json.load(f)
                ids = data.get("inserted_ids", [])
                for cid in set(str(x) for x in ids if x):
                    try:
                        delete_checkup(cid)
                        deleted_checkups += 1
                    except Exception:
                        pass
            # Remove the log file itself
            os.remove(target_path)
            if deleted_checkups > 0:
                request.session["success_message"] = f"Log upload dihapus. {deleted_checkups} data checkup terkait turut dihapus."
            else:
                request.session["success_message"] = "Log upload berhasil dihapus. Tidak ada data checkup terkait."
        except Exception as e:
            request.session["error_message"] = f"Gagal menghapus log/checkup: {e}"
    else:
        request.session["error_message"] = "File log tidak ditemukan."

    return redirect(redirect_url)

@require_http_methods(["POST"]) 
def delete_upload_logs_bulk(request):
    """Delete multiple selected upload log JSON files and associated checkup records."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    redirect_url = reverse("manager:hapus_data_karyawan") + "?subtab=upload_history"
    selected = request.POST.getlist("selected_logs")

    if not selected:
        request.session["error_message"] = "Tidak ada log yang dipilih."
        return redirect(redirect_url)

    log_dir = getattr(settings, "UPLOAD_LOG_DIR", None)
    if not log_dir:
        request.session["error_message"] = "Direktori log tidak ditemukan."
        return redirect(redirect_url)

    base_dir = os.path.abspath(log_dir)
    deleted_logs = 0
    deleted_checkups = 0
    skipped_count = 0

    for name in selected:
        if not name:
            skipped_count += 1
            continue
        safe_name = os.path.basename(name.strip())
        if safe_name != name.strip():
            skipped_count += 1
            continue
        # Only allow JSON files
        if not safe_name.lower().endswith(".json"):
            skipped_count += 1
            continue
        target_path = os.path.abspath(os.path.join(base_dir, safe_name))
        if not target_path.startswith(base_dir + os.sep):
            skipped_count += 1
            continue
        if os.path.isfile(target_path):
            try:
                # Read log and delete related checkups
                from core.queries import delete_checkup
                import json as _json
                with open(target_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                    ids = data.get("inserted_ids", [])
                    for cid in set(str(x) for x in ids if x):
                        try:
                            delete_checkup(cid)
                            deleted_checkups += 1
                        except Exception:
                            pass
                # Delete the log file
                os.remove(target_path)
                deleted_logs += 1
            except Exception:
                skipped_count += 1
        else:
            skipped_count += 1

    if deleted_logs > 0:
        msg = f"{deleted_logs} log dihapus. {deleted_checkups} data checkup terkait turut dihapus."
        if skipped_count > 0:
            msg += f" {skipped_count} dilewati."
        request.session["success_message"] = msg
    else:
        request.session["error_message"] = "Tidak ada log yang dihapus."

    return redirect(redirect_url)

@require_http_methods(["POST"]) 
def purge_upload_logs(request):
    """Delete ALL upload log JSON files and their associated checkup records in the log directory."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    redirect_url = reverse("manager:hapus_data_karyawan") + "?subtab=upload_history"
    log_dir = getattr(settings, "UPLOAD_LOG_DIR", None)
    if not log_dir:
        request.session["error_message"] = "Direktori log tidak ditemukan."
        return redirect(redirect_url)

    base_dir = os.path.abspath(log_dir)
    deleted_logs = 0
    deleted_checkups = 0
    try:
        for fname in os.listdir(base_dir):
            if fname.lower().endswith(".json") and fname.startswith("checkups-"):
                fpath = os.path.abspath(os.path.join(base_dir, fname))
                if fpath.startswith(base_dir + os.sep) and os.path.isfile(fpath):
                    try:
                        # Read log and delete associated checkups
                        from core.queries import delete_checkup
                        import json as _json
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = _json.load(f)
                            ids = data.get("inserted_ids", [])
                            for cid in set(str(x) for x in ids if x):
                                try:
                                    delete_checkup(cid)
                                    deleted_checkups += 1
                                except Exception:
                                    pass
                        # Delete the log file
                        os.remove(fpath)
                        deleted_logs += 1
                    except Exception:
                        pass
        if deleted_logs > 0:
            request.session["success_message"] = f"Berhasil menghapus {deleted_logs} log upload dan {deleted_checkups} data checkup terkait."
        else:
            request.session["error_message"] = "Tidak ada log untuk dihapus."
    except Exception as e:
        request.session["error_message"] = f"Gagal menghapus semua log/checkup: {e}"

    return redirect(redirect_url)

# -------------------------
# Tab 5: Data Management / Hapus Data Karyawan
# -------------------------
def manage_karyawan_uid(request):
    """Manage employee UIDs / Hapus Data Karyawan unified page with filter and pagination."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    # Determine active subtab (karyawan, checkup, upload_history, logs)
    active_subtab = request.GET.get("subtab", "karyawan")

    # Load employees as DataFrame
    df = get_employees()

    # Filters (only by nama)
    filters = {
        'nama': request.GET.get('nama', '').strip(),
    }

    # Apply filter by nama (case-insensitive contains)
    if hasattr(df, 'empty') and not df.empty and filters['nama']:
        df = df[df['nama'].str.contains(filters['nama'], case=False, na=False)]

    # Ensure required columns exist
    if hasattr(df, 'empty') and not df.empty:
        for col in ['uid', 'nama', 'jabatan', 'lokasi']:
            if col not in df.columns:
                df[col] = ''
    else:
        # Create empty DataFrame with required columns if none
        import pandas as pd
        df = pd.DataFrame(columns=['uid', 'nama', 'jabatan', 'lokasi'])

    # Pagination (match dashboard behavior): max 10 per page
    items_per_page = 10
    total_items = len(df)
    total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 1
    current_page = int(request.GET.get('page', 1))
    current_page = max(1, min(current_page, total_pages))

    start_index = (current_page - 1) * items_per_page
    end_index = start_index + items_per_page

    # Slice for current page and convert to list of dicts
    df_page = df.iloc[start_index:end_index]
    employees = df_page[['uid', 'nama', 'jabatan', 'lokasi']].to_dict('records')

    # Build name options for selector (uid + "nama — jabatan") from full filtered dataset
    name_options = []
    if hasattr(df, 'empty') and not df.empty:
        try:
            opts_df = df[['uid', 'nama', 'jabatan']].drop_duplicates(subset=['uid'])
            name_options = [
                {'uid': row['uid'], 'nama': row['nama'], 'label': f"{row['nama']} — {row['jabatan']}"}
                for _, row in opts_df.iterrows()
            ]
        except Exception:
            name_options = []

    # Load upload history for the second tab
    try:
        hist_df = get_checkup_upload_history()
        upload_history = hist_df.to_dict('records') if hasattr(hist_df, 'empty') and not hist_df.empty else []
    except Exception:
        upload_history = []

    # Normalize timestamp and inserted_ids for template usage (limit IDs preview to 5)
    try:
        for row in upload_history:
            ts = row.get("timestamp")
            if isinstance(ts, str):
                try:
                    row["timestamp"] = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            ids = row.get("inserted_ids")
            if isinstance(ids, list):
                str_ids = [str(x) for x in ids]
                row["inserted_ids"] = str_ids
                row["inserted_ids_preview"] = str_ids[:5]
                row["inserted_ids_more_count"] = max(0, len(str_ids) - 5)
    except Exception:
        pass

    # Logs subtab: fetch manual input logs for selected UID
    selected_uid = (request.GET.get('uid') or '').strip()
    manual_logs = []
    if active_subtab == 'logs' and selected_uid:
        try:
            from core.queries import get_manual_input_logs
            logs_df = get_manual_input_logs(selected_uid)
            manual_logs = logs_df.to_dict('records') if hasattr(logs_df, 'empty') and not logs_df.empty else []
        except Exception:
            manual_logs = []

    context = {
        'employees': employees,
        'page_title': 'Hapus Data Karyawan',
        'current_page': current_page,
        'total_pages': total_pages,
        'start_index': start_index,
        'filters': filters,
        'name_options': name_options,
        'active_subtab': active_subtab,
        'upload_history': upload_history,
        'manual_logs': manual_logs,
        'selected_uid': selected_uid,
        'MEDIA_URL': settings.MEDIA_URL,
    }

    return render(request, "manager/data_management.html", context)



# -------------------------
# Tab 5b: Delete Single Employee
# -------------------------
def delete_karyawan(request, uid):
    """Delete a single employee by UID safely and return to main data page."""
    from core.queries import delete_employee_by_uid

    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        delete_employee_by_uid(uid)
        request.session['success_message'] = "Employee deleted successfully"
    except Exception as e:
        request.session['error_message'] = f"Failed to delete employee: {e}"

    return redirect(reverse("manager:hapus_data_karyawan"))
# -------------------------
# Tab 5c: Reset All Employees
# -------------------------
def reset_all_karyawan(request):
    """Delete all employees safely."""
    from core.queries import reset_karyawan_data  # Ensure this exists

    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        reset_karyawan_data()
        request.session['success_message'] = "All employee data has been reset successfully"
    except Exception as e:
        request.session['error_message'] = f"Failed to reset employee data: {e}"

    return redirect(reverse("manager:hapus_data_karyawan"))

# -------------------------
# Tab 5d: Reset All Checkups
# -------------------------
@require_http_methods(["POST"]) 
def reset_all_checkups(request):
    """Delete all medical checkup records safely."""
    from core.queries import delete_all_checkups

    # Accept either custom session auth (Manager) or Django auth for staff/superuser
    session_auth = request.session.get("authenticated")
    session_role = request.session.get("user_role")
    user_ok = hasattr(request, "user") and getattr(request.user, "is_authenticated", False) and (getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))
    if not ((session_auth and session_role == "Manager") or user_ok):
        return redirect("accounts:login")

    try:
        delete_all_checkups()
        request.session['success_message'] = "Semua data checkup berhasil dihapus."
    except Exception as e:
        request.session['error_message'] = f"Gagal menghapus semua data checkup: {e}"

    # Stay on the Data Management page and switch to the new checkup subtab
    return redirect(reverse("manager:hapus_data_karyawan") + "?subtab=checkup")

# -------------------------
# Tab 6: Manage Lokasi
# -------------------------
def manage_lokasi(request):
    """Manage Lokasi (Work Locations)"""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    menu_items = [
        {"key": "dashboard", "name": "Dashboard", "url": reverse("manager:dashboard"), "icon": "chart-line"},
        {"key": "user", "name": "User Management", "url": reverse("manager:user_management"), "icon": "users"},
        {"key": "qr", "name": "QR Codes", "url": reverse("manager:qr_codes"), "icon": "qrcode"},
        {"key": "data", "name": "Upload & Export", "url": reverse("manager:upload_export"), "icon": "upload"},
    ]

    # Fetch real lokasi data
    lokasi_list = get_all_lokasi()  # returns a list of dictionaries or DataFrame with id/name

    # If returned as DataFrame, convert to list of dicts for template
    if hasattr(lokasi_list, "to_dict"):
        lokasi_list = lokasi_list.to_dict("records")

    context = {
        "lokasi_list": lokasi_list,
        "active_menu": "data",  # sidebar highlights Upload & Export/Data
        "menu_items": menu_items,
        "page_title": "Manage Lokasi",
    }

    return render(request, "manager/manage_lokasi.html", context)

# -------------------------
# Tab 6: Employee Profile
# -------------------------
def employee_profile(request, uid):
    """View/edit employee profile."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    # Handle selector redirect if a different uid is chosen via GET
    requested_uid = request.GET.get("uid")
    if requested_uid and str(requested_uid) != str(uid):
        submenu = request.GET.get("submenu", "edit")
        subtab = request.GET.get("subtab")
        # Allow known submenu keys: edit, history, data_karyawan
        if submenu not in ["edit", "history", "data_karyawan", "edit_data"]:
            submenu = "edit"
        # Normalize: route 'edit' and 'edit_data' under data_karyawan with subtab
        if submenu in ["edit", "edit_data"]:
            mapped_subtab = "profile" if submenu == "edit" else "edit_data"
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": requested_uid}) + f"?submenu=data_karyawan&subtab={mapped_subtab}")
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": requested_uid}) + f"?submenu={submenu}{f'&subtab={subtab}' if subtab else ''}")

    # Determine active submenu and subtab
    active_submenu = request.GET.get("submenu", "data_karyawan")
    active_subtab = request.GET.get("subtab", "profile")

    # Validate submenu
    if active_submenu not in ["data_karyawan", "history", "grafik"]:
        # Map legacy keys to new structure
        if active_submenu == "edit":
            active_submenu = "data_karyawan"
            active_subtab = "profile"
        elif active_submenu == "edit_data":
            active_submenu = "data_karyawan"
            active_subtab = "edit_data"
        else:
            active_submenu = "data_karyawan"
            active_subtab = "profile"

    # Validate subtab under data_karyawan (allow profile, edit_data, edit_checkup, tambah, lokasi)
    if active_submenu == "data_karyawan" and active_subtab not in ["profile", "edit_data", "edit_checkup", "tambah", "lokasi"]:
        active_subtab = "profile"

    # NEW: Handle edit/delete single checkup row from History tab
    if request.method == "POST" and active_submenu == "history":
        action = (request.POST.get("action") or "").strip()
        target_id = (request.POST.get("checkup_id") or "").strip()
        if action == "edit_row" and target_id:
            try:
                from core.core_models import Checkup
                # Parse incoming fields; update only provided ones
                def _to_float(v):
                    try:
                        return float(v) if v is not None and str(v).strip() != "" else None
                    except Exception:
                        return None
                def _to_int(v):
                    try:
                        return int(v) if v is not None and str(v).strip() != "" else None
                    except Exception:
                        return None
                def _to_str(v):
                    return str(v).strip() if v is not None and str(v).strip() != "" else None
                tanggal_checkup_raw = request.POST.get("tanggal_checkup")
                try:
                    # Parse with dayfirst=True to correctly handle 'dd/mm/yy' input
                    tc_dt = pd.to_datetime(tanggal_checkup_raw, dayfirst=True, errors="coerce") if tanggal_checkup_raw else None
                    tanggal_checkup_val = tc_dt.date() if pd.notna(tc_dt) else None
                except Exception:
                    tanggal_checkup_val = None
                update_fields = {}
                if tanggal_checkup_val is not None:
                    update_fields["tanggal_checkup"] = tanggal_checkup_val
                # Numeric/text fields
                for key, conv in [
                    ("tinggi", _to_float),
                    ("berat", _to_float),
                    ("lingkar_perut", _to_float),
                    ("bmi", _to_float),
                    ("umur", _to_int),
                    ("gula_darah_puasa", _to_float),
                    ("gula_darah_sewaktu", _to_float),
                    ("cholesterol", _to_float),
                    ("asam_urat", _to_float),
                    ("tekanan_darah", _to_str),
                    ("derajat_kesehatan", _to_str),
                ]:
                    val = conv(request.POST.get(key))
                    if val is not None:
                        update_fields[key] = val
                if update_fields:
                    Checkup.objects.filter(checkup_id=target_id).update(**update_fields)
                    request.session['success_message'] = "Baris riwayat checkup berhasil diperbarui."
                    # Log manual edit to checkup
                    actor = request.session.get("username") or getattr(request.user, "username", None)
                    role = request.session.get("user_role") or "Unknown"
                    try:
                        write_manual_input_log(uid=uid, actor=str(actor), role=str(role), event="manual_checkup_input", changed_fields=list(update_fields.keys()), new_values=update_fields, checkup_id=target_id)
                    except Exception:
                        pass
                else:
                    request.session['error_message'] = "Tidak ada perubahan yang disimpan."
            except Exception as e:
                request.session['error_message'] = f"Gagal menyimpan perubahan: {e}"
        elif action == "delete_all_checkups":
            try:
                from core.core_models import Checkup
                deleted_count, _ = Checkup.objects.filter(uid_id=uid).delete()
                request.session['success_message'] = f"Berhasil menghapus semua data checkup untuk karyawan ini ({deleted_count} baris)."
            except Exception as e:
                request.session['error_message'] = f"Gagal menghapus semua data checkup: {e}"
        else:
            # Default to delete if checkup_id is provided without edit action
            del_id = target_id
            if del_id:
                try:
                    from core.queries import delete_checkup
                    delete_checkup(str(del_id))
                    request.session['success_message'] = "Baris riwayat checkup berhasil dihapus."
                except Exception as e:
                    request.session['error_message'] = f"Gagal menghapus baris riwayat: {e}"
        # Always return to History tab after handling POST
        return redirect(reverse("manager:edit_karyawan", kwargs={'uid': uid}) + "?submenu=history")

    # Handle V2 Edit Master Data submission (manager only)
    if request.method == "POST" and active_submenu == "data_karyawan" and active_subtab == "edit_data":
        nama = (request.POST.get("nama") or "").strip()
        jabatan = (request.POST.get("jabatan") or "").strip()
        lokasi = (request.POST.get("lokasi") or "").strip()

        tanggal_lahir = safe_date(request.POST.get("tanggal_lahir"))
        tanggal_MCU = safe_date(request.POST.get("tanggal_MCU"))
        expired_MCU = safe_date(request.POST.get("expired_MCU"))

        derajat_kesehatan = request.POST.get("derajat_kesehatan")
        if derajat_kesehatan is not None:
            derajat_kesehatan = str(derajat_kesehatan).strip().upper()
            derajat_kesehatan = derajat_kesehatan.replace(" ", "")

        tinggi = safe_float(request.POST.get("tinggi"))
        berat = safe_float(request.POST.get("berat"))
        bmi = safe_float(request.POST.get("bmi"))

        bmi_category = (request.POST.get("bmi_category") or "").strip()

        # Validate lokasi if provided
        if lokasi and not validate_lokasi(lokasi):
            request.session['error_message'] = "Lokasi tidak valid. Pilih lokasi yang tersedia."
            return redirect(reverse("manager:edit_karyawan", kwargs={'uid': uid}) + "?submenu=data_karyawan&subtab=edit_data")

        # Do NOT auto-compute BMI. Respect XLS/manual value as-is.
        # Leave bmi as provided; if None, it will not be saved/changed.

        # Build update payload only with provided non-empty fields (V2 logic)
        row = {"uid": uid}
        if nama:
            row["nama"] = nama
        if jabatan:
            row["jabatan"] = jabatan
        if lokasi:
            row["lokasi"] = lokasi
        if tanggal_lahir is not None:
            row["tanggal_lahir"] = tanggal_lahir
        if tanggal_MCU is not None:
            row["tanggal_MCU"] = tanggal_MCU
        if expired_MCU is not None:
            row["expired_MCU"] = expired_MCU
        if derajat_kesehatan:
            row["derajat_kesehatan"] = derajat_kesehatan
        if tinggi is not None:
            row["tinggi"] = tinggi
        if berat is not None:
            row["berat"] = berat
        if bmi is not None:
            row["bmi"] = bmi
        if bmi_category:
            row["bmi_category"] = bmi_category

        try:
            df_updates = pd.DataFrame([row])
            updated_count = save_manual_karyawan_edits(df_updates)
            if updated_count > 0:
                request.session['success_message'] = "Data master karyawan berhasil diperbarui."
                # Log manual edit to master data
                actor = request.session.get("username") or getattr(request.user, "username", None)
                role = request.session.get("user_role") or "Unknown"
                changed_fields = [k for k in row.keys() if k != "uid"]
                new_values = {k: row[k] for k in changed_fields}
                try:
                    write_manual_input_log(uid=uid, actor=str(actor), role=str(role), event="edit_master", changed_fields=changed_fields, new_values=new_values)
                except Exception:
                    pass
            else:
                request.session['error_message'] = "Tidak ada perubahan yang disimpan."
        except Exception as e:
            request.session['error_message'] = f"Gagal menyimpan perubahan: {e}"
        return redirect(reverse("manager:edit_karyawan", kwargs={'uid': uid}) + "?submenu=data_karyawan&subtab=edit_data")

    # Load employees list for selector
    employees_df = get_employees()
    if employees_df is None or employees_df.empty:
        employees = []
    else:
        employees = employees_df[["uid", "nama"]].to_dict("records")

    # Get selected employee details (sanitized)
    employee_raw = get_employee_by_uid(uid)
    employee_clean = None
    if employees_df is not None and not employees_df.empty:
        try:
            df_uid = employees_df[employees_df['uid'].astype(str) == str(uid)]
            if not df_uid.empty:
                employee_clean = df_uid.iloc[0].to_dict()
        except Exception:
            pass
    if employee_clean is None and employee_raw is not None:
        # Fallback to raw object/dict
        try:
            emp_dict = {}
            for key in ["uid", "nama", "jabatan", "lokasi", "tanggal_lahir", "tanggal_MCU", "expired_MCU"]:
                emp_dict[key] = employee_raw.get(key) if isinstance(employee_raw, dict) else getattr(employee_raw, key, None)
            employee_clean = emp_dict
        except Exception:
            employee_clean = {}

    checkups = get_medical_checkups_by_uid(uid)

    # Compute latest checkup record for display below the employee info table
    latest_checkup = None
    try:
        if not checkups.empty:
            # Sort using raw values to preserve numeric types for status computation
            checkups["tanggal_checkup"] = pd.to_datetime(checkups["tanggal_checkup"], errors="coerce")
            latest_row = checkups.sort_values("tanggal_checkup", ascending=False).iloc[0]

            # Local import to avoid changing global imports
            from core.helpers import compute_status, sanitize_df_for_display as _sanitize
            status = compute_status(latest_row)

            # Compute threshold flags using raw numeric values
            bmi_n = pd.to_numeric(latest_row.get('bmi', None), errors='coerce')
            gdp_n = pd.to_numeric(latest_row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(latest_row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(latest_row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(latest_row.get('asam_urat', None), errors='coerce')
            flags = {
                'bmi_high': (pd.notna(bmi_n) and bmi_n >= 30),
                'gdp_high': (pd.notna(gdp_n) and gdp_n > 120),
                'gds_high': (pd.notna(gds_n) and gds_n > 200),
                'chol_high': (pd.notna(chol_n) and chol_n > 240),
                'asam_high': (pd.notna(asam_n) and asam_n > 7),
            }

            # Sanitize only the latest row for display
            latest_disp = _sanitize(pd.DataFrame([latest_row])).iloc[0].to_dict()
            # Override date format for display (dd/mm/yy)
            try:
                dt = pd.to_datetime(latest_row.get("tanggal_checkup"), errors="coerce")
                if pd.notna(dt):
                    latest_disp["tanggal_checkup"] = dt.strftime("%d/%m/%y")
            except Exception:
                pass
            # Ensure derajat_kesehatan is present for template display
            try:
                dk_raw = latest_row.get('derajat_kesehatan', None)
                if dk_raw is not None:
                    latest_disp['derajat_kesehatan'] = str(dk_raw)
            except Exception:
                # If any issue occurs, leave it unset and template will show '-'
                pass
            # Fallback to baseline from Karyawan if checkup value missing
            if not latest_disp.get('derajat_kesehatan'):
                try:
                    base_dk = (employee_clean or {}).get('derajat_kesehatan')
                    if base_dk:
                        latest_disp['derajat_kesehatan'] = str(base_dk)
                except Exception:
                    pass
            latest_disp["status"] = status
            latest_disp["flags"] = flags
            latest_checkup = latest_disp
    except Exception:
        latest_checkup = None

    # Build history records for template
    history_checkups = []
    # Employee BMI fallback for rows that lack BMI (no auto-calculation)
    try:
        emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
    except Exception:
        emp_bmi = None
    try:
        if checkups is not None and not checkups.empty:
            df_hist = checkups.copy()
            df_hist["tanggal_checkup"] = pd.to_datetime(df_hist["tanggal_checkup"], errors="coerce")
            df_hist = df_hist.sort_values("tanggal_checkup", ascending=False)
            from core.helpers import compute_status
            for _, row in df_hist.iterrows():
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
                # BMI fallback: no autocalc; use employee BMI if row BMI missing/zero
                try:
                    if ((bmi_n is None) or (isinstance(bmi_n, float) and pd.isna(bmi_n)) or (float(bmi_n) == 0.0)) and pd.notna(emp_bmi):
                        bmi_n = float(emp_bmi)
                except Exception:
                    pass
                gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
                flags = {
                    'bmi_high': (pd.notna(bmi_n) and bmi_n >= 30),
                    'gdp_high': (pd.notna(gdp_n) and gdp_n > 120),
                    'gds_high': (pd.notna(gds_n) and gds_n > 200),
                    'chol_high': (pd.notna(chol_n) and chol_n > 240),
                    'asam_high': (pd.notna(asam_n) and asam_n > 7),
                }
                status = compute_status(row)
                dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                tanggal_str = dt.strftime("%d/%m/%y") if pd.notna(dt) else ""
                history_checkups.append({
                    'tanggal_checkup': tanggal_str,
                    'bmi': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else None,
                    'berat': row.get('berat', None),
                    'tinggi': row.get('tinggi', None),
                    'lingkar_perut': row.get('lingkar_perut', None),
                    'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                    'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                    'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                    'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                    'status': status,
                    'flags': flags,
                })
    except Exception:
        history_checkups = []

    # Build dashboard-like history records (similar columns as dashboard, but per UID history)
    history_dashboard = []
    try:
        if checkups is not None and not checkups.empty:
            df_hist2 = checkups.copy()
            # Normalize uid column
            if 'uid_id' in df_hist2.columns and 'uid' not in df_hist2.columns:
                df_hist2 = df_hist2.rename(columns={'uid_id': 'uid'})
            # Ensure tanggal_checkup is datetime for sorting/formatting
            if 'tanggal_checkup' in df_hist2.columns:
                df_hist2['tanggal_checkup'] = pd.to_datetime(df_hist2['tanggal_checkup'], errors='coerce')
            df_hist2 = df_hist2.sort_values('tanggal_checkup', ascending=False)

            # Employee info fallbacks
            emp_nama = (employee_clean or {}).get('nama')
            emp_jabatan = (employee_clean or {}).get('jabatan')
            emp_lokasi = (employee_clean or {}).get('lokasi')
            emp_tanggal_lahir = None
            try:
                tl_raw = (employee_clean or {}).get('tanggal_lahir')
                tl_dt = pd.to_datetime(tl_raw, errors='coerce')
                emp_tanggal_lahir = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
            except Exception:
                emp_tanggal_lahir = None

            # Format MCU dates from employee master data (pass-through, no computation)
            emp_tanggal_mcu = None
            emp_expired_mcu = None
            try:
                mcu_raw = (employee_clean or {}).get('tanggal_MCU')
                mcu_dt = pd.to_datetime(mcu_raw, errors='coerce')
                emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
            except Exception:
                pass
            try:
                exp_raw = (employee_clean or {}).get('expired_MCU')
                exp_dt = pd.to_datetime(exp_raw, errors='coerce')
                emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
            except Exception:
                pass

            from core.helpers import compute_status as _compute_status
            for _, row in df_hist2.iterrows():
                # Numeric coercion for safety
                tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
                berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
                # BMI fallback: do NOT auto-calculate. Defer fallback and use employee BMI later if row BMI is missing/zero.
                lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
                gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
                # Do NOT auto-compute umur; use provided XLS/master value as-is (take from employee master)
                try:
                    umur_val = (employee_clean or {}).get('umur', None)
                except Exception:
                    umur_val = None
                # Employee BMI for fallback
                try:
                    emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
                except Exception:
                    emp_bmi = None

                # BMI fallback: no autocalc; use employee BMI if row BMI missing/zero
                try:
                    if ((bmi_n is None) or (isinstance(bmi_n, float) and pd.isna(bmi_n)) or (float(bmi_n) == 0.0)) and pd.notna(emp_bmi):
                        bmi_n = float(emp_bmi)
                except Exception:
                    pass

                # Date formatting
                tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

                # Status from thresholds
                status_val = _compute_status({
                    'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                    'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                    'cholesterol': chol_n if pd.notna(chol_n) else 0,
                    'asam_urat': asam_n if pd.notna(asam_n) else 0,
                    'bmi': bmi_n if pd.notna(bmi_n) else 0,
                })

                # Prefer checkup derajat_kesehatan; fallback to employee baseline
                dk_val = row.get('derajat_kesehatan', None)
                try:
                    if dk_val is None or (isinstance(dk_val, float) and pd.isna(dk_val)) or (isinstance(dk_val, str) and not dk_val.strip()):
                        dk_val = (employee_clean or {}).get('derajat_kesehatan')
                except Exception:
                    pass
                # BMI category: prefer row value, fallback to employee, else compute from BMI
                bmi_cat_val = row.get('bmi_category', None)
                try:
                    def _is_blank(x):
                        return (x is None) or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not str(x).strip())
                    if _is_blank(bmi_cat_val):
                        bmi_cat_val = (employee_clean or {}).get('bmi_category', None)
                    if _is_blank(bmi_cat_val):
                        bmi_source = bmi_n if pd.notna(bmi_n) else (emp_bmi if pd.notna(emp_bmi) else None)
                        bmi_cat_val = compute_bmi_category(bmi_source)
                except Exception:
                    pass

                history_dashboard.append({
                    'uid': str(row.get('uid', uid)),
                    'nama': emp_nama,
                    'jabatan': emp_jabatan,
                    'lokasi': emp_lokasi,
                    'tanggal_lahir': emp_tanggal_lahir,
                    'umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                    'tanggal_checkup': tanggal_str,
                    'tinggi': float(tinggi_n) if pd.notna(tinggi_n) else None,
                    'berat': float(berat_n) if pd.notna(berat_n) else None,
                    'bmi': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else None,
                    'bmi_category': str(bmi_cat_val) if bmi_cat_val is not None else None,
                    'lingkar_perut': float(lp_n) if pd.notna(lp_n) else None,
                    'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                    'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                    'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                    'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                    'tekanan_darah': row.get('tekanan_darah', None),
                    'derajat_kesehatan': str(dk_val) if dk_val is not None else None,
                    'tanggal_MCU': emp_tanggal_mcu,
                    'expired_MCU': emp_expired_mcu,
                    'checkup_id': row.get('checkup_id'),
                    'status': status_val,
                    'flags': {
                        'bmi_high': (pd.notna(bmi_n) and float(bmi_n) >= 30.0),
                        'gdp_high': (pd.notna(gdp_n) and float(gdp_n) > 120.0),
                        'gds_high': (pd.notna(gds_n) and float(gds_n) > 200.0),
                        'chol_high': (pd.notna(chol_n) and float(chol_n) > 240.0),
                        'asam_high': (pd.notna(asam_n) and float(asam_n) > 7.0),
                    },
                })
    except Exception:
        history_dashboard = []

    # Grafik tab data (month range filter)
    grafik_chart_html = None
    grafik_start_month = request.GET.get('start_month')
    grafik_end_month = request.GET.get('end_month')
    try:
        # Default to last 6 months
        today = datetime.today()
        def _month_str(dt):
            return f"{dt.year}-{dt.month:02d}"
        if not grafik_end_month:
            grafik_end_month = _month_str(today)
        if not grafik_start_month:
            grafik_start_month = _month_str(today - pd.DateOffset(months=5))

        df_ts = checkups.copy() if checkups is not None else pd.DataFrame()
        if df_ts is not None and not df_ts.empty:
            df_ts['tanggal_checkup'] = pd.to_datetime(df_ts['tanggal_checkup'], errors='coerce')
            # Range boundaries
            start_dt = pd.to_datetime(grafik_start_month + '-01', errors='coerce') if grafik_start_month else None
            end_dt = pd.to_datetime(grafik_end_month + '-01', errors='coerce') if grafik_end_month else None
            if pd.notnull(end_dt):
                end_dt = (end_dt + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
            if pd.notnull(start_dt) and pd.notnull(end_dt):
                df_ts = df_ts[(df_ts['tanggal_checkup'] >= start_dt) & (df_ts['tanggal_checkup'] <= end_dt)]

            df_ts = df_ts.sort_values('tanggal_checkup')
            x_vals = df_ts['tanggal_checkup']
            gdp = pd.to_numeric(df_ts.get('gula_darah_puasa'), errors='coerce')
            gds = pd.to_numeric(df_ts.get('gula_darah_sewaktu'), errors='coerce')
            lp = pd.to_numeric(df_ts.get('lingkar_perut'), errors='coerce')
            chol = pd.to_numeric(df_ts.get('cholesterol'), errors='coerce')
            asam = pd.to_numeric(df_ts.get('asam_urat'), errors='coerce')
            bmi_series = pd.to_numeric(df_ts.get('bmi'), errors='coerce')
            def _parse_systolic(val):
                try:
                    s = str(val)
                    if '/' in s:
                        return pd.to_numeric(s.split('/')[0], errors='coerce')
                    return pd.to_numeric(val, errors='coerce')
                except Exception:
                    return pd.NA
            td_systolic = df_ts['tekanan_darah'].apply(_parse_systolic) if 'tekanan_darah' in df_ts.columns else pd.Series([], dtype='float64')

            fig = go.Figure()
            if not x_vals.empty:
                if gdp is not None and not gdp.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=gdp, name='Gula Darah Puasa'))
                if gds is not None and not gds.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=gds, name='Gula Darah Sewaktu'))
                if td_systolic is not None and not td_systolic.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=td_systolic, name='Tekanan Darah (Sistole)'))
                if lp is not None and not lp.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=lp, name='Lingkar Perut'))
                if chol is not None and not chol.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=chol, name='Cholesterol'))
                if asam is not None and not asam.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=asam, name='Asam Urat'))
                if bmi_series is not None and not bmi_series.empty:
                    fig.add_trace(go.Bar(x=x_vals, y=bmi_series, name='BMI'))

                fig.update_layout(
                    title='Grafik Riwayat Medical Checkup',
                    xaxis_title='Tanggal Checkup',
                    yaxis=dict(title='Nilai', showticklabels=True),
                    legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                    margin=dict(l=40, r=20, t=60, b=40),
                    template='plotly_white',
                    barmode='group',
                    height=600
                )
                grafik_chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')
    except Exception:
        grafik_chart_html = None

    # Messages and lokasi options
    success_message = request.session.pop('success_message', None)
    error_message = request.session.pop('error_message', None)
    available_lokasi = get_all_lokasi()

    # Compute MCU expiry estimate (days until/since expiration)
    mcu_expiry_estimate = None
    try:
        exp_raw = (employee_clean or {}).get('expired_MCU')
        exp_dt = pd.to_datetime(exp_raw, errors='coerce')
        if pd.notna(exp_dt):
            delta_days = (exp_dt.date() - datetime.today().date()).days
            if delta_days > 0:
                mcu_expiry_estimate = f"{delta_days} hari lagi"
            elif delta_days == 0:
                mcu_expiry_estimate = "Hari ini"
            else:
                mcu_expiry_estimate = f"Expired {abs(delta_days)} hari lalu"
    except Exception:
        pass

    return render(request, "manager/edit_karyawan.html", {
        "employee": employee_clean or {},
        "employees": employees,
        "checkups": checkups,
        "latest_checkup": latest_checkup,
        "history_checkups": history_checkups,
        "history_dashboard": history_dashboard,
        "active_submenu": active_submenu,
        "active_subtab": active_subtab,
        "success_message": success_message,
        "error_message": error_message,
        "available_lokasi": available_lokasi,
        "lokasi_list": available_lokasi,
        "mcu_expiry_estimate": mcu_expiry_estimate,
        "grafik_chart_html": grafik_chart_html,
        "grafik_start_month": grafik_start_month,
        "grafik_end_month": grafik_end_month,
    })

# New: Add Karyawan (Data Karyawan > Tambah karyawan)
@require_http_methods(["POST"])
def add_karyawan(request):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    nama = (request.POST.get("nama") or "").strip()
    jabatan = (request.POST.get("jabatan") or "").strip()
    lokasi = (request.POST.get("lokasi") or "").strip()
    tanggal_lahir_raw = request.POST.get("tanggal_lahir")
    tanggal_lahir = safe_date(tanggal_lahir_raw)

    if not nama or not jabatan or not validate_lokasi(lokasi):
        request.session['error_message'] = "Mohon isi Nama, Jabatan, dan Lokasi dengan benar."
        employees_df = get_employees()
        default_uid = str(employees_df.iloc[0]['uid']) if employees_df is not None and not employees_df.empty else None
        if default_uid:
            return redirect(reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) + "?submenu=data_karyawan&subtab=tambah")
        return redirect(reverse("manager:dashboard"))

    try:
        from core.core_models import Karyawan
        existing = Karyawan.objects.filter(nama=nama, jabatan=jabatan).first()
        if existing:
            request.session['error_message'] = f"Karyawan sudah ada dengan UID: {existing.uid}"
            return redirect(reverse("manager:edit_karyawan", kwargs={'uid': existing.uid}) + "?submenu=data_karyawan&subtab=profile")

        uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{nama}-{jabatan}"))
        Karyawan.objects.create(
            uid=uid,
            nama=nama,
            jabatan=jabatan,
            lokasi=lokasi,
            tanggal_lahir=tanggal_lahir,
        )
        request.session['success_message'] = f"Karyawan '{nama}' berhasil ditambahkan. UID: {uid}"
        return redirect(reverse("manager:edit_karyawan", kwargs={'uid': uid}) + "?submenu=data_karyawan&subtab=profile")
    except Exception as e:
        request.session['error_message'] = f"Gagal menambahkan karyawan: {e}"
        employees_df = get_employees()
        default_uid = str(employees_df.iloc[0]['uid']) if employees_df is not None and not employees_df.empty else None
        if default_uid:
            return redirect(reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) + "?submenu=data_karyawan&subtab=tambah")
        return redirect(reverse("manager:dashboard"))

@require_http_methods(["POST"])
def add_lokasi(request):
    """
    Manager-only endpoint to add a new Lokasi and redirect back to Data Karyawan > Lokasi Management tab.
    """
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    lokasi_name = (request.POST.get("lokasi") or "").strip()
    current_uid = (request.POST.get("current_uid") or "").strip()

    if not lokasi_name or not validate_lokasi(lokasi_name):
        request.session['error_message'] = "Nama lokasi tidak valid. Harap isi nama lokasi."
    else:
        try:
            from core.core_models import Lokasi
            obj, created = Lokasi.objects.get_or_create(nama=lokasi_name)
            if created:
                request.session['success_message'] = f"Lokasi '{lokasi_name}' berhasil ditambahkan."
            else:
                request.session['error_message'] = f"Lokasi '{lokasi_name}' sudah ada."
        except Exception as e:
            request.session['error_message'] = f"Gagal menambahkan lokasi: {e}"

    if current_uid:
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": current_uid}) + "?submenu=data_karyawan&subtab=lokasi")
    return redirect(reverse("manager:manage_lokasi"))

@require_http_methods(["POST"])
def save_medical_checkup(request, uid):
    # Ensure only Manager can save
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        tanggal_checkup = request.POST.get("tanggal_checkup")
        tinggi = request.POST.get("tinggi")
        berat = request.POST.get("berat")
        lingkar_perut = request.POST.get("lingkar_perut")
        gula_darah_puasa = request.POST.get("gula_darah_puasa")
        gula_darah_sewaktu = request.POST.get("gula_darah_sewaktu")
        cholesterol = request.POST.get("cholesterol")
        asam_urat = request.POST.get("asam_urat")
        umur = request.POST.get("umur")
        derajat_kesehatan = request.POST.get("derajat_kesehatan")
        tekanan_darah = request.POST.get("tekanan_darah")
        bmi = request.POST.get("bmi")

        # Determine checkup date
        tanggal_checkup_date = pd.to_datetime(tanggal_checkup).date() if tanggal_checkup else datetime.today().date()

        # Normalize umur to int if provided (no auto-calculation)
        umur_value = None
        try:
            if umur:
                umur_value = int(umur)
        except Exception:
            umur_value = None

        record = {
            "uid": uid,
            "tanggal_checkup": tanggal_checkup_date,
            "tinggi": float(tinggi) if tinggi else None,
            "berat": float(berat) if berat else None,
            "lingkar_perut": float(lingkar_perut) if lingkar_perut else None,
            "bmi": float(bmi) if bmi else None,
            "umur": umur_value,
            "gula_darah_puasa": float(gula_darah_puasa) if gula_darah_puasa else None,
            "gula_darah_sewaktu": float(gula_darah_sewaktu) if gula_darah_sewaktu else None,
            "cholesterol": float(cholesterol) if cholesterol else None,
            "asam_urat": float(asam_urat) if asam_urat else None,
            "tekanan_darah": tekanan_darah.strip() if tekanan_darah else None,
            "derajat_kesehatan": derajat_kesehatan.strip() if derajat_kesehatan else None,
        }

        new_obj = insert_medical_checkup(**record)
        request.session["success_message"] = "Pemeriksaan medis berhasil disimpan."
        # Log manual checkup input entry
        actor = request.session.get("username") or getattr(request.user, "username", None)
        role = request.session.get("user_role") or "Unknown"
        try:
            write_manual_input_log(
                uid=uid,
                actor=str(actor),
                role=str(role),
                event="manual_checkup_input",
                changed_fields=list(record.keys()),
                new_values=record,
                checkup_id=getattr(new_obj, "checkup_id", None),
            )
        except Exception:
            pass
    except Exception as e:
        request.session["error_message"] = f"Gagal menyimpan checkup: {e}"

    return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=data_karyawan&subtab=profile")

@require_http_methods(["GET"]) 
def export_checkup_data_excel(request):
    # Auth guard for Manager
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        # Default: latest checkup per employee
        df_latest = get_dashboard_checkup_data()
        if df_latest is None or df_latest.empty:
            request.session["warning_message"] = "belum ada check up data, silahkan unggah terlebih dahulu"
            return redirect(reverse("manager:upload_export") + "?submenu=export_data")

        # Apply month range filter if provided
        start_month = request.GET.get('start_month', '').strip()
        end_month = request.GET.get('end_month', '').strip()
        df = df_latest.copy()
        if start_month and end_month:
            try:
                import pandas as _pd
                hist = load_checkups()
                if hist is not None and hasattr(hist, 'empty') and not hist.empty:
                    # Parse and filter
                    if 'tanggal_checkup' in hist.columns:
                        hist['tanggal_checkup'] = _pd.to_datetime(hist['tanggal_checkup'], errors='coerce', dayfirst=True)
                    try:
                        if 'status' not in hist.columns or hist['status'].isna().any():
                            hist['status'] = hist.apply(compute_status, axis=1)
                    except Exception:
                        hist['status'] = hist.get('status', '')
                    start_dt = _pd.to_datetime(start_month + '-01', errors='coerce')
                    end_dt = _pd.to_datetime(end_month + '-01', errors='coerce')
                    end_dt_end = (end_dt + _pd.offsets.MonthBegin(1)) - _pd.Timedelta(days=1) if _pd.notnull(end_dt) else end_dt
                    if _pd.notnull(start_dt):
                        hist = hist[hist['tanggal_checkup'] >= start_dt]
                    if _pd.notnull(end_dt_end):
                        hist = hist[hist['tanggal_checkup'] <= end_dt_end]
                    if not hist.empty and 'uid' in hist.columns:
                        hist = hist.sort_values(by=['uid','tanggal_checkup'])
                        latest_in_range = hist.groupby('uid').tail(1).set_index('uid')
                        check_cols = [
                            'tanggal_checkup','tinggi','berat','lingkar_perut','bmi','umur',
                            'gula_darah_puasa','gula_darah_sewaktu','cholesterol','asam_urat',
                            'tekanan_darah','derajat_kesehatan','status','tanggal_MCU','expired_MCU','bmi_category'
                        ]
                        for col in check_cols:
                            if col not in df.columns:
                                df[col] = None
                        df[check_cols] = None
                        for uid, row in latest_in_range.iterrows():
                            idxs = df.index[df['uid'].astype(str) == str(uid)].tolist()
                            for idx in idxs:
                                for col in check_cols:
                                    if col in latest_in_range.columns:
                                        df.at[idx, col] = row.get(col, None)
            except Exception:
                # If filter fails, fallback to latest
                df = df_latest.copy()

        # Build Excel bytes
        excel_bytes = build_checkup_excel(df)
        response = HttpResponse(
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="medical_checkup_data.xlsx"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Failed to export data: {e}"
        return redirect(reverse("manager:upload_export") + "?submenu=export_data")

@require_http_methods(["GET"]) 
def export_master_karyawan_excel(request):
    """Export master karyawan data to Excel (schema matches uploaded master XLS)."""
    # Auth guard for Manager
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        df = get_employees().copy()
        if df is None or df.empty:
            request.session["warning_message"] = "belum ada data karyawan untuk diekspor"
            return redirect(reverse("manager:upload_export") + "?submenu=export_data")

        # Columns to match master upload schema
        cols_order = [
            "nama", "jabatan", "lokasi", "tanggal_lahir",
            "tanggal_MCU", "expired_MCU",
            "derajat_kesehatan", "tinggi", "berat", "bmi", "bmi_category",
        ]
        for col in cols_order:
            if col not in df.columns:
                df[col] = None
        df_export = df[cols_order]

        # Format dates to dd/mm/yy for consistency with uploads
        for col in ["tanggal_lahir", "tanggal_MCU", "expired_MCU"]:
            if col in df_export.columns:
                try:
                    df_export[col] = pd.to_datetime(df_export[col], errors='coerce').dt.strftime('%d/%m/%y')
                except Exception:
                    pass

        # Write to Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Master Karyawan")
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="master_karyawan.xlsx"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Failed to export master data: {e}"
        return redirect(reverse("manager:upload_export") + "?submenu=export_data")

@require_http_methods(["GET"])
def export_checkup_history_by_uid(request, uid):
    """Export the CURRENT displayed history medical checkup DataFrame (no new computation) for the specified UID."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    try:
        from core.core_models import Karyawan
        if not Karyawan.objects.filter(uid=uid).exists():
            request.session['error_message'] = f"UID {uid} tidak ditemukan."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

        # Load raw checkups for UID
        checkups = get_medical_checkups_by_uid(uid)
        if checkups is None or checkups.empty:
            request.session['warning_message'] = "Tidak ada data checkup untuk UID ini."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

        # Build the same 'history_dashboard' style rows used by the UI
        employees_df = get_employees()
        employee_clean = None
        if employees_df is not None and not employees_df.empty:
            try:
                df_uid = employees_df[employees_df['uid'].astype(str) == str(uid)]
                if not df_uid.empty:
                    employee_clean = df_uid.iloc[0].to_dict()
            except Exception:
                pass

        df_hist2 = checkups.copy()
        if "uid_id" in df_hist2.columns and "uid" not in df_hist2.columns:
            df_hist2 = df_hist2.rename(columns={"uid_id": "uid"})
        if "tanggal_checkup" in df_hist2.columns:
            df_hist2["tanggal_checkup"] = pd.to_datetime(df_hist2["tanggal_checkup"], errors="coerce")
        df_hist2 = df_hist2.sort_values("tanggal_checkup", ascending=False)

        emp_nama = (employee_clean or {}).get('nama')
        emp_jabatan = (employee_clean or {}).get('jabatan')
        emp_lokasi = (employee_clean or {}).get('lokasi')
        # Format tanggal lahir
        emp_tanggal_lahir = None
        try:
            tl_raw = (employee_clean or {}).get('tanggal_lahir')
            tl_dt = pd.to_datetime(tl_raw, errors='coerce')
            emp_tanggal_lahir = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
        except Exception:
            pass
        # MCU dates
        emp_tanggal_mcu = None
        emp_expired_mcu = None
        try:
            mcu_dt = pd.to_datetime((employee_clean or {}).get('tanggal_MCU'), errors='coerce')
            emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
        except Exception:
            pass
        try:
            exp_dt = pd.to_datetime((employee_clean or {}).get('expired_MCU'), errors='coerce')
            emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
        except Exception:
            pass
        # umur and employee BMI fallback
        try:
            umur_val = (employee_clean or {}).get('umur', None)
        except Exception:
            umur_val = None
        try:
            emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
        except Exception:
            emp_bmi = None

        rows = []
        for _, row in df_hist2.iterrows():
            tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
            berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
            bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
            # BMI fallback: no autocalc; use employee BMI if row BMI missing/zero
            try:
                if ((bmi_n is None) or (isinstance(bmi_n, float) and pd.isna(bmi_n)) or (float(bmi_n) == 0.0)) and pd.notna(emp_bmi):
                    bmi_n = float(emp_bmi)
            except Exception:
                pass
            lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
            gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
            tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
            tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

            # Status (match UI)
            status_val = compute_status({
                'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                'cholesterol': chol_n if pd.notna(chol_n) else 0,
                'asam_urat': asam_n if pd.notna(asam_n) else 0,
                'bmi': bmi_n if pd.notna(bmi_n) else 0,
            })

            # Derajat Kesehatan with fallback
            dk_val = row.get('derajat_kesehatan', None)
            try:
                if dk_val is None or (isinstance(dk_val, float) and pd.isna(dk_val)) or (isinstance(dk_val, str) and not dk_val.strip()):
                    dk_val = (employee_clean or {}).get('derajat_kesehatan')
            except Exception:
                pass

            # BMI Category: prefer row, fallback to employee, else compute from BMI
            bmi_cat_val = row.get('bmi_category', None)
            def _is_blank(x):
                return (x is None) or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not str(x).strip())
            if _is_blank(bmi_cat_val):
                bmi_cat_val = (employee_clean or {}).get('bmi_category', None)
            if _is_blank(bmi_cat_val):
                bmi_source = bmi_n if pd.notna(bmi_n) else (emp_bmi if pd.notna(emp_bmi) else None)
                bmi_cat_val = compute_bmi_category(bmi_source)

            rows.append({
                'UID': str(row.get('uid', uid)),
                'Nama': emp_nama,
                'Jabatan': emp_jabatan,
                'Lokasi': emp_lokasi,
                'Tanggal Lahir': emp_tanggal_lahir,
                'Umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                'BMI': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else None,
                'BMI Category': str(bmi_cat_val) if bmi_cat_val is not None else None,
                'Tanggal Checkup': tanggal_str,
                'Lingkar Perut': float(lp_n) if pd.notna(lp_n) else None,
                'Gula Darah Puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                'Gula Darah Sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                'Cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                'Asam Urat': float(asam_n) if pd.notna(asam_n) else None,
                'Tekanan Darah': row.get('tekanan_darah', None),
                'Derajat Kesehatan': str(dk_val) if dk_val is not None else None,
                'Tanggal MCU': emp_tanggal_mcu,
                'Expired MCU': emp_expired_mcu,
                'Status': status_val,
            })

        import pandas as _pd
        df_export = _pd.DataFrame(rows)
        columns_order = [
            'UID','Nama','Jabatan','Lokasi','Tanggal Lahir','Umur','BMI','BMI Category','Tanggal Checkup','Lingkar Perut','Gula Darah Puasa','Gula Darah Sewaktu','Cholesterol','Asam Urat','Tekanan Darah','Derajat Kesehatan','Tanggal MCU','Expired MCU','Status'
        ]

        excel_bytes = build_checkup_excel(df_export, enrich=False, columns=columns_order)
        filename = f"checkup_history_{uid}.xlsx"
        response = HttpResponse(excel_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor riwayat checkup: {e}"
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"])
def export_checkup_row(request, uid, checkup_id):
    """Export a single medical checkup row for the specified UID, restricting to visible columns (no gestational_diabetes)."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    try:
        from core.core_models import Checkup
        qs = Checkup.objects.filter(checkup_id=checkup_id, uid_id=uid)
        if not qs.exists():
            request.session['error_message'] = "Checkup tidak ditemukan untuk UID terkait."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")
        import pandas as pd
        df = pd.DataFrame(list(qs.values()))
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}

        # Prepare a single-row export matching the history UID export columns
        from core.helpers import compute_status
        rows = []
        for _, row in df.iterrows():
            # Basic fields and conversions
            tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
            berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
            bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
            lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
            gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
            tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
            tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

            # Employee context and fallbacks
            emp_nama = employee_clean.get('nama')
            emp_jabatan = employee_clean.get('jabatan')
            emp_lokasi = employee_clean.get('lokasi')
            try:
                tl_dt = pd.to_datetime(employee_clean.get('tanggal_lahir'), errors='coerce')
                emp_tanggal_lahir = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
            except Exception:
                emp_tanggal_lahir = None
            try:
                mcu_dt = pd.to_datetime(employee_clean.get('tanggal_MCU'), errors='coerce')
                emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
            except Exception:
                emp_tanggal_mcu = None
            try:
                exp_dt = pd.to_datetime(employee_clean.get('expired_MCU'), errors='coerce')
                emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
            except Exception:
                emp_expired_mcu = None
            umur_val = employee_clean.get('umur', None)
            emp_bmi = pd.to_numeric(employee_clean.get('bmi', None), errors='coerce')

            # Status value to match UI thresholds
            status_val = compute_status({
                'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                'cholesterol': chol_n if pd.notna(chol_n) else 0,
                'asam_urat': asam_n if pd.notna(asam_n) else 0,
                'bmi': bmi_n if pd.notna(bmi_n) else (float(emp_bmi) if pd.notna(emp_bmi) else 0),
            })

            # BMI Category from available BMI source (row or employee)
            bmi_cat_val = row.get('bmi_category', None)
            def _is_blank(x):
                return (x is None) or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not str(x).strip())
            if _is_blank(bmi_cat_val):
                bmi_cat_val = (employee_clean or {}).get('bmi_category', None)
            if _is_blank(bmi_cat_val):
                from core.helpers import compute_bmi_category
                bmi_source = bmi_n if pd.notna(bmi_n) and float(bmi_n) != 0.0 else (emp_bmi if pd.notna(emp_bmi) else None)
                bmi_cat_val = compute_bmi_category(bmi_source)

            # Build row with visible columns only
            rows.append({
                'UID': str(row.get('uid', uid)),
                'Nama': emp_nama,
                'Jabatan': emp_jabatan,
                'Lokasi': emp_lokasi,
                'Tanggal Lahir': emp_tanggal_lahir,
                'Umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                'BMI': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else (float(emp_bmi) if pd.notna(emp_bmi) else None),
                'BMI Category': str(bmi_cat_val) if bmi_cat_val is not None else None,
                'Tanggal Checkup': tanggal_str,
                'Lingkar Perut': float(lp_n) if pd.notna(lp_n) else None,
                'Gula Darah Puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                'Gula Darah Sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                'Cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                'Asam Urat': float(asam_n) if pd.notna(asam_n) else None,
                'Tekanan Darah': row.get('tekanan_darah', None),
                'Derajat Kesehatan': row.get('derajat_kesehatan', None) or employee_clean.get('derajat_kesehatan', None),
                'Tanggal MCU': emp_tanggal_mcu,
                'Expired MCU': emp_expired_mcu,
                'Status': status_val,
            })

        import pandas as _pd
        df_export = _pd.DataFrame(rows)
        columns_order = [
            'UID','Nama','Jabatan','Lokasi','Tanggal Lahir','Umur','BMI','BMI Category','Tanggal Checkup','Lingkar Perut','Gula Darah Puasa','Gula Darah Sewaktu','Cholesterol','Asam Urat','Tekanan Darah','Derajat Kesehatan','Tanggal MCU','Expired MCU','Status'
        ]

        excel_bytes = build_checkup_excel(df_export, enrich=False, columns=columns_order)
        filename = f"checkup_{checkup_id}.xlsx"
        response = HttpResponse(excel_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor data checkup: {e}"
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"])
def export_checkup_history_by_uid_pdf(request, uid):
    """Export the CURRENT displayed history medical checkup DataFrame for the specified UID as PDF, with vertical/portrait layout."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    try:
        from core.core_models import Karyawan
        if not Karyawan.objects.filter(uid=uid).exists():
            request.session['error_message'] = f"UID {uid} tidak ditemukan."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

        checkups = get_medical_checkups_by_uid(uid)
        if checkups is None or checkups.empty:
            request.session['warning_message'] = "Tidak ada data checkup untuk UID ini."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

        employees_df = get_employees()
        employee_clean = None
        if employees_df is not None and not employees_df.empty:
            try:
                df_uid = employees_df[employees_df['uid'].astype(str) == str(uid)]
                if not df_uid.empty:
                    employee_clean = df_uid.iloc[0].to_dict()
            except Exception:
                pass

        df_hist2 = checkups.copy()
        if "uid_id" in df_hist2.columns and "uid" not in df_hist2.columns:
            df_hist2 = df_hist2.rename(columns={"uid_id": "uid"})
        if "tanggal_checkup" in df_hist2.columns:
            df_hist2["tanggal_checkup"] = pd.to_datetime(df_hist2["tanggal_checkup"], errors="coerce")
        df_hist2 = df_hist2.sort_values("tanggal_checkup", ascending=False)

        emp_nama = (employee_clean or {}).get('nama')
        emp_jabatan = (employee_clean or {}).get('jabatan')
        emp_lokasi = (employee_clean or {}).get('lokasi')
        emp_tanggal_lahir = None
        try:
            tl_raw = (employee_clean or {}).get('tanggal_lahir')
            tl_dt = pd.to_datetime(tl_raw, errors='coerce')
            emp_tanggal_lahir = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
        except Exception:
            pass
        emp_tanggal_mcu = None
        emp_expired_mcu = None
        try:
            mcu_dt = pd.to_datetime((employee_clean or {}).get('tanggal_MCU'), errors='coerce')
            emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
        except Exception:
            pass
        try:
            exp_dt = pd.to_datetime((employee_clean or {}).get('expired_MCU'), errors='coerce')
            emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
        except Exception:
            pass
        try:
            umur_val = (employee_clean or {}).get('umur', None)
        except Exception:
            umur_val = None
        try:
            emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
        except Exception:
            emp_bmi = None

        rows = []
        for _, row in df_hist2.iterrows():
            bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
            # BMI fallback: no autocalc; use employee BMI if row BMI missing/zero
            try:
                if ((bmi_n is None) or (isinstance(bmi_n, float) and pd.isna(bmi_n)) or (float(bmi_n) == 0.0)) and pd.notna(emp_bmi):
                    bmi_n = float(emp_bmi)
            except Exception:
                pass
            lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
            gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
            tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
            tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

            status_val = compute_status({
                'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                'cholesterol': chol_n if pd.notna(chol_n) else 0,
                'asam_urat': asam_n if pd.notna(asam_n) else 0,
                'bmi': bmi_n if pd.notna(bmi_n) else 0,
            })

            bmi_cat_val = row.get('bmi_category', None)
            def _is_blank(x):
                return (x is None) or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not str(x).strip())
            if _is_blank(bmi_cat_val):
                bmi_cat_val = (employee_clean or {}).get('bmi_category', None)
            if _is_blank(bmi_cat_val):
                bmi_source = bmi_n if pd.notna(bmi_n) else (emp_bmi if pd.notna(emp_bmi) else None)
                bmi_cat_val = compute_bmi_category(bmi_source)

            rows.append({
                'UID': str(row.get('uid', uid)),
                'Nama': emp_nama,
                'Jabatan': emp_jabatan,
                'Lokasi': emp_lokasi,
                'Tanggal Lahir': emp_tanggal_lahir,
                'Umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                'BMI': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else None,
                'BMI Category': str(bmi_cat_val) if bmi_cat_val is not None else None,
                'Tanggal Checkup': tanggal_str,
                'Lingkar Perut': float(lp_n) if pd.notna(lp_n) else None,
                'Gula Darah Puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                'Gula Darah Sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                'Cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                'Asam Urat': float(asam_n) if pd.notna(asam_n) else None,
                'Tekanan Darah': row.get('tekanan_darah', None),
                'Derajat Kesehatan': row.get('derajat_kesehatan', None) or (employee_clean or {}).get('derajat_kesehatan', None),
                'Tanggal MCU': emp_tanggal_mcu,
                'Expired MCU': emp_expired_mcu,
                'Status': status_val,
            })

        import pandas as _pd
        df_export = _pd.DataFrame(rows)
        columns_order = [
            'UID','Nama','Jabatan','Lokasi','Tanggal Lahir','Umur','BMI','BMI Category','Tanggal Checkup','Lingkar Perut','Gula Darah Puasa','Gula Darah Sewaktu','Cholesterol','Asam Urat','Tekanan Darah','Derajat Kesehatan','Tanggal MCU','Expired MCU','Status'
        ]

        pdf_bytes = build_checkup_pdf(
            df_export,
            enrich=False,
            columns=columns_order,
            orientation='portrait',
            max_cols_per_table=8,
            title_text='Mini-MCU Record',
            list_style=True,
        )
        filename = f"checkup_history_{uid}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor riwayat checkup (PDF): {e}"
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"])
def export_checkup_row_pdf(request, uid, checkup_id):
    """Export a single medical checkup row for the specified UID as PDF, restricting to visible columns (no gestational_diabetes)."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    try:
        from core.core_models import Checkup
        qs = Checkup.objects.filter(checkup_id=checkup_id, uid_id=uid)
        if not qs.exists():
            request.session['error_message'] = "Checkup tidak ditemukan untuk UID terkait."
            return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")
        import pandas as pd
        df = pd.DataFrame(list(qs.values()))
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}

        # Build row with visible columns only (same as UID history export)
        from core.helpers import compute_status, compute_bmi_category
        rows = []
        for _, row in df.iterrows():
            bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
            lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
            gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
            tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
            tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

            # Employee context
            emp_nama = employee_clean.get('nama')
            emp_jabatan = employee_clean.get('jabatan')
            emp_lokasi = employee_clean.get('lokasi')
            try:
                tl_dt = pd.to_datetime(employee_clean.get('tanggal_lahir'), errors='coerce')
                emp_tanggal_lahir = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
            except Exception:
                emp_tanggal_lahir = None
            try:
                mcu_dt = pd.to_datetime(employee_clean.get('tanggal_MCU'), errors='coerce')
                emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
            except Exception:
                emp_tanggal_mcu = None
            try:
                exp_dt = pd.to_datetime(employee_clean.get('expired_MCU'), errors='coerce')
                emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
            except Exception:
                emp_expired_mcu = None
            umur_val = employee_clean.get('umur', None)
            emp_bmi = pd.to_numeric(employee_clean.get('bmi', None), errors='coerce')

            status_val = compute_status({
                'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                'cholesterol': chol_n if pd.notna(chol_n) else 0,
                'asam_urat': asam_n if pd.notna(asam_n) else 0,
                'bmi': bmi_n if pd.notna(bmi_n) else (float(emp_bmi) if pd.notna(emp_bmi) else 0),
            })

            bmi_cat_val = row.get('bmi_category', None)
            def _is_blank(x):
                return (x is None) or (isinstance(x, float) and pd.isna(x)) or (isinstance(x, str) and not str(x).strip())
            if _is_blank(bmi_cat_val):
                bmi_cat_val = (employee_clean or {}).get('bmi_category', None)
            if _is_blank(bmi_cat_val):
                bmi_source = bmi_n if pd.notna(bmi_n) and float(bmi_n) != 0.0 else (emp_bmi if pd.notna(emp_bmi) else None)
                bmi_cat_val = compute_bmi_category(bmi_source)

            rows.append({
                'UID': str(row.get('uid', uid)),
                'Nama': emp_nama,
                'Jabatan': emp_jabatan,
                'Lokasi': emp_lokasi,
                'Tanggal Lahir': emp_tanggal_lahir,
                'Umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                'BMI': float(bmi_n) if pd.notna(bmi_n) and float(bmi_n) != 0.0 else (float(emp_bmi) if pd.notna(emp_bmi) else None),
                'BMI Category': str(bmi_cat_val) if bmi_cat_val is not None else None,
                'Tanggal Checkup': tanggal_str,
                'Lingkar Perut': float(lp_n) if pd.notna(lp_n) else None,
                'Gula Darah Puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                'Gula Darah Sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                'Cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                'Asam Urat': float(asam_n) if pd.notna(asam_n) else None,
                'Tekanan Darah': row.get('tekanan_darah', None),
                'Derajat Kesehatan': row.get('derajat_kesehatan', None) or (employee_clean or {}).get('derajat_kesehatan', None),
                'Tanggal MCU': emp_tanggal_mcu,
                'Expired MCU': emp_expired_mcu,
                'Status': status_val,
            })

        import pandas as _pd
        df_export = _pd.DataFrame(rows)
        columns_order = [
            'UID','Nama','Jabatan','Lokasi','Tanggal Lahir','Umur','BMI','BMI Category','Tanggal Checkup','Lingkar Perut','Gula Darah Puasa','Gula Darah Sewaktu','Cholesterol','Asam Urat','Tekanan Darah','Derajat Kesehatan','Tanggal MCU','Expired MCU','Status'
        ]

        pdf_bytes = build_checkup_pdf(
            df_export,
            enrich=False,
            columns=columns_order,
            orientation='portrait',
            max_cols_per_table=8,
            title_text='Mini-MCU Record',
            list_style=True,
        )
        filename = f"checkup_{checkup_id}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor data checkup (PDF): {e}"
        return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=history")



# users_interface/manager/manager_views.py
import io
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods
import pandas as pd
from datetime import datetime
from django.conf import settings
import base64
from users_ui.qr.qr_utils import generate_qr_bytes
import uuid
from utils.validators import safe_date, validate_lokasi, normalize_string, safe_float

from core.queries import (
    get_users,
    add_user,
    get_employees,
    add_employee_if_exists,
    reset_karyawan_data,
    get_employee_by_uid,
    get_medical_checkups_by_uid,
    insert_medical_checkup,
    save_manual_karyawan_edits,
    get_latest_medical_checkup,
    delete_user_by_id,
    count_users_by_role,
    reset_user_password as core_reset_user_password,
    get_user_by_username,
    change_username as core_change_username,
    write_checkup_upload_log,
    get_checkup_upload_history,
)

from core.helpers import (
    get_all_lokasi,
    sanitize_df_for_display,
    get_dashboard_checkup_data,
    get_active_menu_for_view,
    compute_bmi_category,
)
from core import excel_parser, checkup_uploader
from utils.export_utils import generate_karyawan_template_excel, export_checkup_data_excel as build_checkup_excel
from users_ui.qr.qr_views import qr_detail_view, qr_bulk_download_view

# -------------------------
# Tab 1: Dashboard
# -------------------------
def dashboard(request):
    """
    Manager dashboard showing:
    - Total users by role
    - Recent medical checkups
    - Quick stats
    """
    if not request.session.get("authenticated") or request.session.get("user_role") not in ["Manager", "Tenaga Kesehatan"]:
        return redirect("accounts:login")

    active_menu = "dashboard"  # Changed to match the mapping in get_active_menu_for_view
    active_submenu = request.GET.get('submenu', 'data')
    # Path-based override to allow nurse routes to open grafik tabs directly
    path_str = request.path or ''
    forced_subtab = None
    if 'grafik/kesehatan' in path_str or 'dashboard/grafik/kesehatan' in path_str:
        active_submenu = 'grafik'
        forced_subtab = 'grafik_kesehatan'
    elif 'grafik/well_unwell' in path_str or 'dashboard/grafik/well_unwell' in path_str:
        active_submenu = 'grafik'
        forced_subtab = 'well_unwell'

    # Grafik JSON API: return processed data for chart overhaul
    if active_submenu == 'grafik' and request.GET.get('grafik_json') == '1':
        # Build JSON payload based on month range and UID filters
        try:
            df_json = load_checkups()
        except Exception:
            df_json = pd.DataFrame()
        # Fallback to latest dashboard data if historical checkups are unavailable
        if not hasattr(df_json, 'empty') or df_json.empty:
            try:
                df_json = get_dashboard_checkup_data()
            except Exception:
                df_json = pd.DataFrame()
        now = pd.Timestamp.now()
        default_end_month_dt = pd.Timestamp(year=now.year, month=now.month, day=1)
        default_start_month_dt = default_end_month_dt - pd.offsets.DateOffset(months=5)
        # Choose date column (fallback to synthetic current month if absent)
        date_col = None
        if not df_json.empty and 'tanggal_MCU' in df_json.columns:
            df_json['tanggal_MCU'] = pd.to_datetime(df_json['tanggal_MCU'], errors='coerce')
            date_col = 'tanggal_MCU'
        elif not df_json.empty and 'tanggal_checkup' in df_json.columns:
            df_json['tanggal_checkup'] = pd.to_datetime(df_json['tanggal_checkup'], errors='coerce')
            date_col = 'tanggal_checkup'
        else:
            # Synthesize a month column using current month so aggregated view still works
            df_json = df_json.copy()
            df_json['synthetic_month'] = now.strftime('%Y-%m')
        # Ensure status
        try:
            if 'status' not in df_json.columns or df_json['status'].isna().any():
                df_json['status'] = df_json.apply(compute_status, axis=1)
        except Exception:
            pass
        # Parse tekanan darah sistole when needed
        def parse_systolic(td_val):
            try:
                if pd.isna(td_val):
                    return None
                s = str(td_val)
                if '/' in s:
                    return float(s.split('/')[0])
                return float(s)
            except Exception:
                return None
        # Filters
        uid = request.GET.get('uid', 'all')
        start_month = request.GET.get('start_month')
        end_month = request.GET.get('end_month')
        start_dt = pd.to_datetime(start_month + '-01', errors='coerce') if start_month else default_start_month_dt
        end_dt = pd.to_datetime(end_month + '-01', errors='coerce') if end_month else default_end_month_dt
        # Filter by month range (inclusive)
        if date_col:
            df_json = df_json[(df_json[date_col] >= start_dt) & (df_json[date_col] <= end_dt)]
        # Individual vs aggregate
        if uid and uid != 'all':
            df_u = df_json[df_json['uid'].astype(str) == str(uid)].copy()
            if df_u.empty:
                return JsonResponse({'mode':'individual','x_dates':[],'series':{'gula_darah_puasa':[],'gula_darah_sewaktu':[],'tekanan_darah_sistole':[],'lingkar_perut':[],'cholesterol':[],'asam_urat':[],'bmi':[]},'summary':{'total_employees':0,'well_count':0,'unwell_count':0}})
            # Sort by date
            if date_col:
                df_u = df_u.sort_values(by=date_col)
                x_dates = df_u[date_col].dt.strftime('%Y-%m-%d').tolist()
            else:
                x_dates = []
            series = {
                'gula_darah_puasa': df_u.get('gula_darah_puasa', pd.Series(dtype='float64')).tolist(),
                'gula_darah_sewaktu': df_u.get('gula_darah_sewaktu', pd.Series(dtype='float64')).tolist(),
                'tekanan_darah_sistole': df_u.get('tekanan_darah', pd.Series(dtype='object')).apply(parse_systolic).tolist() if 'tekanan_darah' in df_u.columns else [],
                'lingkar_perut': df_u.get('lingkar_perut', pd.Series(dtype='float64')).tolist(),
                'cholesterol': df_u.get('cholesterol', pd.Series(dtype='float64')).tolist(),
                'asam_urat': df_u.get('asam_urat', pd.Series(dtype='float64')).tolist(),
                'bmi': df_u.get('bmi', pd.Series(dtype='float64')).tolist(),
            }
            # Summary from latest row
            latest_row = df_u.iloc[-1]
            total_employees = 1
            well_count = 1 if str(latest_row.get('status')) == 'Well' else 0
            unwell_count = 1 if str(latest_row.get('status')) == 'Unwell' else 0
            return JsonResponse({'mode':'individual','x_dates':x_dates,'series':series,'summary':{'total_employees':total_employees,'well_count':well_count,'unwell_count':unwell_count}})
        else:
            # Multiline time-series across multiple karyawan for selected parameters
            df_filt = df_json.copy()
            if df_filt.empty or not date_col:
                return JsonResponse({'mode':'multiline','x_dates':[],'employees':[],'series_by_employee':{}})
            # Build unified date axis within the filtered range
            df_filt = df_filt.dropna(subset=[date_col])
            df_filt = df_filt.sort_values(by=[date_col, 'uid'])
            x_dates = sorted(df_filt[date_col].dt.strftime('%Y-%m-%d').unique().tolist())
            # Employee display names
            # Prefer 'nama' if available; otherwise fallback to 'UID {uid}'
            employees = []
            try:
                # Ensure 'nama' column exists
                if 'nama' not in df_filt.columns:
                    df_filt['nama'] = df_filt['uid'].astype(str).apply(lambda u: f'UID {u}')
            except Exception:
                pass
            # Build series per employee, aligned to x_dates
            series_by_employee = {}
            uids = [str(u) for u in df_filt['uid'].dropna().astype(str).unique().tolist()]
            for u in uids:
                df_u = df_filt[df_filt['uid'].astype(str) == u].copy()
                df_u = df_u.sort_values(by=[date_col])
                # Map date -> row for fast lookup
                date_map = {}
                for _, row in df_u.iterrows():
                    try:
                        key = pd.to_datetime(row[date_col]).strftime('%Y-%m-%d')
                    except Exception:
                        key = None
                    if key:
                        date_map[key] = row
                # Helpers
                def to_float_safe(val):
                    try:
                        return float(val)
                    except Exception:
                        return None
                def parse_systolic(val):
                    try:
                        if pd.isna(val):
                            return None
                        s = str(val)
                        if '/' in s:
                            return float(s.split('/')[0])
                        return float(s)
                    except Exception:
                        return None
                # Build aligned arrays
                s_gp = []
                s_gs = []
                s_td = []
                s_lp = []
                s_ch = []
                s_au = []
                s_bmi = []
                for d in x_dates:
                    row = date_map.get(d)
                    if row is None:
                        s_gp.append(None); s_gs.append(None); s_td.append(None); s_lp.append(None); s_ch.append(None); s_au.append(None); s_bmi.append(None)
                    else:
                        s_gp.append(to_float_safe(row.get('gula_darah_puasa')))
                        s_gs.append(to_float_safe(row.get('gula_darah_sewaktu')))
                        s_td.append(parse_systolic(row.get('tekanan_darah')))
                        s_lp.append(to_float_safe(row.get('lingkar_perut')))
                        s_ch.append(to_float_safe(row.get('cholesterol')))
                        s_au.append(to_float_safe(row.get('asam_urat')))
                        s_bmi.append(to_float_safe(row.get('bmi')))
                series_by_employee[u] = {
                    'nama': str(df_u.iloc[-1]['nama']) if not df_u.empty else f'UID {u}',
                    'gula_darah_puasa': s_gp,
                    'gula_darah_sewaktu': s_gs,
                    'tekanan_darah_sistole': s_td,
                    'lingkar_perut': s_lp,
                    'cholesterol': s_ch,
                    'asam_urat': s_au,
                    'bmi': s_bmi,
                }
                employees.append({'uid': u, 'nama': series_by_employee[u]['nama']})
            return JsonResponse({'mode':'multiline','x_dates':x_dates,'employees':employees,'series_by_employee':series_by_employee})

    # Get the DataFrame
    df = get_dashboard_checkup_data()

    # Ensure expected columns exist to avoid KeyError after backup restores
    for col in ['lokasi', 'status', 'nama', 'jabatan']:
        if col not in df.columns:
            df[col] = ''

    # Normalize 'jabatan' to remove duplicates caused by spacing/casing differences
    if not df.empty and 'jabatan' in df.columns:
        df['jabatan_clean'] = df['jabatan'].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
        df['jabatan_key'] = df['jabatan_clean'].str.lower()
    else:
        df['jabatan_clean'] = ''
        df['jabatan_key'] = ''
    
    # Get available locations for dropdowns
    # 1) From dashboard (employees-based) data
    all_lokasi = sorted([loc for loc in df['lokasi'].dropna().unique().tolist() if str(loc).strip()])
    # 2) From checkups data to align with grafik JSON source
    try:
        chk_df = load_checkups()
        if chk_df is not None and hasattr(chk_df, 'empty') and not chk_df.empty:
            chk_col = None
            if 'lokasi' in chk_df.columns:
                chk_col = 'lokasi'
            elif 'Lokasi Kerja' in chk_df.columns:
                chk_col = 'Lokasi Kerja'
            if chk_col:
                checkup_lokasi = [loc for loc in chk_df[chk_col].dropna().unique().tolist() if str(loc).strip()]
            else:
                checkup_lokasi = []
        else:
            checkup_lokasi = []
    except Exception:
        checkup_lokasi = []
    # 3) Use the union (ensures dropdown reflects locations present in checkups JSON and employee list)
    available_lokasi_union = sorted(set(all_lokasi) | set(checkup_lokasi))
    
    # Make an unfiltered copy for card totals (keep cards constant when filters change)
    df_all = df.copy()
    
    # Get filter parameters
    filters = {
        'nama': request.GET.get('nama', ''),
        'jabatan': request.GET.get('jabatan', ''),
        'lokasi': request.GET.get('lokasi', ''),  # Single location selection
        'status': request.GET.get('status', ''),  # Well/Unwell
        'expiry': request.GET.get('expiry', ''),  # Expired/Almost Expired filter
    }

    # Apply filters
    # [DEBUG] Data count before applying filters (including lokasi)
    try:
        print("[DEBUG] Data count before filter:", len(df))
    except Exception:
        pass
    if filters['nama']:
        df = df[df['nama'].astype(str).str.contains(filters['nama'], case=False, na=False)]
    if filters['jabatan']:
        # Normalize filter to match jabatan_key
        filt_clean = ' '.join(filters['jabatan'].split()).strip().lower()
        df = df[df['jabatan_key'] == filt_clean]
    if filters['lokasi']:  # Filter by selected location
        df = df[df['lokasi'] == filters['lokasi']]
    # [DEBUG] Data count after lokasi filter (or same as before when lokasi not provided)
    try:
        print("[DEBUG] Data count after lokasi filter:", len(df))
    except Exception:
        pass
    if filters['status']:  # Filter by Well/Unwell status
        df = df[df['status'] == filters['status']]
    # Date range filter removed: always showing latest checkup data

    # Compute MCU expiry flags for styling (expired = red, within 60 days = yellow)
    try:
        if 'expired_MCU' in df.columns:
            expired_dt = pd.to_datetime(df['expired_MCU'], format='%d/%m/%y', errors='coerce')
            today = pd.Timestamp.today().normalize()
            warn_deadline = today + pd.Timedelta(days=60)
            df['mcu_is_expired'] = expired_dt.notna() & (expired_dt < today)
            df['mcu_is_warning'] = expired_dt.notna() & (expired_dt >= today) & (expired_dt <= warn_deadline)
        else:
            df['mcu_is_expired'] = False
            df['mcu_is_warning'] = False
    except Exception:
        # Fallback to avoid breaking dashboard rendering
        df['mcu_is_expired'] = False
        df['mcu_is_warning'] = False

    # Apply expiry filter after computing flags
    if filters.get('expiry'):
        val = str(filters['expiry']).lower()
        if val == 'expired':
            df = df[df['mcu_is_expired']]
        elif val in ('warning', 'almost', 'almost_expired', 'almost-expired'):
            df = df[df['mcu_is_warning']]
    
    # Get unique values for dropdowns from filtered data
    # Build a mapping of normalized key -> cleaned display value to dedupe case/spacing
    jabatan_map = {}
    if not df.empty and 'jabatan_key' in df.columns and 'jabatan_clean' in df.columns:
        for key, val in zip(df['jabatan_key'], df['jabatan_clean']):
            if key and key not in jabatan_map:
                jabatan_map[key] = val
    available_jabatan = sorted(jabatan_map.values())
    # Use union of employee and checkup locations for lokasi dropdown
    available_lokasi = available_lokasi_union
    # Status options are fixed
    available_status = ['Well', 'Unwell']
    
    # Calculate Well/Unwell counts from unfiltered data
    total_well = int((df_all['status'] == 'Well').sum()) if not df_all.empty else 0
    total_unwell = int((df_all['status'] == 'Unwell').sum()) if not df_all.empty else 0
    
    # Pagination
    items_per_page = 10
    total_items = len(df)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    current_page = int(request.GET.get('page', 1))
    current_page = max(1, min(current_page, total_pages))  # Ensure page is within bounds
    
    start_index = (current_page - 1) * items_per_page
    end_index = start_index + items_per_page
    
    # Slice the DataFrame for current page
    df_page = df.iloc[start_index:end_index]
    # Sanitize page slice to avoid NaT/UUID issues in templates
    try:
        df_page = sanitize_df_for_display(df_page)
    except Exception:
        pass
    
    # Convert DataFrame to list of dictionaries for template
    employees = df_page.to_dict('records')
    
    # Get dashboard statistics
    users_df = get_users()
    checkups_today = 0  # Will be updated when checkup data is uploaded
    active_nurses = len(users_df[users_df['role'] == 'nurse']) if not users_df.empty else 0
    pending_reviews = 0  # Will be updated when checkup data is uploaded

    # Grafik filter defaults and UID options for new Grafik tab
    # Always show all employees (not just those with checkup data) with names
    available_employees = []
    try:
        # Get all employees from master data
        df_emps = get_employees()
        if hasattr(df_emps, 'empty') and not df_emps.empty and 'uid' in df_emps.columns and 'nama' in df_emps.columns:
            for _, row in df_emps.iterrows():
                uid = str(row['uid']) if pd.notna(row['uid']) else ''
                nama = str(row['nama']) if pd.notna(row['nama']) else f'UID {uid}'
                if uid:
                    available_employees.append({'uid': uid, 'nama': nama})
    except Exception:
        pass
    
    # Sort by name for better UX
    available_employees = sorted(available_employees, key=lambda x: x['nama'].lower())
    now2 = pd.Timestamp.now()
    default_end_month = now2.strftime('%Y-%m')
    default_start_month = (now2 - pd.offsets.DateOffset(months=5)).strftime('%Y-%m')

    # Initialize empty chart data since we don't have checkup data yet
    checkup_dates = []
    checkup_counts = []
    dept_names = []
    dept_counts = []

    if not df.empty and 'jabatan' in df.columns:
        dept_counts_series = df['jabatan'].value_counts()
        dept_names = dept_counts_series.index.tolist()
        dept_counts = dept_counts_series.values.tolist()
    
    # Compute latest upload info for tooltip
    latest_check_date_disp = None
    if 'tanggal_checkup' in df_all.columns and not df_all.empty:
        dt_series = pd.to_datetime(df_all['tanggal_checkup'], errors='coerce')
        dt_max = dt_series.max()
        # Format date as dd/mm/yy per request
        latest_check_date_disp = dt_max.strftime('%d/%m/%y') if pd.notnull(dt_max) else None
    try:
        hist_df = get_checkup_upload_history()
        if hasattr(hist_df, 'empty') and not hist_df.empty:
            latest = hist_df.iloc[0]
            ts_val = latest.get('timestamp', None)
            # Format timestamp as dd/mm/yy HH:MM per request
            ts_disp = ts_val.strftime('%d/%m/%y %H:%M') if pd.notnull(ts_val) else '-'
            filename = latest.get('filename', '')
            inserted = int(latest.get('inserted', 0))
            skipped = int(latest.get('skipped_count', 0))
            if latest_check_date_disp:
                latest_checkup_display = f"{latest_check_date_disp} • {filename} • Inserted: {inserted} • Skipped: {skipped}"
            else:
                latest_checkup_display = f"{ts_disp} • {filename} • Inserted: {inserted} • Skipped: {skipped}"
        else:
            latest_checkup_display = latest_check_date_disp
    except Exception:
        latest_checkup_display = latest_check_date_disp
    
    # Grafik subtab and month range defaults
    grafik_subtab = 'grafik'
    grafik_start_month = request.GET.get('start_month', default_start_month)
    grafik_end_month = request.GET.get('end_month', default_end_month)

    context = {
        'active_menu': active_menu,
        'active_submenu': active_submenu,
        'employees': employees,
        'total_karyawan': total_items,
        'total_well': total_well,
        'total_unwell': total_unwell,
        'current_page': current_page,
        'total_pages': total_pages,
        'start_index': start_index,
        'filters': filters,
        'available_jabatan': available_jabatan,
        'available_lokasi': available_lokasi,
        'available_status': available_status,  # Add status options to context
        'checkups_today': checkups_today,
        'active_nurses': active_nurses,
        'pending_reviews': pending_reviews,
        'checkup_dates': checkup_dates,
        'checkup_counts': checkup_counts,
        'dept_names': dept_names,
        'dept_counts': dept_counts,
        'latest_checkup_display': latest_checkup_display,
        # New Grafik UI context
        'available_employees': available_employees,
        'default_start_month': default_start_month,
        'default_end_month': default_end_month,
        # Grafik context (Vue-based)
        'grafik_start_month': grafik_start_month,
        'grafik_end_month': grafik_end_month,
    }

    # Legacy Plotly (Grafik Kesehatan) removed; handled by Vue on client.

    # Legacy Plotly (Well & Unwell) removed; handled by Vue on client.

    # Upload History context
    if active_submenu == 'upload_history':
        try:
            hist_df = get_checkup_upload_history()
            upload_history = hist_df.to_dict('records') if hasattr(hist_df, 'empty') and not hist_df.empty else []
        except Exception:
            upload_history = []
        context['upload_history'] = upload_history
        context['MEDIA_URL'] = settings.MEDIA_URL
    
    return render(request, 'manager/dashboard.html', context)

# -------------------------
# Tab 2: User Management
# -------------------------
def add_new_user(request):
    """Add new user form and list."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        role = request.POST.get("role")
        
        try:
            # Normalize role values from form to canonical names
            role_map = {
                "manager": "Manager",
                "Manager": "Manager",
                "nurse": "Tenaga Kesehatan",
                "Tenaga Kesehatan": "Tenaga Kesehatan",
            }
            canonical_role = role_map.get(role)
            if not username or not password or not canonical_role:
                request.session['error_message'] = "Username, password, dan role valid diperlukan."
            else:
                add_user(username, password, canonical_role)
                request.session['success_message'] = f"User {username} added successfully"
        except Exception as e:
            request.session['error_message'] = f"Failed to add user: {e}"
        
        # Redirect preserving submenu to Add/Remove
        return redirect(reverse("manager:user_management") + "?submenu=add_remove")

    # Fetch all users
    users_df = get_users()
    
    # Map DB role names to simplified keys
    users_df['role_key'] = users_df['role'].str.lower().replace({
        'manager': 'manager',
        'tenaga kesehatan': 'nurse'
    })
    
    # Filter only manager and nurse users
    filtered_users = users_df[users_df['role_key'].isin(['manager', 'nurse'])]

    # Determine submenu selection
    active_submenu = request.GET.get('submenu', 'add_remove')

    context = {
        "users": filtered_users.to_dict('records'),
        "active_menu": "user",
        "active_submenu": active_submenu,
    }
    
    return render(request, "manager/user_management.html", context)

def remove_user(request, user_id):
    try:
        delete_user_by_id(user_id)
        request.session['success_message'] = "User removed successfully"
    except Exception as e:
        request.session['error_message'] = f"Failed to remove user: {e}"
    
    return redirect(reverse("manager:user_management") + "?submenu=add_remove")

@require_http_methods(["POST"])
def update_user_role(request, user_id):
    """Update user role from Manage Roles submenu."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    new_role = request.POST.get('role')
    try:
        from core.core_models import User
        from core.queries import count_users_by_role
        user = User.objects.get(id=user_id)

        # Enforce caps when promoting to Manager or Tenaga Kesehatan
        if new_role == "Manager" and count_users_by_role("Manager") >= 5 and user.role != "Manager":
            request.session['error_message'] = "Limit akun Manager sudah 5. Tidak dapat mempromosikan lagi."
            return redirect(reverse("manager:user_management") + "?submenu=manage_roles")
        if new_role == "Tenaga Kesehatan" and count_users_by_role("Tenaga Kesehatan") >= 10 and user.role != "Tenaga Kesehatan":
            request.session['error_message'] = "Limit akun Tenaga Kesehatan sudah 10. Tidak dapat mempromosikan lagi."
            return redirect(reverse("manager:user_management") + "?submenu=manage_roles")

        user.role = new_role
        user.save()
        request.session['success_message'] = "Role updated"
    except Exception as e:
        request.session['error_message'] = f"Failed to update role: {e}"
    
    return redirect(reverse("manager:user_management") + "?submenu=manage_roles")

# -------------------------
# Tab 3: QR Codes
# -------------------------
def qr_manager_interface(request):
    """QR code generation interface."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")
    
    # Get all employees from database and convert to list of dicts
    employees_df = get_employees()
    
    # Check if DataFrame is empty or doesn't have required columns
    if employees_df is None or employees_df.empty or not all(col in employees_df.columns for col in ['uid', 'nama']):
        employees = []
    else:
        employees = employees_df.to_dict('records')
    
    # Handle bulk export
    if request.GET.get("bulk") == "1":
        return qr_bulk_download_view(request)
    
    context = {
        "employees": employees,
        "active_menu": "qr",
    }
    
    # Handle inline single QR preview
    uid = request.GET.get("uid")
    if uid:
        # Find selected employee
        selected = None
        for emp in employees:
            if str(emp.get('uid')) == str(uid):
                selected = emp
                break
        
        if selected:
            # Build QR URL
            server_url = getattr(settings, "APP_BASE_URL", os.getenv("APP_BASE_URL", "")) or request.build_absolute_uri("/").rstrip("/")
            qr_url = f"{server_url}/karyawan/?uid={selected['uid']}"
            # Generate QR bytes and base64
            qr_bytes = generate_qr_bytes(qr_url)
            qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")
            context.update({
                "selected_name": selected.get('nama'),
                "selected_uid": selected.get('uid'),
                "qr_base64": qr_base64,
            })
        else:
            context.update({
                "error": "UID karyawan tidak ditemukan.",
            })
    
    return render(request, "manager/qr_codes.html", context)

# -------------------------
# Tab 4: Upload & Export Data
# -------------------------
def download_karyawan_template(request):
    """Download employee checkup template with real UID, nama, jabatan, lokasi, and tanggal_lahir."""
    try:
        excel_file = generate_karyawan_template_excel()
        response = HttpResponse(
            excel_file,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response['Content-Disposition'] = 'attachment; filename="Template_Checkup.xlsx"'
        return response
    except Exception as e:
        request.session['error_message'] = f"Failed to generate template: {e}"
        return redirect(reverse("manager:dashboard"))

def download_checkup_template(request):
    """
    Download Excel template containing master employee data 
    plus all medical checkup columns (like in V2).
    """
    try:
        # Use the same template generator as master karyawan
        excel_file = generate_karyawan_template_excel()
        response = HttpResponse(
            excel_file,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="Checkup_Template.xlsx"'
        return response

    except Exception as e:
        request.session["error_message"] = f"Failed to generate checkup template: {e}"
        return redirect(reverse("manager:upload_export"))



def upload_master_karyawan_xls(request):
    # Get first employee UID for Edit Karyawan menu
    employees_df = get_employees()
    default_uid = str(employees_df.iloc[0]['uid']) if not employees_df.empty else None

    menu_items = [
        {"key": "dashboard", "name": "Dashboard", "url": reverse("manager:dashboard"), "icon": "chart-line"},
        {"key": "user", "name": "User Management", "url": reverse("manager:user_management"), "icon": "users"},
        {"key": "qr", "name": "QR Codes", "url": reverse("manager:qr_codes"), "icon": "qrcode"},
        {"key": "data", "name": "Upload & Export", "url": reverse("manager:upload_export"), "icon": "upload"},
        {"key": "hapus_data_karyawan", "name": "Hapus Data Karyawan", "url": reverse("manager:hapus_data_karyawan"), "icon": "database"},
        {"key": "edit_karyawan", "name": "Edit Master Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
    ]
    
    if request.method == "POST" and request.FILES.get("file"):
        try:
            # Parse and save master karyawan data using core.excel_parser
            result = excel_parser.parse_master_karyawan(request.FILES["file"])
            request.session['success_message'] = f"{result['inserted']} karyawan berhasil diupload, {result['skipped']} dilewati."
        except Exception as e:
            request.session['error_message'] = f"Upload failed: {e}"
        return redirect(reverse("manager:dashboard"))
    
    return render(request, "manager/upload_export.html", {
        "active_menu": "data",
        "menu_items": menu_items
    })

def upload_medical_checkup_xls(request):
    """Upload medical checkup data from Excel."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    # Get first employee UID for Edit Karyawan menu
    employees_df = get_employees()
    default_uid = str(employees_df.iloc[0]['uid']) if not employees_df.empty else None

    menu_items = [
        {"key": "dashboard", "name": "Dashboard", "url": reverse("manager:dashboard"), "icon": "chart-line"},
        {"key": "user", "name": "User Management", "url": reverse("manager:user_management"), "icon": "users"},
        {"key": "qr", "name": "QR Codes", "url": reverse("manager:qr_codes"), "icon": "qrcode"},
        {"key": "data", "name": "Upload & Export", "url": reverse("manager:upload_export"), "icon": "upload"},
        {"key": "hapus_data_karyawan", "name": "Hapus Data Karyawan", "url": reverse("manager:hapus_data_karyawan"), "icon": "database"},
        {"key": "edit_karyawan", "name": "Edit Master Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
    ]
    
    if request.method == "POST" and request.FILES.get("file"):
        try:
            uploaded_file = request.FILES["file"]
            os.makedirs(settings.UPLOAD_CHECKUPS_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            original_name = os.path.basename(uploaded_file.name)
            save_path = os.path.join(settings.UPLOAD_CHECKUPS_DIR, f"{ts}-{original_name}")
            with open(save_path, "wb+") as dest:
                for chunk in uploaded_file.chunks():
                    dest.write(chunk)

            # Decide parser based on anthropometric columns presence (check aliases across all sheets)
            all_sheets = pd.read_excel(save_path, sheet_name=None, dtype=str)
            union_cols = set()
            for _df in (all_sheets.values() if all_sheets else []):
                try:
                    _norm = {str(c).strip().lower().replace(' ', '_') for c in getattr(_df, 'columns', [])}
                    union_cols |= _norm
                except Exception:
                    continue
            keys = ['tinggi', 'berat', 'bmi', 'height', 'weight', 'imt']
            has_anthro = any(any(k in col for k in keys) for col in union_cols)
            if has_anthro:
                result = excel_parser.parse_checkup_anthropometric(save_path)
            else:
                result = checkup_uploader.parse_checkup_xls(save_path)
            # Write log entry for this upload
            write_checkup_upload_log(original_name, result)
            inserted = int(result.get('inserted', 0)) if isinstance(result, dict) else 0
            skipped = len(result.get('skipped', [])) if isinstance(result, dict) else 0
            request.session['success_message'] = f"Excel berhasil di upload! {inserted} checkup disimpan, {skipped} baris dilewati."
        except Exception as e:
            request.session['error_message'] = f"Upload failed: {e}"
        return redirect(reverse("manager:dashboard"))
    
    return render(request, "manager/upload_export.html", {
        "active_menu": "data",
        "menu_items": menu_items
    })

# -------------------------
# Tab 5: Data Management / Hapus Data Karyawan
# -------------------------
def manage_karyawan_uid(request):
    """Manage employee UIDs / Hapus Data Karyawan unified page with filter and pagination."""
    # Accept either custom session auth (Manager) or Django auth for staff/superuser
    session_auth = request.session.get("authenticated")
    session_role = request.session.get("user_role")
    user_ok = hasattr(request, "user") and getattr(request.user, "is_authenticated", False) and (getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False))
    if not ((session_auth and session_role == "Manager") or user_ok):
        return redirect("accounts:login")

    # Load employees as DataFrame
    df = get_employees()

    # Filters (only by nama)
    filters = {
        'nama': request.GET.get('nama', '').strip(),
    }

    # Apply filter by nama (case-insensitive contains)
    if hasattr(df, 'empty') and not df.empty and filters['nama']:
        df = df[df['nama'].str.contains(filters['nama'], case=False, na=False)]

    # Ensure required columns exist
    if hasattr(df, 'empty') and not df.empty:
        for col in ['uid', 'nama', 'jabatan', 'lokasi']:
            if col not in df.columns:
                df[col] = ''
    else:
        # Create empty DataFrame with required columns if none
        import pandas as pd
        df = pd.DataFrame(columns=['uid', 'nama', 'jabatan', 'lokasi'])

    # Pagination (match dashboard behavior): max 10 per page
    items_per_page = 10
    total_items = len(df)
    total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 1
    current_page = int(request.GET.get('page', 1))
    current_page = max(1, min(current_page, total_pages))

    start_index = (current_page - 1) * items_per_page
    end_index = start_index + items_per_page

    # Slice for current page and convert to list of dicts
    df_page = df.iloc[start_index:end_index]
    employees = df_page[['uid', 'nama', 'jabatan', 'lokasi']].to_dict('records')

    # Build name options for selector (uid + "nama — jabatan") from full filtered dataset
    name_options = []
    if hasattr(df, 'empty') and not df.empty:
        try:
            opts_df = df[['uid', 'nama', 'jabatan']].drop_duplicates(subset=['uid'])
            name_options = [
                {'uid': row['uid'], 'nama': row['nama'], 'label': f"{row['nama']} — {row['jabatan']}"}
                for _, row in opts_df.iterrows()
            ]
        except Exception:
            name_options = []

    # Determine active subtab (karyawan or upload_history)
    active_subtab = request.GET.get("subtab", "karyawan")

    # Logs: simple global listing across all UIDs (no filters)
    manual_logs = []
    if active_subtab == "logs":
        try:
            from core.queries import get_recent_manual_input_logs
            manual_logs = get_recent_manual_input_logs(limit=200)
            # Normalize timestamp for template rendering
            try:
                from datetime import datetime as _dt
                for row in manual_logs:
                    ts = row.get("timestamp")
                    if isinstance(ts, str):
                        try:
                            row["timestamp"] = _dt.fromisoformat(ts)
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception:
            manual_logs = []

    # Load upload history for the second tab
    try:
        hist_df = get_checkup_upload_history()
        upload_history = hist_df.to_dict('records') if hasattr(hist_df, 'empty') and not hist_df.empty else []
    except Exception:
        upload_history = []

    # Normalize timestamp and inserted_ids for template usage
    try:
        for row in upload_history:
            ts = row.get("timestamp")
            if hasattr(ts, "to_pydatetime"):
                row["timestamp"] = ts.to_pydatetime()
            elif isinstance(ts, str):
                from datetime import datetime as _dt
                try:
                    row["timestamp"] = _dt.fromisoformat(ts)
                except Exception:
                    pass
            ids = row.get("inserted_ids")
            if isinstance(ids, list):
                str_ids = [str(x) for x in ids]
                row["inserted_ids"] = str_ids
                row["inserted_ids_preview"] = str_ids[:5]
                row["inserted_ids_more_count"] = max(0, len(str_ids) - 5)
    except Exception:
        pass

    context = {
        'employees': employees,
        'page_title': 'Hapus Data Karyawan',
        'current_page': current_page,
        'total_pages': total_pages,
        'start_index': start_index,
        'filters': filters,
        'name_options': name_options,
        'active_subtab': active_subtab,
        'upload_history': upload_history,
        'manual_logs': manual_logs,
        'MEDIA_URL': settings.MEDIA_URL,
    }

    return render(request, "manager/data_management.html", context)



# TODO: Vue fetch target → used in grafik_kesehatan (Phase 2)
@require_http_methods(["GET"]) 
def well_unwell_summary_json(request):
    """Return Well vs Unwell totals as JSON filtered by month range (YYYY-MM) and lokasi kerja."""
    # STEP 3️⃣ — BACKEND PARAMETER DIAGNOSTIC
    try:
        print("[DEBUG] Incoming GET params:", dict(request.GET))
    except Exception:
        pass
    # Temporary debug info to surface diagnostics directly in JSON response for easier automated verification
    debug_info = {
        "incoming_params": dict(getattr(request, "GET", {})),
        "auth_role": request.session.get("user_role"),
    }
    # Basic auth guard similar to dashboard (allow Manager and Tenaga Kesehatan)
    role = request.session.get("user_role")
    if not request.session.get("authenticated") or role not in ["Manager", "Tenaga Kesehatan"]:
        return JsonResponse({"error": "unauthorized"}, status=401)

    month_from = request.GET.get("month_from", "")
    month_to = request.GET.get("month_to", "")
    lokasi = request.GET.get("lokasi", "")
    uid_filter = (request.GET.get("uid", "") or "").strip()

    # Load checkup data
    try:
        df = load_checkups()
    except Exception:
        df = None
    # Capture initial DataFrame state
    try:
        debug_info["df_is_none"] = df is None
        debug_info["initial_columns"] = list(df.columns) if df is not None else []
        debug_info["initial_rows"] = (len(df) if df is not None else 0)
    except Exception:
        pass

    months = []
    well_counts = []
    unwell_counts = []

    try:
        if df is not None and hasattr(df, "empty") and not df.empty:
            import pandas as _pd
            from datetime import datetime
            try:
                print("[DEBUG] Initial rows:", len(df))
                debug_info["initial_rows_printed"] = len(df)
            except Exception:
                pass
            # Ensure tanggal_checkup parsed and status present
            if "tanggal_checkup" in df.columns:
                try:
                    df["tanggal_checkup"] = _pd.to_datetime(df["tanggal_checkup"], errors="coerce")
                except Exception:
                    pass
            # Compute status if missing or contains NaN
            try:
                if "status" not in df.columns or df["status"].isna().any():
                    from core.helpers import compute_status as _compute_status
                    df["status"] = df.apply(_compute_status, axis=1)
            except Exception:
                # If compute fails, default unknown to Well to avoid skewing Unwell
                df["status"] = df.get("status", "Well")

            # Apply karyawan UID filter first (if provided)
            if uid_filter:
                try:
                    df = df[df["uid"].astype(str) == uid_filter]
                    debug_info["rows_after_uid_filter"] = len(df)
                except Exception:
                    pass

            # Apply lokasi filter with safe normalization (case/whitespace-insensitive)
            lokasi_filter = (request.GET.get("lokasi", "") or "").strip()
            try:
                print("[DEBUG] Filter lokasi:", lokasi_filter)
                debug_info["lokasi_filter"] = lokasi_filter
            except Exception:
                pass
            if lokasi_filter and lokasi_filter.lower() not in ["all", ""]:
                # Determine which column to use for lokasi (support both 'lokasi' and 'Lokasi Kerja')
                col_name = None
                if "lokasi" in df.columns:
                    col_name = "lokasi"
                elif "Lokasi Kerja" in df.columns:
                    col_name = "Lokasi Kerja"
                debug_info["lokasi_col_name"] = col_name
                if col_name:
                    try:
                        df[col_name] = df[col_name].astype(str).str.strip().str.lower()
                        lokasi_norm = lokasi_filter.lower()
                        # Optional debug: view unique normalized lokasi values
                        try:
                            print("[DEBUG] Unique lokasi values:", df[col_name].dropna().unique().tolist())
                            debug_info["unique_lokasi_values"] = df[col_name].dropna().unique().tolist()
                        except Exception:
                            pass
                        # Strict filter: if no match, return empty dataset (no rows)
                        filtered_df = df[df[col_name] == lokasi_norm].copy()
                        try:
                            print("[DEBUG] Data count after lokasi filter:", len(filtered_df))
                            debug_info["rows_after_lokasi_filter"] = len(filtered_df)
                        except Exception:
                            pass
                        if hasattr(filtered_df, "empty") and filtered_df.empty:
                            print(f"[INFO] No data found for lokasi: {lokasi_norm}")
                            debug_info["lokasi_filter_match"] = False
                            df = df.head(0)
                        else:
                            debug_info["lokasi_filter_match"] = True
                            df = filtered_df
                    except Exception:
                        # Do not fallback to previous df; keep current df state
                        pass
                else:
                    print("[DEBUG] Missing column 'lokasi' or 'Lokasi Kerja' in DataFrame")
                    debug_info["lokasi_col_missing"] = True

            # Parse month range (robust): if only single month provided, bound to that month
            start_date = None
            end_date = None
            try:
                if month_from:
                    parts = str(month_from).split("-")
                    if len(parts) >= 2:
                        y = int(parts[0]); m = int(parts[1])
                        start_date = datetime(y, m, 1)
                        # If month_to missing, set end to first day of next month
                        if not month_to:
                            if m == 12:
                                end_date = datetime(y + 1, 1, 1)
                            else:
                                end_date = datetime(y, m + 1, 1)
                if month_to:
                    parts = str(month_to).split("-")
                    if len(parts) >= 2:
                        y2 = int(parts[0]); m2 = int(parts[1])
                        # end_date is first day of next month to make filter exclusive upper bound
                        if m2 == 12:
                            end_date = datetime(y2 + 1, 1, 1)
                        else:
                            end_date = datetime(y2, m2 + 1, 1)
                        # If month_from missing, set start to first day of target month
                        if not start_date:
                            start_date = datetime(y2, m2, 1)
            except Exception:
                pass

            # Filter by date range
            if start_date:
                df = df[df["tanggal_checkup"] >= start_date]
            if end_date:
                df = df[df["tanggal_checkup"] < end_date]
            try:
                debug_info["rows_after_date_filter"] = len(df)
            except Exception:
                pass

            # Group by year-month and status
            df["year_month"] = df["tanggal_checkup"].dt.strftime("%Y-%m")
            monthly_stats = df.groupby(["year_month", "status"]).size().unstack(fill_value=0)

            # Sort months chronologically
            monthly_stats = monthly_stats.sort_index()

            # Extract data for response
            months = monthly_stats.index.tolist()
            well_counts = monthly_stats.get("Well", _pd.Series(0, index=monthly_stats.index)).tolist()
            unwell_counts = monthly_stats.get("Unwell", _pd.Series(0, index=monthly_stats.index)).tolist()

    except Exception as e:
        print(f"Error processing Well/Unwell data: {str(e)}")
        debug_info["processing_error"] = str(e)
        pass

    data = {
        "months": months,
        "well_counts": well_counts,
        "unwell_counts": unwell_counts,
        # Temporary: include debug info for automated diagnostics. Will be removed after verification.
        "debug": debug_info
    }
    # Diagnostic logging: params, record counts, JSON length, processing time
    try:
        import json, time as _t
        _start = _t.time()
        body = json.dumps(data, ensure_ascii=False)
        duration = _t.time() - _start
        # Structured JSON log per instructions
        print(json.dumps({
            "filters": dict(request.GET),
            "dataLengths": { "well": len(well_counts), "unwell": len(unwell_counts) },
            "jsonSize": len(body),
            "time": round(duration, 3)
        }))
    except Exception:
        pass
    return JsonResponse(data)

# -------------------------
# Grafik → Lokasi list JSON
# -------------------------
@require_http_methods(["GET"]) 
def lokasi_list_json(request):
    """Return list of lokasi names for filters as JSON.

    Response shape:
    { "lokasi": ["Lokasi A", "Lokasi B", ...] }
    """
    # Auth guard similar to dashboard
    role = request.session.get("user_role")
    if not request.session.get("authenticated") or role not in ["Manager", "Tenaga Kesehatan"]:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        lokasi = get_all_lokasi() or []
        # Ensure plain strings
        lokasi = [str(x) for x in lokasi if x is not None and str(x).strip()]
    except Exception:
        lokasi = []
    return JsonResponse({"lokasi": lokasi})

# -------------------------
# Grafik → Karyawan list JSON
# -------------------------
@require_http_methods(["GET"]) 
def karyawan_list_json(request):
    """Return list of karyawan (uid + nama) for filters as JSON.

    Response shape:
    { "karyawan": [ {"uid": "...", "nama": "..."}, ... ] }
    """
    # Auth guard similar to dashboard
    role = request.session.get("user_role")
    if not request.session.get("authenticated") or role not in ["Manager", "Tenaga Kesehatan"]:
        return JsonResponse({"error": "unauthorized"}, status=401)

    items = []
    try:
        df_emp = get_employees()
        if df_emp is not None and hasattr(df_emp, "empty") and not df_emp.empty:
            # Only keep necessary columns
            cols = [c for c in ["uid", "nama", "lokasi"] if c in df_emp.columns]
            df_slim = df_emp[cols].copy()
            # Sort by nama for nicer UX
            if "nama" in df_slim.columns:
                df_slim = df_slim.sort_values("nama")
            items = df_slim.to_dict(orient="records")
    except Exception:
        items = []
    return JsonResponse({"karyawan": items})

# -------------------------
# Grafik → Health Metrics summary JSON
# -------------------------
@require_http_methods(["GET"]) 
def health_metrics_summary_json(request):
    """Return monthly averages for 5 health metrics filtered by month range (YYYY-MM) and lokasi kerja.

    Updated response shape expected by frontend:
    {
      "x_dates": ["2025-01", "2025-02", ...],
      "series": {
        "Gula Darah Puasa": [...],
        "Gula Darah Sewaktu": [...],
        "Tekanan Darah": [...],  # systolic average per month
        "Cholesterol": [...],
        "Asam Urat": [...]
      }
    }
    """
    # Auth guard similar to dashboard
    role = request.session.get("user_role")
    if not request.session.get("authenticated") or role not in ["Manager", "Tenaga Kesehatan"]:
        return JsonResponse({"error": "unauthorized"}, status=401)

    month_from = request.GET.get("month_from", "").strip()
    month_to = request.GET.get("month_to", "").strip()
    lokasi_filter = request.GET.get("lokasi", "").strip()
    uid_filter = (request.GET.get("uid", "") or "").strip()
    # Diagnostics start time
    try:
        import time as _t
        _diag_start_time = _t.time()
    except Exception:
        _diag_start_time = None

    # Load historical checkup data; fallback to dashboard latest if necessary
    try:
        df = load_checkups()
    except Exception:
        df = None
    if df is None or not hasattr(df, "empty") or df.empty:
        try:
            df = get_dashboard_checkup_data()
        except Exception:
            df = None
    if df is None or not hasattr(df, "empty") or df.empty:
        return JsonResponse({"x_dates": [], "series": {}})

    import pandas as _pd
    from datetime import datetime as _dt

    # Determine date column
    date_col = None
    for cand in ["tanggal_checkup", "tanggal_periksa", "Tanggal Pemeriksaan", "tanggal"]:
        if cand in df.columns:
            date_col = cand
            break
    if not date_col:
        return JsonResponse({"x_dates": [], "series": {}})

    # Parse dates
    try:
        df[date_col] = _pd.to_datetime(df[date_col], errors="coerce")
    except Exception:
        pass
    df = df.dropna(subset=[date_col])

    # Apply karyawan UID filter (if provided)
    if uid_filter:
        try:
            df = df[df["uid"].astype(str) == uid_filter]
        except Exception:
            pass

    # Apply lokasi filter (supports 'lokasi' or 'Lokasi Kerja')
    if lokasi_filter and lokasi_filter.lower() not in ["", "all"]:
        lokasi_col = None
        if "lokasi" in df.columns:
            lokasi_col = "lokasi"
        elif "Lokasi Kerja" in df.columns:
            lokasi_col = "Lokasi Kerja"
        if lokasi_col:
            df[lokasi_col] = df[lokasi_col].astype(str).str.strip()
            df = df[df[lokasi_col].str.lower() == lokasi_filter.lower()]

    # Month range bounds
    start_date = None
    end_date = None
    try:
        if month_from:
            y, m = [int(x) for x in str(month_from).split("-")[:2]]
            start_date = _dt(y, m, 1)
        if month_to:
            y2, m2 = [int(x) for x in str(month_to).split("-")[:2]]
            end_date = _dt(y2, m2, 1)
            # exclusive upper bound: first day of next month
            end_date = _dt(y2 + (1 if m2 == 12 else 0), 1 if m2 == 12 else m2 + 1, 1)
        # If only month_from provided, set end_date to next month
        if start_date and not end_date:
            y, m = start_date.year, start_date.month
            end_date = _dt(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    except Exception:
        pass
    if start_date:
        df = df[df[date_col] >= start_date]
    if end_date:
        df = df[df[date_col] < end_date]

    if not hasattr(df, "empty") or df.empty:
        return JsonResponse({"x_dates": [], "series": {}})

    # Helper to extract systolic values from 'tekanan_darah' like '120/80'
    def _parse_systolic(x):
        try:
            s = str(x)
            if "/" in s:
                return float(s.split("/")[0])
            return float(s)
        except Exception:
            return _pd.NA

    # Build month key
    df["month"] = df[date_col].dt.strftime("%Y-%m")

    # Prepare numeric columns for target metrics
    gdp_col = "gula_darah_puasa" if "gula_darah_puasa" in df.columns else None
    gds_col = "gula_darah_sewaktu" if "gula_darah_sewaktu" in df.columns else None
    chol_col = "cholesterol" if "cholesterol" in df.columns else None
    asam_col = "asam_urat" if "asam_urat" in df.columns else None
    bp_col = "tekanan_darah" if "tekanan_darah" in df.columns else None

    df["gdp_num"] = _pd.to_numeric(df.get(gdp_col, _pd.Series([_pd.NA]*len(df))), errors="coerce") if gdp_col else _pd.Series([_pd.NA]*len(df))
    df["gds_num"] = _pd.to_numeric(df.get(gds_col, _pd.Series([_pd.NA]*len(df))), errors="coerce") if gds_col else _pd.Series([_pd.NA]*len(df))
    df["chol_num"] = _pd.to_numeric(df.get(chol_col, _pd.Series([_pd.NA]*len(df))), errors="coerce") if chol_col else _pd.Series([_pd.NA]*len(df))
    df["asam_num"] = _pd.to_numeric(df.get(asam_col, _pd.Series([_pd.NA]*len(df))), errors="coerce") if asam_col else _pd.Series([_pd.NA]*len(df))
    df["bp_sys"] = df.get(bp_col, _pd.Series([_pd.NA]*len(df))).apply(_parse_systolic) if bp_col else _pd.Series([_pd.NA]*len(df))

    # Group by month and compute mean
    gb = df.groupby("month").agg({
        "gdp_num":"mean",
        "gds_num":"mean",
        "bp_sys":"mean",
        "chol_num":"mean",
        "asam_num":"mean",
    }).reset_index().sort_values("month")

    x_dates = gb["month"].astype(str).tolist()

    def _clean(vals):
        return [ None if (v is None or (isinstance(v, float) and _pd.isna(v))) else float(v) for v in vals ]

    series = {
        "Gula Darah Puasa": _clean(gb["gdp_num"].tolist()),
        "Gula Darah Sewaktu": _clean(gb["gds_num"].tolist()),
        "Tekanan Darah": _clean(gb["bp_sys"].tolist()),
        "Cholesterol": _clean(gb["chol_num"].tolist()),
        "Asam Urat": _clean(gb["asam_num"].tolist()),
    }
    # Diagnostic logging for request and response payload characteristics
    try:
        import json, time as _t
        payload = {"x_dates": x_dates, "series": series}
        json_str = json.dumps(payload, ensure_ascii=False)
        duration = (_t.time() - _diag_start_time) if _diag_start_time else 0.0
        # Derive summary metrics record count (max series length or months)
        try:
            _series_lengths = [ len(v) for v in series.values() if isinstance(v, list) ]
            summary_len = max(_series_lengths) if _series_lengths else len(x_dates)
        except Exception:
            summary_len = len(x_dates)
        print(
            json.dumps({
                "filters": dict(request.GET),
                "dataLengths": { "summaryMetrics": summary_len },
                "jsonSize": len(json_str),
                "time": round(duration, 3)
            })
        )
        return JsonResponse(payload)
    except Exception:
        return JsonResponse({"x_dates": x_dates, "series": series})

# -------------------------
# Tab 5b: Delete Single Employee (trailing duplicate removed)
# -------------------------
# Removed trailing duplicate function that was incomplete to prevent override/syntax issues.

# -------------------------
# Grafik Diagnostics: Receive client-side logs
# -------------------------
@csrf_exempt
@require_http_methods(["POST"]) 
def grafik_diagnostic_log(request):
    """Temporary endpoint to capture frontend diagnostic logs when browser may freeze.

    Expected JSON payload shape:
    {
      "filters": {"month_from":"YYYY-MM","month_to":"YYYY-MM","lokasi":"","uid":""},
      "wellDataLength": int,
      "unwellDataLength": int,
      "xDatesLength": int,
      "seriesKeys": ["Gula Darah Puasa", ...]
    }
    """
    role = request.session.get("user_role")
    if not request.session.get("authenticated") or role not in ["Manager", "Tenaga Kesehatan"]:
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        import json, time
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        raw_body = request.body.decode("utf-8")
        payload = json.loads(raw_body or "{}")
        # Print concise diagnostic line
        filters = payload.get("filters", {})
        well_len = payload.get("wellDataLength")
        unwell_len = payload.get("unwellDataLength")
        x_len = payload.get("xDatesLength")
        keys = payload.get("seriesKeys")
        print(f"[Diagnostic] grafik-manager-client | ts={ts} | filters={filters} | well={well_len} | unwell={unwell_len} | x_dates={x_len} | series_keys={keys}")
        return JsonResponse({"ok": True})
    except Exception as e:
        print(f"[Diagnostic] grafik-manager-client | error={str(e)}")
        return JsonResponse({"ok": False, "error": str(e)}, status=200)
