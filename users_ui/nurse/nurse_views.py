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
from utils.export_utils import generate_karyawan_template_excel

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
    employees = df_page.to_dict("records")

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

        # Build Plotly figure
        if not pivot.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=pivot.index, y=pivot.get('well', 0), mode='lines+markers', name='Well', line=dict(color='green')))
            fig.add_trace(go.Scatter(x=pivot.index, y=pivot.get('unwell', 0), mode='lines+markers', name='Unwell', line=dict(color='red')))
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
        "grafik_chart_html": grafik_chart_html,
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
        # Allow known submenu keys: edit, history, data_karyawan, edit_data
        if submenu not in ["edit", "history", "data_karyawan", "edit_data"]:
            submenu = "edit"
        # Normalize: route 'edit' and 'edit_data' under data_karyawan with subtab
        if submenu in ["edit", "edit_data"]:
            mapped_subtab = "profile" if submenu == "edit" else "edit_data"
            return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": requested_uid}) + f"?submenu=data_karyawan&subtab={mapped_subtab}")
        return redirect(reverse("nurse:karyawan_detail", kwargs={"uid": requested_uid}) + f"?submenu={submenu}{f'&subtab={subtab}' if subtab else ''}")

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
            for key in ["uid", "nama", "jabatan", "lokasi", "tanggal_lahir"]:
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
                })
    except Exception:
        history_checkups = []

    return render(request, "nurse/edit_karyawan.html", {
        "employee": employee_clean or {},
        "employees": employees,
        "checkups": checkups,
        "latest_checkup": latest_checkup,
        "history_checkups": history_checkups,
        "active_submenu": active_submenu,
        "active_subtab": active_subtab,
        "active_menu_label": "Edit Karyawan",
        "view_only": True,
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
        derajat_kesehatan = request.POST.get("derajat_kesehatan")

        # Compute BMI server-side if not provided
        bmi_value = None
        try:
            if berat and tinggi:
                berat_f = float(berat)
                tinggi_cm = float(tinggi)
                if berat_f > 0 and tinggi_cm > 0:
                    tinggi_m = tinggi_cm / 100.0
                    bmi_value = round(berat_f / (tinggi_m ** 2), 2)
        except Exception:
            bmi_value = None

        record = {
            "uid": uid,
            "tanggal_checkup": pd.to_datetime(tanggal_checkup).date() if tanggal_checkup else datetime.today().date(),
            "tinggi": float(tinggi) if tinggi else None,
            "berat": float(berat) if berat else None,
            "lingkar_perut": float(lingkar_perut) if lingkar_perut else None,
            "bmi": float(bmi) if bmi else bmi_value,
            "umur": int(umur) if umur else None,
            "gula_darah_puasa": float(gula_darah_puasa) if gula_darah_puasa else None,
            "gula_darah_sewaktu": float(gula_darah_sewaktu) if gula_darah_sewaktu else None,
            "cholesterol": float(cholesterol) if cholesterol else None,
            "asam_urat": float(asam_urat) if asam_urat else None,
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
