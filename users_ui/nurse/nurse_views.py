# users_ui/nurse/nurse_views.py
import io
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods
import pandas as pd
from datetime import datetime
import base64
from django.conf import settings
import os

from core.queries import (
    get_users,
    add_user,
    get_employees,
    add_employee_if_exists,
    get_employee_by_uid,
    get_medical_checkups_by_uid,
    insert_medical_checkup,
    save_manual_karyawan_edits,
    get_latest_medical_checkup,
    load_checkups,
)
from core.helpers import (
    sanitize_df_for_display,
    get_dashboard_checkup_data,
    compute_status,
)
from core import checkup_uploader
from users_ui.qr.qr_views import qr_detail_view, qr_bulk_download_view
from users_ui.qr.qr_utils import generate_qr_bytes
from utils.export_utils import generate_karyawan_template_excel, export_checkup_data_excel as build_checkup_excel, export_checkup_data_pdf as build_checkup_pdf

# Plotly for grafik replication
import plotly.graph_objects as go
import plotly.io as pio


# -------------------------
# Tab 1: Dashboard
# -------------------------
def nurse_index(request):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    # Replicate manager-style dashboard submenu handling
    active_submenu = request.GET.get("submenu", "data")

    # Grafik JSON API: replicate Manager Grafik for Nurse dashboard
    if active_submenu == 'grafik' and request.GET.get('grafik_json') == '1':
        try:
            df_json = load_checkups()
        except Exception:
            df_json = pd.DataFrame()
        if df_json is None or df_json.empty:
            try:
                df_json = get_dashboard_checkup_data()
            except Exception:
                df_json = pd.DataFrame()
        now = pd.Timestamp.now()
        default_end_month_dt = pd.Timestamp(year=now.year, month=now.month, day=1)
        default_start_month_dt = default_end_month_dt - pd.offsets.DateOffset(months=5)
        # Choose date column and robustly parse
        date_col = None
        if not df_json.empty and 'tanggal_MCU' in df_json.columns:
            df_json['tanggal_MCU_raw'] = df_json['tanggal_MCU']
            df_json['tanggal_MCU'] = pd.to_datetime(df_json['tanggal_MCU'], errors='coerce', dayfirst=True)
            if df_json['tanggal_MCU'].isna().all():
                df_json['tanggal_MCU'] = pd.to_datetime(df_json['tanggal_MCU_raw'], format='%d/%m/%y', errors='coerce')
            date_col = 'tanggal_MCU'
        elif not df_json.empty and 'tanggal_checkup' in df_json.columns:
            df_json['tanggal_checkup'] = pd.to_datetime(df_json['tanggal_checkup'], errors='coerce', dayfirst=True)
            date_col = 'tanggal_checkup'
        else:
            df_json = df_json.copy()
            df_json['synthetic_month'] = now.strftime('%Y-%m')
        # Ensure status column exists
        try:
            if 'status' not in df_json.columns or df_json['status'].isna().any():
                df_json['status'] = df_json.apply(compute_status, axis=1)
        except Exception:
            pass
        # Filters
        uid = request.GET.get('uid', 'all')
        start_month = request.GET.get('start_month')
        end_month = request.GET.get('end_month')
        start_dt = pd.to_datetime(start_month + '-01', errors='coerce') if start_month else default_start_month_dt
        end_dt = pd.to_datetime(end_month + '-01', errors='coerce') if end_month else default_end_month_dt
        if date_col:
            df_json = df_json[(df_json[date_col] >= start_dt) & (df_json[date_col] <= end_dt)]
        # Individual vs multiline
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
        if uid and uid != 'all':
            df_u = df_json[df_json['uid'].astype(str) == str(uid)].copy()
            if df_u.empty:
                return JsonResponse({'mode':'individual','x_dates':[],'series':{'gula_darah_puasa':[],'gula_darah_sewaktu':[],'tekanan_darah_sistole':[],'lingkar_perut':[],'cholesterol':[],'asam_urat':[]},'summary':{'total_employees':0,'well_count':0,'unwell_count':0}})
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
            }
            latest_row = df_u.iloc[-1]
            total_employees = 1
            well_count = 1 if str(latest_row.get('status')) == 'Well' else 0
            unwell_count = 1 if str(latest_row.get('status')) == 'Unwell' else 0
            return JsonResponse({'mode':'individual','x_dates':x_dates,'series':series,'summary':{'total_employees':total_employees,'well_count':well_count,'unwell_count':unwell_count}})
        else:
            df_filt = df_json.copy()
            if df_filt.empty or not date_col:
                return JsonResponse({'mode':'multiline','x_dates':[],'employees':[],'series_by_employee':{}})
            df_filt = df_filt.dropna(subset=[date_col]).sort_values(by=[date_col, 'uid'])
            x_dates = sorted(df_filt[date_col].dt.strftime('%Y-%m-%d').unique().tolist())
            try:
                if 'nama' not in df_filt.columns:
                    df_filt['nama'] = df_filt['uid'].astype(str).apply(lambda u: f'UID {u}')
            except Exception:
                pass
            series_by_employee = {}
            employees_list = []
            uids = [str(u) for u in df_filt['uid'].dropna().astype(str).unique().tolist()]
            for u in uids:
                df_u = df_filt[df_filt['uid'].astype(str) == u].copy().sort_values(by=[date_col])
                date_map = {}
                for _, row in df_u.iterrows():
                    try:
                        key = pd.to_datetime(row[date_col]).strftime('%Y-%m-%d')
                    except Exception:
                        key = None
                    if key:
                        date_map[key] = row
                def to_float_safe(val):
                    try:
                        return float(val)
                    except Exception:
                        return None
                s_gp = []; s_gs = []; s_td = []; s_lp = []; s_ch = []; s_au = []
                for d in x_dates:
                    row = date_map.get(d)
                    if row is None:
                        s_gp.append(None); s_gs.append(None); s_td.append(None); s_lp.append(None); s_ch.append(None); s_au.append(None)
                    else:
                        s_gp.append(to_float_safe(row.get('gula_darah_puasa')))
                        s_gs.append(to_float_safe(row.get('gula_darah_sewaktu')))
                        s_td.append(parse_systolic(row.get('tekanan_darah')))
                        s_lp.append(to_float_safe(row.get('lingkar_perut')))
                        s_ch.append(to_float_safe(row.get('cholesterol')))
                        s_au.append(to_float_safe(row.get('asam_urat')))
                series_by_employee[u] = {
                    'nama': str(df_u.iloc[-1]['nama']) if not df_u.empty else f'UID {u}',
                    'gula_darah_puasa': s_gp,
                    'gula_darah_sewaktu': s_gs,
                    'tekanan_darah_sistole': s_td,
                    'lingkar_perut': s_lp,
                    'cholesterol': s_ch,
                    'asam_urat': s_au,
                }
                employees_list.append({'uid': u, 'nama': series_by_employee[u]['nama']})
            return JsonResponse({'mode':'multiline','x_dates':x_dates,'employees':employees_list,'series_by_employee':series_by_employee})

    # Pull session messages for toast notifications
    success_message = request.session.pop("success_message", None)
    error_message = request.session.pop("error_message", None)
    warning_message = request.session.pop("warning_message", None)

    # Get the dashboard DataFrame similar to manager
    df = get_dashboard_checkup_data()

    # Normalize 'jabatan' to remove duplicates caused by spacing/casing differences
    if not df.empty and "jabatan" in df.columns:
        df["jabatan_clean"] = df["jabatan"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        df["jabatan_key"] = df["jabatan_clean"].str.lower()
    else:
        df["jabatan_clean"] = ""
        df["jabatan_key"] = ""

    # Get all available locations before filtering
    all_lokasi = sorted(df["lokasi"].dropna().unique().tolist()) if not df.empty and "lokasi" in df.columns else []

    # Get filter parameters
    filters = {
        "nama": request.GET.get("nama", ""),
        "jabatan": request.GET.get("jabatan", ""),
        "lokasi": request.GET.get("lokasi", ""),
        "status": request.GET.get("status", ""),
        "expiry": request.GET.get("expiry", ""),
    }

    # Apply filters
    if filters["nama"]:
        df = df[df["nama"].str.contains(filters["nama"], case=False, na=False)]
    if filters["jabatan"]:
        # Normalize filter to match jabatan_key
        filt_clean = " ".join(filters["jabatan"].split()).strip().lower()
        df = df[df["jabatan_key"] == filt_clean]
    if filters["lokasi"]:
        df = df[df["lokasi"] == filters["lokasi"]]
    if filters["status"]:
        df = df[df["status"] == filters["status"]]

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
        df['mcu_is_expired'] = False
        df['mcu_is_warning'] = False

    # Apply expiry filter if requested
    if filters.get("expiry"):
        expiry_val = str(filters["expiry"]).lower()
        if expiry_val == "expired":
            df = df[df["mcu_is_expired"]]
        elif expiry_val in ("warning", "almost", "almost_expired", "almost-expired"):
            df = df[df["mcu_is_warning"]]

    # Build available dropdown options from filtered/normalized data
    jabatan_map = {}
    if not df.empty and "jabatan_key" in df.columns and "jabatan_clean" in df.columns:
        for key, val in zip(df["jabatan_key"], df["jabatan_clean"]):
            if key and key not in jabatan_map:
                jabatan_map[key] = val
    available_jabatan = sorted(jabatan_map.values())
    available_lokasi = all_lokasi
    available_status = ["Well", "Unwell"]

    # Stats
    total_items = len(df)
    total_well = len(df[df["status"] == "Well"]) if not df.empty and "status" in df.columns else 0
    total_unwell = len(df[df["status"] == "Unwell"]) if not df.empty and "status" in df.columns else 0

    # Pagination (match manager)
    items_per_page = 10
    total_pages = (total_items + items_per_page - 1) // items_per_page if total_items > 0 else 1
    current_page = int(request.GET.get("page", 1))
    current_page = max(1, min(current_page, total_pages))

    start_index = (current_page - 1) * items_per_page
    end_index = start_index + items_per_page

    df_page = df.iloc[start_index:end_index] if not df.empty else df
    # Sanitize date/time columns to avoid NaTType utcoffset issues in templates
    try:
        df_page = sanitize_df_for_display(df_page)
    except Exception:
        pass
    employees = df_page.to_dict("records")

    # Defaults for Grafik filters (last 6 months)
    now = pd.Timestamp.now()
    default_end_month_dt = pd.Timestamp(year=now.year, month=now.month, day=1)
    default_start_month_dt = default_end_month_dt - pd.offsets.DateOffset(months=5)
    default_start_month = default_start_month_dt.strftime('%Y-%m')
    default_end_month = default_end_month_dt.strftime('%Y-%m')

    # Manager-style Grafik subtab and month range variables (match Manager dashboard)
    grafik_subtab = request.GET.get('subtab', 'grafik_kesehatan')
    grafik_start_month = request.GET.get('start_month', default_start_month)
    grafik_end_month = request.GET.get('end_month', default_end_month)

    # --- Grafik Kesehatan in-dashboard ---
    merged_chart_html = None
    if active_submenu == "grafik" and grafik_subtab == "grafik_kesehatan":
        # Call the grafik logic directly to get context; fallback to internal helper
        from users_ui.nurse.nurse_views import nurse_grafik_kesehatan, nurse_grafik_kesehatan_logic
        resp = nurse_grafik_kesehatan(request)
        grafik_context = getattr(resp, "context_data", None)
        if not grafik_context or "grafik_chart_html" not in grafik_context:
            try:
                merged_chart_html = nurse_grafik_kesehatan_logic(request)
            except Exception:
                merged_chart_html = None
        else:
            merged_chart_html = grafik_context.get("grafik_chart_html")
    # ----------------------------------------

    # Available employees for UID dropdown in Grafik
    available_employees = []
    try:
        emp_df = get_employees()
    except Exception:
        emp_df = pd.DataFrame()
    if emp_df is not None and not emp_df.empty:
        cols = [c for c in emp_df.columns]
        uid_col = 'uid' if 'uid' in cols else ('UID' if 'UID' in cols else None)
        name_col = 'nama' if 'nama' in cols else ('Nama' if 'Nama' in cols else None)
        if uid_col:
            emp_df = emp_df.dropna(subset=[uid_col])
            for _, row in emp_df.iterrows():
                u = str(row[uid_col])
                n = str(row[name_col]) if name_col else f'UID {u}'
                available_employees.append({'uid': u, 'nama': n})

    # Additional dashboard metrics similar to manager
    users_df = get_users()
    checkups_today = 0
    active_nurses = len(users_df[users_df["role"] == "nurse"]) if not users_df.empty and "role" in users_df.columns else 0
    pending_reviews = 0

    # Grafik chart data (replicated from manager)
    grafik_chart_html = None
    grafik_filter_mode = request.GET.get('grafik_mode', 'month')  # 'month' or 'week'
    grafik_month = request.GET.get('grafik_month', '')  # e.g., '2025-10'

    # Build time series from all checkups to plot trend
    all_checkups_df = load_checkups()
    if not all_checkups_df.empty:
        # Ensure datetime
        all_checkups_df['tanggal_checkup'] = pd.to_datetime(all_checkups_df['tanggal_checkup'], errors='coerce')
        # Derive status if missing
        if 'status' not in all_checkups_df.columns or all_checkups_df['status'].isna().any():
            all_checkups_df['status'] = all_checkups_df.apply(compute_status, axis=1)

        # Apply optional lokasi/jabatan/status filters to grafik too, for consistency
        graf_df = all_checkups_df.copy()
        if filters['lokasi']:
            graf_df = graf_df[graf_df['lokasi'] == filters['lokasi']]
        if filters['jabatan']:
            filt_clean = ' '.join(filters['jabatan'].split()).strip().lower()
            # match original jabatan via lower() to be robust
            graf_df = graf_df[graf_df['jabatan'].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True).str.lower() == filt_clean]
        if filters['status']:
            graf_df = graf_df[graf_df['status'] == filters['status']]

        # Filter by month or week if provided
        if grafik_filter_mode == 'month' and grafik_month:
            try:
                month_dt = pd.to_datetime(grafik_month + '-01', errors='coerce')
                if pd.notnull(month_dt):
                    month_start = month_dt
                    # end of month: add 1 month then subtract 1 day safely
                    next_month = (month_dt + pd.offsets.MonthBegin(1))
                    month_end = next_month - pd.Timedelta(days=1)
                    graf_df = graf_df[(graf_df['tanggal_checkup'] >= month_start) & (graf_df['tanggal_checkup'] <= month_end)]
            except Exception:
                pass
        elif grafik_filter_mode == 'week':
            # Use ISO week filter if provided via grafik_week as 'YYYY-Www'
            grafik_week = request.GET.get('grafik_week', '')
            if grafik_week:
                try:
                    # Parse 'YYYY-Www' to a date range (ISO week)
                    year_str, week_str = grafik_week.split('-W')
                    year_i, week_i = int(year_str), int(week_str)
                    # ISO week start (Monday)
                    week_start = pd.to_datetime(f'{year_i}-W{week_i}-1', format='%G-W%V-%u', errors='coerce')
                    week_end = week_start + pd.Timedelta(days=6)
                    if pd.notnull(week_start):
                        graf_df = graf_df[(graf_df['tanggal_checkup'] >= week_start) & (graf_df['tanggal_checkup'] <= week_end)]
                except Exception:
                    pass

        # Aggregate counts per day
        graf_df['date'] = graf_df['tanggal_checkup'].dt.date
        daily = graf_df.groupby(['date', 'status']).size().reset_index(name='count')
        # Pivot to get Well vs Unwell columns
        pivot = daily.pivot_table(index='date', columns='status', values='count', fill_value=0)
        pivot = pivot.rename(columns={'Well': 'well', 'Unwell': 'unwell'})
        pivot = pivot.sort_index()
        # Ensure both expected status columns exist as Series to avoid scalar fallbacks
        pivot = pivot.reindex(columns=['well', 'unwell'], fill_value=0)

        # Build Plotly figure (only for Well/Unwell subtab)
        if grafik_subtab == 'well_unwell' and not pivot.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pivot.index, y=pivot['well'], mode='lines+markers', name='Well', line=dict(color='green')))
            fig.add_trace(go.Scatter(x=pivot.index, y=pivot['unwell'], mode='lines+markers', name='Unwell', line=dict(color='red')))
            fig.update_layout(
                title='Well vs Unwell Over Time',
                xaxis_title='Tanggal',
                yaxis_title='Total Karyawan',
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                margin=dict(l=40, r=20, t=60, b=40),
                template='plotly_white'
            )
            grafik_chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')

    # Department chart data
    checkup_dates = []
    checkup_counts = []
    dept_names = []
    dept_counts = []
    if not df.empty and "jabatan" in df.columns:
        dept_counts_series = df["jabatan"].value_counts()
        dept_names = dept_counts_series.index.tolist()
        dept_counts = dept_counts_series.values.tolist()

    context = {
        "active_submenu": active_submenu,
        "employees": employees,
        "total_karyawan": total_items,
        "total_well": total_well,
        "total_unwell": total_unwell,
        "current_page": current_page,
        "total_pages": total_pages,
        "start_index": start_index,
        "filters": filters,
        "available_jabatan": available_jabatan,
        "available_lokasi": available_lokasi,
        "available_status": available_status,
        "checkups_today": checkups_today,
        "active_nurses": active_nurses,
        "pending_reviews": pending_reviews,
        "checkup_dates": checkup_dates,
        "checkup_counts": checkup_counts,
        "dept_names": dept_names,
        "dept_counts": dept_counts,
        "grafik_chart_html": merged_chart_html if merged_chart_html is not None else grafik_chart_html,
        # Added for Nurse Grafik replication
        "available_employees": available_employees,
        "default_start_month": default_start_month,
        "default_end_month": default_end_month,
        # Manager-style Grafik context
        "grafik_subtab": grafik_subtab,
        "grafik_start_month": grafik_start_month,
        "grafik_end_month": grafik_end_month,
        "active_menu_label": "Dashboard",
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
    }

    return render(request, "nurse/dashboard.html", context)


# -------------------------
# Tab 2: User Management (if needed for nurse)
# -------------------------
@require_http_methods(["POST"])
def add_new_user(request):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    username = request.POST.get("username")
    password = request.POST.get("password")
    role = request.POST.get("role")

    # Enforce ground rules: nurse can only add Karyawan
    role_map = {
        "karyawan": "Karyawan",
        "Karyawan": "Karyawan",
    }
    canonical_role = role_map.get(role)

    if not username or not password or not canonical_role:
        request.session["error_message"] = "Perawat hanya dapat menambah data Karyawan. Username, password, dan role Karyawan wajib diisi."
        return redirect(reverse("nurse:dashboard"))

    try:
        add_user(username, password, canonical_role)
        request.session["success_message"] = f"User '{username}' ditambahkan sebagai '{canonical_role}'!"
    except Exception as e:
        if "unique" in str(e).lower():
            request.session["error_message"] = "Username sudah ada!"
        else:
            request.session["error_message"] = f"Error: {e}"
    return redirect(reverse("nurse:dashboard"))


# -------------------------
# Tab 3: QR Codes
# -------------------------
def nurse_qr_interface(request, uid=None, bulk=False):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    # Mirror manager behavior: allow bulk via GET param or dedicated route
    if request.GET.get("bulk") == "1" or bulk:
        return qr_bulk_download_view(request)

    # Build nurse QR page context and render nurse template
    employees_df = get_employees()

    # Validate employees data
    if employees_df is None or employees_df.empty or not all(col in employees_df.columns for col in ["uid", "nama"]):
        return render(request, "nurse/qr_codes.html", {"error": "Tidak ada data karyawan yang tersedia."})

    # Unique list of employees with uid as str
    karyawan_data = employees_df[["uid", "nama"]].drop_duplicates().copy()
    karyawan_data["uid"] = karyawan_data["uid"].astype(str)

    # Determine selected UID from GET (preferred) or path param
    selected_uid = request.GET.get("uid") or (str(uid) if uid else None)

    # Base context: show list and no preview unless a UID is selected
    context = {
        "employees": karyawan_data.to_dict(orient="records"),
    }

    if not selected_uid:
        return render(request, "nurse/qr_codes.html", context)

    # Get selected employee name
    selected_rows = karyawan_data[karyawan_data["uid"] == selected_uid]
    if selected_rows.empty:
        context.update({"error": "UID karyawan tidak ditemukan.", "selected_uid": selected_uid})
        return render(request, "nurse/qr_codes.html", context)
    selected_name = selected_rows.iloc[0]["nama"]

    # Build QR URL pointing to Karyawan app
    server_url = getattr(settings, "APP_BASE_URL", os.getenv("APP_BASE_URL", "")) or request.build_absolute_uri("/").rstrip("/")
    qr_url = f"{server_url}/karyawan/?uid={selected_uid}"

    # Generate QR code bytes and base64
    qr_bytes = generate_qr_bytes(qr_url)
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")

    context.update({
        "selected_name": selected_name,
        "selected_uid": selected_uid,
        "qr_base64": qr_base64,
    })
    return render(request, "nurse/qr_codes.html", context)


# -------------------------
# Tab 4: Upload Medical Checkup Only
# -------------------------
@require_http_methods(["POST"])
def nurse_upload_checkup(request):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    file = request.FILES.get("file")
    if not file:
        request.session["warning_message"] = "File XLS harus diunggah!"
        return redirect(reverse("nurse:dashboard"))

    try:
        result = checkup_uploader.parse_checkup_xls(file)
        request.session["success_message"] = f"{result['inserted']} checkup berhasil, {len(result['skipped'])} gagal."
    except Exception as e:
        request.session["error_message"] = f"Gagal memproses XLS checkup: {e}"

    return redirect(reverse("nurse:dashboard"))


# -------------------------
# Tab 4: Upload & Export Page (GET)
# -------------------------
@require_http_methods(["GET"])
def nurse_upload_export(request):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    # Pull session messages for toast notifications
    success_message = request.session.pop("success_message", None)
    error_message = request.session.pop("error_message", None)
    warning_message = request.session.pop("warning_message", None)

    # Render the Upload / Export page for nurse (limited features)
    context = {
        "active_menu_label": "Upload / Export Data",
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
    }
    return render(request, "nurse/upload_export.html", context)


# -------------------------
# Tab 6: Edit / Update Karyawan Data
# -------------------------
def nurse_karyawan_detail(request, uid):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    # Handle selector redirect if a different uid is chosen via GET
    requested_uid = request.GET.get("uid")
    if requested_uid and str(requested_uid) != str(uid):
        submenu = request.GET.get("submenu", "edit")
        subtab = request.GET.get("subtab")
        # Allow known submenu keys: edit, history, data_karyawan, edit_data, grafik
        if submenu not in ["edit", "history", "data_karyawan", "edit_data", "grafik"]:
            submenu = "edit"
        # Normalize: route 'edit' and 'edit_data' under data_karyawan with subtab
        if submenu in ["edit", "edit_data"]:
            mapped_subtab = "profile" if submenu == "edit" else "edit_data"
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": requested_uid}) + f"?submenu=data_karyawan&subtab={mapped_subtab}")
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": requested_uid}) + f"?submenu={submenu}{f'&subtab={subtab}' if subtab else ''}")

    # Handle per-row edit or bulk inline save (History Medical Check Up)
    if request.method == "POST" and (request.POST.get("save_changes") or request.POST.get("action") == "edit_row"):
        # Per-row Edit + Save (manager-style)
        if request.POST.get("action") == "edit_row":
            from core.core_models import Checkup
            checkup_id = request.POST.get("checkup_id")
            if checkup_id:
                fields = ["tanggal_checkup","lingkar_perut","gula_darah_puasa","gula_darah_sewaktu","cholesterol","asam_urat","tekanan_darah","derajat_kesehatan"]
                update_data = {}
                for f in fields:
                    val = request.POST.get(f)
                    if val not in (None, ""):
                        update_data[f] = val
                # Normalize tanggal_checkup to date if possible
                try:
                    if update_data.get("tanggal_checkup"):
                        dt = pd.to_datetime(update_data["tanggal_checkup"], errors="coerce")
                        if pd.notna(dt):
                            update_data["tanggal_checkup"] = dt.date()
                except Exception:
                    pass
                if update_data:
                    Checkup.objects.filter(checkup_id=checkup_id).update(**update_data)
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        import json
        from core.core_models import Checkup
        edited_data_raw = request.POST.get("edited_table_data")
        try:
            rows = json.loads(edited_data_raw) if edited_data_raw else []
        except Exception:
            rows = []
        saved = 0
        for item in rows:
            try:
                checkup_id = item.get("checkup_id")
                if not checkup_id:
                    continue
                # Read fields from edited row
                tanggal_checkup = item.get("tanggal_checkup")
                lingkar_perut = item.get("lingkar_perut")
                gula_darah_puasa = item.get("gula_darah_puasa")
                gula_darah_sewaktu = item.get("gula_darah_sewaktu")
                cholesterol = item.get("cholesterol")
                asam_urat = item.get("asam_urat")
                tekanan_darah = item.get("tekanan_darah")
                derajat_kesehatan = item.get("derajat_kesehatan")
                # Safe conversions
                update_data = {
                    "lingkar_perut": float(lingkar_perut) if lingkar_perut not in (None, "") else None,
                    "gula_darah_puasa": float(gula_darah_puasa) if gula_darah_puasa not in (None, "") else None,
                    "gula_darah_sewaktu": float(gula_darah_sewaktu) if gula_darah_sewaktu not in (None, "") else None,
                    "cholesterol": float(cholesterol) if cholesterol not in (None, "") else None,
                    "asam_urat": float(asam_urat) if asam_urat not in (None, "") else None,
                    "tekanan_darah": str(tekanan_darah).strip() if tekanan_darah not in (None, "") else None,
                    "derajat_kesehatan": str(derajat_kesehatan).strip() if derajat_kesehatan not in (None, "") else None,
                }
                if tanggal_checkup:
                    dt = pd.to_datetime(tanggal_checkup, dayfirst=True, errors="coerce")
                    if pd.notna(dt):
                        update_data["tanggal_checkup"] = dt.date()
                # Drop None values to avoid overriding with NULL
                update_data = {k: v for k, v in update_data.items() if v is not None}
                if update_data:
                    Checkup.objects.filter(checkup_id=checkup_id).update(**update_data)
                    saved += 1
            except Exception:
                continue
        # Optional audit log
        try:
            from core.queries import write_manual_input_log
            actor = request.session.get("username") or "unknown"
            write_manual_input_log(uid=str(uid), actor=actor, role="Tenaga Kesehatan", event="manual_checkup_input", changed_fields=[], new_values={}, checkup_id=None)
        except Exception:
            pass
        request.session["success_message"] = f"Berhasil menyimpan {saved} perubahan."
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

    # Determine active submenu and subtab
    active_submenu = request.GET.get("submenu", "data_karyawan")
    active_subtab = request.GET.get("subtab", "profile")

    # Validate submenu under data_karyawan
    if active_submenu == "data_karyawan" and active_subtab not in ["profile", "edit_data"]:
        active_subtab = "profile"

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
            # Include broader set of fields to mirror manager's profile display
            for key in [
                "uid", "nama", "jabatan", "lokasi",
                "tanggal_lahir", "tanggal_MCU", "expired_MCU",
                "derajat_kesehatan", "berat", "tinggi", "bmi", "bmi_category",
                "lingkar_perut", "kontak_darurat"
            ]:
                emp_dict[key] = employee_raw.get(key) if isinstance(employee_raw, dict) else getattr(employee_raw, key, None)
            employee_clean = emp_dict
        except Exception:
            employee_clean = {}

    checkups = get_medical_checkups_by_uid(uid)

    # Compute latest checkup record for display
    latest_checkup = None
    try:
        if checkups is not None and not checkups.empty:
            checkups["tanggal_checkup"] = pd.to_datetime(checkups["tanggal_checkup"], errors="coerce")
            latest_row = checkups.sort_values("tanggal_checkup", ascending=False).iloc[0]
            from core.helpers import compute_status, sanitize_df_for_display as _sanitize
            status = compute_status(latest_row)
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
            latest_disp = _sanitize(pd.DataFrame([latest_row])).iloc[0].to_dict()
            try:
                dt = pd.to_datetime(latest_row.get("tanggal_checkup"), errors="coerce")
                if pd.notna(dt):
                    latest_disp["tanggal_checkup"] = dt.strftime("%d/%m/%y")
            except Exception:
                pass
            latest_disp["status"] = status
            latest_disp["flags"] = flags
            latest_checkup = latest_disp
    except Exception:
        latest_checkup = None

    # Build history records for template
    history_checkups = []
    try:
        if checkups is not None and not checkups.empty:
            df_hist = checkups.copy()
            df_hist["tanggal_checkup"] = pd.to_datetime(df_hist["tanggal_checkup"], errors="coerce")
            df_hist = df_hist.sort_values("tanggal_checkup", ascending=False)
            from core.helpers import compute_status
            for _, row in df_hist.iterrows():
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
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
                    'bmi': float(bmi_n) if pd.notna(bmi_n) else None,
                    'berat': row.get('berat', None),
                    'tinggi': row.get('tinggi', None),
                    'lingkar_perut': row.get('lingkar_perut', None),
                    'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                    'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                    'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                    'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                    'status': status,
                    'flags': flags,
                    'checkup_id': int(row.get('checkup_id')) if row.get('checkup_id') is not None else None,
                })
    except Exception:
        history_checkups = []

    # Build dashboard-like history records (similar to manager's history_dashboard)
    history_dashboard = []
    try:
        if checkups is not None and not checkups.empty:
            df_hist2 = checkups.copy()
            # Normalize uid column if needed
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

            # Build per-row dashboard entries
            for _, row in df_hist2.iterrows():
                # Parse numerics safely
                umur_val = row.get('umur', None)
                tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
                berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
                lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
                gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')

                # Date formatting
                tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None

                # Status based on thresholds (use parsed numerics to avoid string issues)
                status_val = compute_status({
                    'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                    'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                    'cholesterol': chol_n if pd.notna(chol_n) else 0,
                    'asam_urat': asam_n if pd.notna(asam_n) else 0,
                    'bmi': bmi_n if pd.notna(bmi_n) else 0,
                })

                # Flags for conditional highlighting (match manager thresholds)
                flags = {
                    'bmi_high': (pd.notna(bmi_n) and bmi_n >= 30),
                    'gdp_high': (pd.notna(gdp_n) and gdp_n > 120),
                    'gds_high': (pd.notna(gds_n) and gds_n > 200),
                    'chol_high': (pd.notna(chol_n) and chol_n > 240),
                    'asam_high': (pd.notna(asam_n) and asam_n > 7),
                }

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
                    'bmi': float(bmi_n) if pd.notna(bmi_n) else None,
                    'lingkar_perut': float(lp_n) if pd.notna(lp_n) else None,
                    'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                    'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                    'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                    'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                    'tekanan_darah': row.get('tekanan_darah', None),
                    'derajat_kesehatan': str(row.get('derajat_kesehatan')) if row.get('derajat_kesehatan') is not None else None,
                    'tanggal_MCU': emp_tanggal_mcu,
                    'expired_MCU': emp_expired_mcu,
                    'status': status_val,
                    'flags': flags,
                    'checkup_id': int(row.get('checkup_id')) if row.get('checkup_id') is not None else None,
                })
    except Exception:
        history_dashboard = []

    # Grafik (match manager employee_profile)
    grafik_chart_html = None
    grafik_start_month = request.GET.get('start_month')
    grafik_end_month = request.GET.get('end_month')
    if active_submenu == 'grafik':
        try:
            # Default to last 6 months
            today = datetime.today()
            def _month_str(dt):
                return f"{dt.year}-{dt.month:02d}"
            if not grafik_end_month:
                grafik_end_month = _month_str(today)
            if not grafik_start_month:
                grafik_start_month = _month_str(today - pd.DateOffset(months=5))

            df_ts = checkups.copy()
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
                        fig.add_trace(go.Scatter(x=x_vals, y=gdp, mode='lines+markers', name='Gula Darah Puasa'))
                    if gds is not None and not gds.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=gds, mode='lines+markers', name='Gula Darah Sewaktu'))
                    if td_systolic is not None and not td_systolic.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=td_systolic, mode='lines+markers', name='Tekanan Darah (Sistole)'))
                    if lp is not None and not lp.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=lp, mode='lines+markers', name='Lingkar Perut'))
                    if chol is not None and not chol.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=chol, mode='lines+markers', name='Cholesterol'))
                    if asam is not None and not asam.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=asam, mode='lines+markers', name='Asam Urat'))

                    fig.update_layout(
                        title='Grafik',
                        xaxis_title='Tanggal Checkup',
                        yaxis_title='Nilai',
                        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                        margin=dict(l=40, r=20, t=60, b=40),
                        template='plotly_white'
                    )
                    grafik_chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')
        except Exception:
            grafik_chart_html = None
    else:
        grafik_chart_html = None

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

    # Dynamically control view-only mode: enable inline editing on History tab
    view_only_flag = False if active_submenu == "history" else True

    return render(request, "nurse/edit_karyawan.html", {
        "employee": employee_clean or {},
        "employees": employees,
        "checkups": checkups,
        "latest_checkup": latest_checkup,
        "history_checkups": history_checkups,
        "history_dashboard": history_dashboard,
        "active_submenu": active_submenu,
        "active_subtab": active_subtab,
        "active_menu_label": "Edit Data Checkup",
        "view_only": view_only_flag,
        "mcu_expiry_estimate": mcu_expiry_estimate,
        "grafik_chart_html": grafik_chart_html,
        "grafik_start_month": grafik_start_month,
        "grafik_end_month": grafik_end_month,
    })


@require_http_methods(["POST"])
def nurse_save_medical_checkup(request, uid):
    # Check if user is logged in and is a nurse
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    try:
        tanggal_checkup = request.POST.get("tanggal_checkup")
        tinggi = request.POST.get("tinggi")
        berat = request.POST.get("berat")
        lingkar_perut = request.POST.get("lingkar_perut")
        bmi = request.POST.get("bmi")
        umur = request.POST.get("umur")
        gula_darah_puasa = request.POST.get("gula_darah_puasa")
        gula_darah_sewaktu = request.POST.get("gula_darah_sewaktu")
        cholesterol = request.POST.get("cholesterol")
        asam_urat = request.POST.get("asam_urat")
        tekanan_darah = request.POST.get("tekanan_darah")
        derajat_kesehatan = request.POST.get("derajat_kesehatan")

        # BMI is captured as provided; no auto-calculation
        bmi_value = float(bmi) if bmi else None

        # Determine checkup date
        tanggal_checkup_date = pd.to_datetime(tanggal_checkup).date() if tanggal_checkup else datetime.today().date()

        # Umur is captured as provided; no auto-calculation
        try:
            umur_value = int(umur) if umur else None
        except Exception:
            umur_value = None

        record = {
            "uid": uid,
            "tanggal_checkup": tanggal_checkup_date,
            "tinggi": float(tinggi) if tinggi else None,
            "berat": float(berat) if berat else None,
            "lingkar_perut": float(lingkar_perut) if lingkar_perut else None,
            "bmi": float(bmi) if bmi else bmi_value,
            "umur": umur_value,
            "gula_darah_puasa": float(gula_darah_puasa) if gula_darah_puasa else None,
            "gula_darah_sewaktu": float(gula_darah_sewaktu) if gula_darah_sewaktu else None,
            "cholesterol": float(cholesterol) if cholesterol else None,
            "asam_urat": float(asam_urat) if asam_urat else None,
            "tekanan_darah": tekanan_darah.strip() if tekanan_darah else None,
            "derajat_kesehatan": derajat_kesehatan.strip() if derajat_kesehatan else None,
        }

        insert_medical_checkup(**record)
        request.session["success_message"] = "Pemeriksaan medis berhasil disimpan."
    except Exception as e:
        request.session["error_message"] = f"Gagal menyimpan checkup: {e}"

    return redirect(reverse("nurse:dashboard"))


@require_http_methods(["GET"])
def nurse_download_checkup_template(request):
    """Download Excel template for recording medical checkup data (available to nurse)."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        excel_file = generate_karyawan_template_excel()
        response = HttpResponse(
            excel_file,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="Checkup_Template.xlsx"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Failed to generate checkup template: {e}"
        return redirect(reverse("nurse:upload_export"))

# New: PDF export of dashboard-like checkup data for nurse
@require_http_methods(["GET"]) 
def nurse_export_checkup_data(request):
    # Export all checkup data visible in dashboard (XLS)
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        df = get_dashboard_checkup_data()
        if df is None or df.empty:
            request.session["warning_message"] = "belum ada check up data, silahkan unggah terlebih dahulu"
            return redirect(reverse("nurse:upload_export") + "?submenu=export_data")
        excel_bytes = build_checkup_excel(df)
        response = HttpResponse(
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="medical_checkup_data.xlsx"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Gagal mengekspor data checkup: {e}"
        return redirect(reverse("nurse:upload_export") + "?submenu=export_data")

@require_http_methods(["GET"]) 
def nurse_export_checkup_data_pdf(request):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        df = get_dashboard_checkup_data()
        if df is None or df.empty:
            request.session["warning_message"] = "belum ada check up data, silahkan unggah terlebih dahulu"
            return redirect(reverse("nurse:upload_export") + "?submenu=export_data")
        pdf_bytes = build_checkup_pdf(df)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="medical_checkup_data.pdf"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Gagal mengekspor data checkup ke PDF: {e}"
        return redirect(reverse("nurse:upload_export") + "?submenu=export_data")

# New: Delete a checkup row (hapus)
@require_http_methods(["POST", "GET"]) 
def nurse_delete_checkup(request, checkup_id):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    from core.queries import delete_checkup
    try:
        delete_checkup(checkup_id)
        request.session["success_message"] = "Checkup berhasil dihapus."
    except Exception as e:
        request.session["error_message"] = f"Gagal menghapus checkup: {e}"
    # Redirect back to employee detail if uid is provided; else to dashboard
    uid = request.GET.get("uid")
    submenu = request.GET.get("submenu", "history")
    if uid:
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + f"?submenu={submenu}")
    return redirect(reverse("nurse:dashboard"))

# New: Edit a checkup row
@require_http_methods(["GET", "POST"]) 
def nurse_edit_checkup(request, checkup_id):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    from core.core_models import Checkup
    # Fetch existing record
    obj = Checkup.objects.filter(checkup_id=checkup_id).first()
    if obj is None:
        request.session["error_message"] = "Checkup tidak ditemukan"
        return redirect(reverse("nurse:dashboard"))

    if request.method == "POST":
        try:
            # Read and normalize inputs
            tanggal_checkup = request.POST.get("tanggal_checkup")
            tinggi = request.POST.get("tinggi")
            berat = request.POST.get("berat")
            lingkar_perut = request.POST.get("lingkar_perut")
            bmi = request.POST.get("bmi")
            umur = request.POST.get("umur")
            gula_darah_puasa = request.POST.get("gula_darah_puasa")
            gula_darah_sewaktu = request.POST.get("gula_darah_sewaktu")
            cholesterol = request.POST.get("cholesterol")
            asam_urat = request.POST.get("asam_urat")
            tekanan_darah = request.POST.get("tekanan_darah")
            derajat_kesehatan = request.POST.get("derajat_kesehatan")

            # Safe conversions
            import pandas as pd
            tanggal_checkup_date = pd.to_datetime(tanggal_checkup, errors="coerce")
            # Apply updates
            update_data = {
                "tinggi": float(tinggi) if tinggi else None,
                "berat": float(berat) if berat else None,
                "lingkar_perut": float(lingkar_perut) if lingkar_perut else None,
                "bmi": float(bmi) if bmi else None,
                "umur": int(umur) if umur else None,
                "gula_darah_puasa": float(gula_darah_puasa) if gula_darah_puasa else None,
                "gula_darah_sewaktu": float(gula_darah_sewaktu) if gula_darah_sewaktu else None,
                "cholesterol": float(cholesterol) if cholesterol else None,
                "asam_urat": float(asam_urat) if asam_urat else None,
                "tekanan_darah": tekanan_darah.strip() if tekanan_darah else None,
                "derajat_kesehatan": derajat_kesehatan.strip() if derajat_kesehatan else None,
            }
            if pd.notna(tanggal_checkup_date):
                update_data["tanggal_checkup"] = tanggal_checkup_date.date()
            Checkup.objects.filter(checkup_id=checkup_id).update(**update_data)
            request.session["success_message"] = "Checkup berhasil diperbarui."
            # Redirect back to karyawan detail
            uid = str(obj.uid_id)
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        except Exception as e:
            request.session["error_message"] = f"Gagal memperbarui checkup: {e}"
            uid = str(obj.uid_id)
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

    # GET: render edit form
    return render(request, "nurse/edit_checkup.html", {"checkup": obj})


@require_http_methods(["GET"])
def nurse_export_karyawan_data(request):
    """Export all employee master data to Excel (available to nurse)."""
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        df = get_employees().copy()
        if df.empty:
            request.session["warning_message"] = "Tidak ada data karyawan untuk diekspor."
            return redirect(reverse("nurse:upload_export"))

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Data Karyawan")
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="data_karyawan.xlsx"'
        return response
    except Exception as e:
        request.session["error_message"] = f"Gagal mengekspor data karyawan: {e}"
        return redirect(reverse("nurse:upload_export"))


# -------------------------
# Avatar Upload (Nurse)
# -------------------------
@require_http_methods(["POST"])
def upload_avatar(request):
    # Only Nurse can upload own avatar
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    file = request.FILES.get("avatar")
    if not file:
        request.session["error_message"] = "Tidak ada file yang diunggah."
        return redirect(reverse("nurse:dashboard"))

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
        return redirect(reverse("nurse:dashboard"))
    max_size = 2 * 1024 * 1024
    if getattr(file, "size", 0) > max_size:
        request.session["error_message"] = "Ukuran file terlalu besar (maks 2MB)."
        return redirect(reverse("nurse:dashboard"))

    # Determine username
    username = request.session.get("username") or getattr(getattr(request, "user", None), "username", None)
    if not username:
        request.session["error_message"] = "Tidak dapat menentukan pengguna untuk avatar."
        return redirect(reverse("nurse:dashboard"))

    # Prepare directories
    from django.conf import settings
    import os
    target_dir = os.path.join(settings.MEDIA_ROOT, "avatars", "nurse")
    os.makedirs(target_dir, exist_ok=True)

    # Remove existing avatars for this user across supported extensions
    for old_ext in ["jpg", "jpeg", "png", "webp", "gif"]:
        old_path = os.path.join(target_dir, f"{username}.{old_ext}")
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass

    # Save new avatar
    target_path = os.path.join(target_dir, f"{username}.{ext}")
    try:
        with open(target_path, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)
        request.session["success_message"] = "Avatar berhasil diunggah!"
    except Exception as e:
        request.session["error_message"] = f"Gagal menyimpan avatar: {e}"

    return redirect(reverse("nurse:dashboard"))

@require_http_methods(["GET"]) 
def nurse_export_checkup_history_by_uid(request, uid):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        from core.core_models import Karyawan
        if not Karyawan.objects.filter(uid=uid).exists():
            request.session['error_message'] = f"UID {uid} tidak ditemukan."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        df = get_medical_checkups_by_uid(uid)
        if df is None or df.empty:
            request.session['warning_message'] = "Tidak ada data checkup untuk UID ini."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        # Normalize
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})
        if "tanggal_checkup" in df.columns:
            df["tanggal_checkup"] = pd.to_datetime(df["tanggal_checkup"], errors="coerce")
        df = df.sort_values("tanggal_checkup", ascending=False)

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}
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

        # umur and employee BMI fallback
        try:
            umur_val_emp = (employee_clean or {}).get('umur', None)
        except Exception:
            umur_val_emp = None
        try:
            emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
        except Exception:
            emp_bmi = None

        from core.helpers import compute_bmi_category
        rows = []
        for _, row in df.iterrows():
            tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
            berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
            bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
            # BMI fallback: use employee BMI if row BMI missing/zero
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

            dk_val = row.get('derajat_kesehatan', None)
            try:
                if dk_val is None or (isinstance(dk_val, float) and pd.isna(dk_val)) or (isinstance(dk_val, str) and not dk_val.strip()):
                    dk_val = (employee_clean or {}).get('derajat_kesehatan')
            except Exception:
                pass

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
                'Umur': int(umur_val_emp) if pd.notna(pd.to_numeric(umur_val_emp, errors='coerce')) else None,
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
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"]) 
def nurse_export_checkup_history_by_uid_pdf(request, uid):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        from core.core_models import Karyawan
        if not Karyawan.objects.filter(uid=uid).exists():
            request.session['error_message'] = f"UID {uid} tidak ditemukan."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        df = get_medical_checkups_by_uid(uid)
        if df is None or df.empty:
            request.session['warning_message'] = "Tidak ada data checkup untuk UID ini."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})
        if "tanggal_checkup" in df.columns:
            df["tanggal_checkup"] = pd.to_datetime(df["tanggal_checkup"], errors="coerce")
        df = df.sort_values("tanggal_checkup", ascending=False)

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}
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

        try:
            emp_bmi = pd.to_numeric((employee_clean or {}).get('bmi', None), errors='coerce')
        except Exception:
            emp_bmi = None
        umur_val_emp = (employee_clean or {}).get('umur', None)

        from core.helpers import compute_bmi_category
        rows = []
        for _, row in df.iterrows():
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
                'Umur': int(umur_val_emp) if pd.notna(pd.to_numeric(umur_val_emp, errors='coerce')) else None,
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
        filename = f"checkup_history_{uid}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor riwayat checkup ke PDF: {e}"
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"]) 
def nurse_export_checkup_row(request, uid, checkup_id):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        from core.core_models import Checkup
        qs = Checkup.objects.filter(checkup_id=checkup_id, uid_id=uid)
        if not qs.exists():
            request.session['error_message'] = "Checkup tidak ditemukan untuk UID terkait."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        import pandas as _pd
        df = _pd.DataFrame(list(qs.values()))
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}
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
        umur_val_emp = employee_clean.get('umur', None)
        emp_bmi = pd.to_numeric(employee_clean.get('bmi', None), errors='coerce')

        from core.helpers import compute_bmi_category
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
                'Umur': int(umur_val_emp) if pd.notna(pd.to_numeric(umur_val_emp, errors='coerce')) else None,
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

        excel_bytes = build_checkup_excel(df_export, enrich=False, columns=columns_order)
        filename = f"checkup_{checkup_id}.xlsx"
        response = HttpResponse(excel_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e:
        request.session['error_message'] = f"Gagal mengekspor data checkup: {e}"
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

@require_http_methods(["GET"]) 
def nurse_export_checkup_row_pdf(request, uid, checkup_id):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        from core.core_models import Checkup
        qs = Checkup.objects.filter(checkup_id=checkup_id, uid_id=uid)
        if not qs.exists():
            request.session['error_message'] = "Checkup tidak ditemukan untuk UID terkait."
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")
        import pandas as _pd
        df = _pd.DataFrame(list(qs.values()))
        if "uid_id" in df.columns and "uid" not in df.columns:
            df = df.rename(columns={"uid_id": "uid"})

        # Fetch employee baseline for fallbacks
        employee_clean = get_employee_by_uid(uid) or {}
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
        umur_val_emp = employee_clean.get('umur', None)
        emp_bmi = pd.to_numeric(employee_clean.get('bmi', None), errors='coerce')

        from core.helpers import compute_bmi_category
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
                'Umur': int(umur_val_emp) if pd.notna(pd.to_numeric(umur_val_emp, errors='coerce')) else None,
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
        request.session['error_message'] = f"Gagal mengekspor data checkup ke PDF: {e}"
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": uid}) + "?submenu=history")

# Internal helper to generate grafik_chart_html without rendering

def nurse_grafik_kesehatan_logic(request):
    uid = request.GET.get('uid', 'all')
    now2 = pd.Timestamp.now()
    default_end_month = now2.strftime('%Y-%m')
    default_start_month = (now2 - pd.offsets.DateOffset(months=5)).strftime('%Y-%m')
    grafik_start_month = request.GET.get('start_month', default_start_month)
    grafik_end_month = request.GET.get('end_month', default_end_month)

    grafik_chart_html = None
    try:
        if uid and uid != 'all':
            df_ts = get_medical_checkups_by_uid(uid) or pd.DataFrame()
            if df_ts is not None and not df_ts.empty:
                df_ts = df_ts.copy()
                df_ts['tanggal_checkup'] = pd.to_datetime(df_ts['tanggal_checkup'], errors='coerce')
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
                        fig.add_trace(go.Scatter(x=x_vals, y=gdp, mode='lines+markers', name='Gula Darah Puasa'))
                    if gds is not None and not gds.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=gds, mode='lines+markers', name='Gula Darah Sewaktu'))
                    if td_systolic is not None and not td_systolic.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=td_systolic, mode='lines+markers', name='Tekanan Darah (Sistole)'))
                    if lp is not None and not lp.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=lp, mode='lines+markers', name='Lingkar Perut'))
                    if chol is not None and not chol.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=chol, mode='lines+markers', name='Cholesterol'))
                    if asam is not None and not asam.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=asam, mode='lines+markers', name='Asam Urat'))

                    fig.update_layout(
                        title='Grafik',
                        xaxis_title='Tanggal Checkup',
                        yaxis_title='Nilai',
                        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                        margin=dict(l=40, r=20, t=60, b=40),
                        template='plotly_white'
                    )
                    grafik_chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')
        else:
            try:
                df = load_checkups()
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                try:
                    df = get_dashboard_checkup_data()
                except Exception:
                    df = pd.DataFrame()

            date_col = None
            if not df.empty and 'tanggal_checkup' in df.columns:
                df['tanggal_checkup'] = pd.to_datetime(df['tanggal_checkup'], errors='coerce', dayfirst=True)
                date_col = 'tanggal_checkup'
            elif not df.empty and 'tanggal_MCU' in df.columns:
                df['tanggal_MCU'] = pd.to_datetime(df['tanggal_MCU'], errors='coerce', dayfirst=True)
                date_col = 'tanggal_MCU'

            if date_col is not None:
                df = df.dropna(subset=[date_col])
                start_dt = pd.to_datetime(grafik_start_month + '-01', errors='coerce') if grafik_start_month else None
                end_dt = pd.to_datetime(grafik_end_month + '-01', errors='coerce') if grafik_end_month else None
                if pd.notnull(end_dt):
                    end_dt = (end_dt + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
                if pd.notnull(start_dt) and pd.notnull(end_dt):
                    df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]

                numeric_cols = [
                    'gula_darah_puasa', 'gula_darah_sewaktu',
                    'cholesterol', 'asam_urat', 'bmi'
                ]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                if not df.empty:
                    grouped = df.groupby(date_col)[numeric_cols].mean().reset_index()

                    fig = go.Figure()
                    label_map = {
                        'gula_darah_puasa': 'Gula Darah Puasa',
                        'gula_darah_sewaktu': 'Gula Darah Sewaktu',
                        'cholesterol': 'Cholesterol',
                        'asam_urat': 'Asam Urat',
                        'bmi': 'BMI',
                    }
                    for col in numeric_cols:
                        if col in grouped.columns:
                            fig.add_trace(go.Scatter(
                                x=grouped[date_col],
                                y=grouped[col],
                                mode='lines+markers',
                                name=label_map.get(col, col.replace('_', ' ').title())
                            ))
                    fig.update_layout(
                        title='Rata-rata Parameter MCU Semua Karyawan',
                        xaxis_title='Tanggal Checkup',
                        yaxis_title='Nilai Pemeriksaan',
                        template='plotly_white',
                        height=500
                    )
                    grafik_chart_html = pio.to_html(fig, include_plotlyjs='cdn', full_html=False)
    except Exception:
        grafik_chart_html = None

    return grafik_chart_html

@require_http_methods(["GET"]) 
def nurse_grafik_kesehatan(request):
    # Nurse-only access
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")

    # Employee selector (same as dashboard, but we will reuse Edit Data Checkup → Grafik logic when a UID is selected)
    available_employees = []
    try:
        df_emps = get_employees()
        if hasattr(df_emps, 'empty') and not df_emps.empty and 'uid' in df_emps.columns and 'nama' in df_emps.columns:
            for _, row in df_emps.iterrows():
                uid = str(row['uid']) if pd.notna(row['uid']) else ''
                nama = str(row['nama']) if pd.notna(row['nama']) else f'UID {uid}'
                if uid:
                    available_employees.append({'uid': uid, 'nama': nama})
    except Exception:
        pass
    available_employees = sorted(available_employees, key=lambda x: x['nama'].lower())

    # Month range defaults (last 6 months)
    now2 = pd.Timestamp.now()
    default_end_month = now2.strftime('%Y-%m')
    default_start_month = (now2 - pd.offsets.DateOffset(months=5)).strftime('%Y-%m')
    grafik_start_month = request.GET.get('start_month', default_start_month)
    grafik_end_month = request.GET.get('end_month', default_end_month)

    uid = request.GET.get('uid', '')

    grafik_chart_html = None
    try:
        # If a specific employee is selected, reuse the exact logic from Edit Data Checkup → Grafik
        if uid and uid != 'all':
            df_ts = get_medical_checkups_by_uid(uid) or pd.DataFrame()
            if df_ts is not None and not df_ts.empty:
                df_ts = df_ts.copy()
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
                        fig.add_trace(go.Scatter(x=x_vals, y=gdp, mode='lines+markers', name='Gula Darah Puasa'))
                    if gds is not None and not gds.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=gds, mode='lines+markers', name='Gula Darah Sewaktu'))
                    if td_systolic is not None and not td_systolic.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=td_systolic, mode='lines+markers', name='Tekanan Darah (Sistole)'))
                    if lp is not None and not lp.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=lp, mode='lines+markers', name='Lingkar Perut'))
                    if chol is not None and not chol.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=chol, mode='lines+markers', name='Cholesterol'))
                    if asam is not None and not asam.empty:
                        fig.add_trace(go.Scatter(x=x_vals, y=asam, mode='lines+markers', name='Asam Urat'))

                    fig.update_layout(
                        title='Grafik',
                        xaxis_title='Tanggal Checkup',
                        yaxis_title='Nilai',
                        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                        margin=dict(l=40, r=20, t=60, b=40),
                        template='plotly_white'
                    )
                    grafik_chart_html = pio.to_html(fig, full_html=False, include_plotlyjs='cdn')
        else:
            # Mode: Semua Karyawan — aggregate by date using the same parameters as per-UID logic
            try:
                df = load_checkups()
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                try:
                    df = get_dashboard_checkup_data()
                except Exception:
                    df = pd.DataFrame()

            # Prefer tanggal_checkup; fallback to tanggal_MCU
            date_col = None
            if not df.empty and 'tanggal_checkup' in df.columns:
                df['tanggal_checkup'] = pd.to_datetime(df['tanggal_checkup'], errors='coerce', dayfirst=True)
                date_col = 'tanggal_checkup'
            elif not df.empty and 'tanggal_MCU' in df.columns:
                df['tanggal_MCU'] = pd.to_datetime(df['tanggal_MCU'], errors='coerce', dayfirst=True)
                date_col = 'tanggal_MCU'

            if date_col is None:
                grafik_chart_html = None
            else:
                # Drop invalid dates and filter by month range
                df = df.dropna(subset=[date_col])
                start_dt = pd.to_datetime(grafik_start_month + '-01', errors='coerce') if grafik_start_month else None
                end_dt = pd.to_datetime(grafik_end_month + '-01', errors='coerce') if grafik_end_month else None
                if pd.notnull(end_dt):
                    end_dt = (end_dt + pd.offsets.MonthBegin(1)) - pd.Timedelta(days=1)
                if pd.notnull(start_dt) and pd.notnull(end_dt):
                    df = df[(df[date_col] >= start_dt) & (df[date_col] <= end_dt)]

                # Convert relevant parameters to numeric
                numeric_cols = [
                    'gula_darah_puasa', 'gula_darah_sewaktu',
                    'cholesterol', 'asam_urat', 'bmi'
                ]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                if df.empty:
                    grafik_chart_html = None
                else:
                    # Group by date and take mean to aggregate all employees
                    grouped = df.groupby(date_col)[numeric_cols].mean().reset_index()

                    # Build Plotly figure
                    fig = go.Figure()
                    label_map = {
                        'gula_darah_puasa': 'Gula Darah Puasa',
                        'gula_darah_sewaktu': 'Gula Darah Sewaktu',
                        'cholesterol': 'Cholesterol',
                        'asam_urat': 'Asam Urat',
                        'bmi': 'BMI',
                    }
                    for col in numeric_cols:
                        if col in grouped.columns:
                            fig.add_trace(go.Scatter(
                                x=grouped[date_col],
                                y=grouped[col],
                                mode='lines+markers',
                                name=label_map.get(col, col.replace('_', ' ').title())
                            ))
                    fig.update_layout(
                        title='Rata-rata Parameter MCU Semua Karyawan',
                        xaxis_title='Tanggal Checkup',
                        yaxis_title='Nilai Pemeriksaan',
                        template='plotly_white',
                        height=500
                    )
                    grafik_chart_html = pio.to_html(fig, include_plotlyjs='cdn', full_html=False)
    except Exception:
        grafik_chart_html = None

    context = {
        'grafik_subtab': 'grafik_kesehatan',
        'grafik_start_month': grafik_start_month,
        'grafik_end_month': grafik_end_month,
        'available_employees': available_employees,
        'default_start_month': default_start_month,
        'default_end_month': default_end_month,
        'grafik_chart_html': grafik_chart_html,
    }
    return render(request, 'nurse_dashboard/grafik/grafik_kesehatan.html', context)

@require_http_methods(["GET"]) 
def nurse_grafik_well_unwell(request):
    if not request.session.get("authenticated") or request.session.get("user_role") != "Tenaga Kesehatan":
        return redirect("accounts:login")
    try:
        base_df = get_dashboard_checkup_data()
    except Exception:
        base_df = pd.DataFrame()
    all_lokasi = []
    if base_df is not None and not base_df.empty and 'lokasi' in base_df.columns:
        all_lokasi = sorted([str(x) for x in base_df['lokasi'].dropna().unique().tolist()])
    context = {
        'grafik_subtab': 'well_unwell',
        'available_lokasi': all_lokasi,
    }
    return render(request, 'nurse_dashboard/grafik/well_unwell.html', context)
