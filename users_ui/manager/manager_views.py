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
import os
from utils.validators import safe_date, validate_lokasi, normalize_string

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
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    active_menu = "dashboard"  # Changed to match the mapping in get_active_menu_for_view
    active_submenu = request.GET.get('submenu', 'data')
    
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
    
    # Get all available locations before filtering (exclude empty values)
    all_lokasi = sorted([loc for loc in df['lokasi'].dropna().unique().tolist() if str(loc).strip()])
    
    # Make an unfiltered copy for card totals (keep cards constant when filters change)
    df_all = df.copy()
    
    # Get filter parameters
    filters = {
        'nama': request.GET.get('nama', ''),
        'jabatan': request.GET.get('jabatan', ''),
        'lokasi': request.GET.get('lokasi', ''),  # Single location selection
        'status': request.GET.get('status', ''),  # New status filter
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
    
    # Convert DataFrame to list of dictionaries for template
    employees = df_page.to_dict('records')
    
    # Get dashboard statistics
    users_df = get_users()
    checkups_today = 0  # Will be updated when checkup data is uploaded
    active_nurses = len(users_df[users_df['role'] == 'nurse']) if not users_df.empty else 0
    pending_reviews = 0  # Will be updated when checkup data is uploaded

    # Initialize chart data for grafik
    grafik_chart_html = None
    grafik_filter_mode = request.GET.get('grafik_mode', 'month')  # 'month' or 'week'
    grafik_month = request.GET.get('grafik_month', '')  # e.g., '2025-10'

    # Build time series from all checkups (not just latest) to plot trend
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
            # Use ISO week filter if provided via grafik_month as 'YYYY-Www'
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

        # Build Plotly figure
        if not pivot.empty:
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
        latest_check_date_disp = dt_max.strftime('%Y-%m-%d') if pd.notnull(dt_max) else None
    try:
        hist_df = get_checkup_upload_history()
        if hasattr(hist_df, 'empty') and not hist_df.empty:
            latest = hist_df.iloc[0]
            ts_val = latest.get('timestamp', None)
            ts_disp = ts_val.strftime('%Y-%m-%d %H:%M') if pd.notnull(ts_val) else '-'
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
        'grafik_chart_html': grafik_chart_html,
        'grafik_filter_mode': grafik_filter_mode,
    }
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
        {"key": "edit_karyawan", "name": "Edit Karyawan Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
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
        {"key": "edit_karyawan", "name": "Edit Karyawan Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
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

            result = checkup_uploader.parse_checkup_xls(save_path)
            # Write log entry for this upload
            write_checkup_upload_log(original_name, result)
            request.session['success_message'] = "Excel berhasil di upload!"
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

    # Determine active subtab (karyawan or upload_history)
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
        'MEDIA_URL': settings.MEDIA_URL,
    }

    return render(request, "manager/data_management.html", context)



# -------------------------
# Tab 5b: Delete Single Employee
# -------------------------
def delete_karyawan(request, uid):
    """Delete a single employee by UID safely and return to main data page."""
    from core.queries import delete_employee_by_uid  # Ensure this exists

    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        delete_employee_by_uid(uid)
        request.session['success_message'] = "Employee deleted successfully"
    except Exception as e:
        request.session['error_message'] = f"Failed to delete employee: {e}"

    # Redirect back to the main Hapus Data Karyawan page
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
    if active_submenu not in ["data_karyawan", "history"]:
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

    # Validate subtab under data_karyawan (allow profile, edit_data, tambah)
    if active_submenu == "data_karyawan" and active_subtab not in ["profile", "edit_data", "tambah"]:
        active_subtab = "profile"

    # Handle V2 Edit Karyawan Data submission (manager only)
    if request.method == "POST" and active_submenu == "data_karyawan" and active_subtab == "edit_data":
        nama = (request.POST.get("nama") or "").strip()
        jabatan = (request.POST.get("jabatan") or "").strip()
        lokasi = (request.POST.get("lokasi") or "").strip()
        tanggal_lahir_raw = request.POST.get("tanggal_lahir")
        tanggal_lahir = safe_date(tanggal_lahir_raw)

        # Validate lokasi if provided
        if lokasi and not validate_lokasi(lokasi):
            request.session['error_message'] = "Lokasi tidak valid. Pilih lokasi yang tersedia."
            return redirect(reverse("manager:edit_karyawan", kwargs={'uid': uid}) + "?submenu=data_karyawan&subtab=edit_data")

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

        try:
            df_updates = pd.DataFrame([row])
            updated_count = save_manual_karyawan_edits(df_updates)
            if updated_count > 0:
                request.session['success_message'] = "Data karyawan berhasil diperbarui."
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
            for key in ["uid", "nama", "jabatan", "lokasi", "tanggal_lahir"]:
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

            from core.helpers import compute_status as _compute_status
            for _, row in df_hist2.iterrows():
                # Numeric coercion for safety
                tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
                berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
                lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
                gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
                # Age: use row['umur'] if present, else compute
                umur_val = row.get('umur', None)
                try:
                    if pd.isna(umur_val):
                        tl_dt = pd.to_datetime((employee_clean or {}).get('tanggal_lahir'), errors='coerce')
                        tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                        if pd.notna(tl_dt) and pd.notna(tc_dt):
                            umur_val = int((tc_dt.date() - tl_dt.date()).days // 365)
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
                    'tanggal_MCU': None,
                    'expired_MCU': None,
                    'status': status_val,
                })
    except Exception:
        history_dashboard = []

    # Messages and lokasi options
    success_message = request.session.pop('success_message', None)
    error_message = request.session.pop('error_message', None)
    available_lokasi = get_all_lokasi()

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

        # Compute BMI server-side (if inputs provided)
        bmi = None
        try:
            if tinggi and berat:
                t = float(tinggi)
                b = float(berat)
                bmi = round(b / ((t / 100) ** 2), 2) if t > 0 else None
        except Exception:
            bmi = None

        # Determine checkup date
        tanggal_checkup_date = pd.to_datetime(tanggal_checkup).date() if tanggal_checkup else datetime.today().date()

        # Auto-calculate umur if not provided, using employee birthdate
        umur_value = None
        if umur:
            try:
                umur_value = int(umur)
            except Exception:
                umur_value = None
        else:
            try:
                from core.queries import get_employee_by_uid
                emp = get_employee_by_uid(uid)
                birth_raw = emp.get("tanggal_lahir") if isinstance(emp, dict) else getattr(emp, "tanggal_lahir", None)
                birth_dt = pd.to_datetime(birth_raw, errors="coerce") if birth_raw else None
                birth_date = birth_dt.date() if pd.notna(birth_dt) else None
                if birth_date and tanggal_checkup_date:
                    umur_value = tanggal_checkup_date.year - birth_date.year - (
                        (tanggal_checkup_date.month, tanggal_checkup_date.day) < (birth_date.month, birth_date.day)
                    )
            except Exception:
                umur_value = None

        record = {
            "uid": uid,
            "tanggal_checkup": tanggal_checkup_date,
            "tinggi": float(tinggi) if tinggi else None,
            "berat": float(berat) if berat else None,
            "lingkar_perut": float(lingkar_perut) if lingkar_perut else None,
            "bmi": float(bmi) if bmi is not None else None,
            "umur": umur_value,
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

    return redirect(reverse("manager:edit_karyawan", kwargs={"uid": uid}) + "?submenu=data_karyawan&subtab=profile")

@require_http_methods(["GET"]) 
def export_checkup_data_excel(request):
    # Auth guard for Manager
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    try:
        # Load all checkups
        df = load_checkups()

        # If no data, show warning and redirect to Export tab
        if df is None or df.empty:
            request.session["warning_message"] = "belum ada check up data, silahkan unggah terlebih dahulu"
            return redirect(reverse("manager:upload_export") + "?submenu=export_data")

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
from utils.validators import safe_date, validate_lokasi, normalize_string

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
    if not request.session.get("authenticated") or request.session.get("user_role") != "Manager":
        return redirect("accounts:login")

    active_menu = "dashboard"  # Changed to match the mapping in get_active_menu_for_view
    active_submenu = request.GET.get('submenu', 'data')
    
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
    
    # Get all available locations before filtering (exclude empty values)
    all_lokasi = sorted([loc for loc in df['lokasi'].dropna().unique().tolist() if str(loc).strip()])
    
    # Make an unfiltered copy for card totals (keep cards constant when filters change)
    df_all = df.copy()
    
    # Get filter parameters
    filters = {
        'nama': request.GET.get('nama', ''),
        'jabatan': request.GET.get('jabatan', ''),
        'lokasi': request.GET.get('lokasi', ''),  # Single location selection
        'status': request.GET.get('status', ''),  # New status filter
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
    # Date range filter removed: always showing latest checkup data
    
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
    
    # Convert DataFrame to list of dictionaries for template
    employees = df_page.to_dict('records')
    
    # Get dashboard statistics
    users_df = get_users()
    checkups_today = 0  # Will be updated when checkup data is uploaded
    active_nurses = len(users_df[users_df['role'] == 'nurse']) if not users_df.empty else 0
    pending_reviews = 0  # Will be updated when checkup data is uploaded

    # Grafik chart: Well vs Unwell over time (month/week filters)
    grafik_chart_html = None
    grafik_filter_mode = request.GET.get('grafik_mode', 'month')  # 'month' or 'week'
    grafik_month = request.GET.get('grafik_month', '')  # e.g., '2025-10'

    all_checkups_df = load_checkups()
    if not all_checkups_df.empty:
        # Ensure datetime for filtering/aggregation
        all_checkups_df['tanggal_checkup'] = pd.to_datetime(all_checkups_df['tanggal_checkup'], errors='coerce')
        # Derive status if missing
        if 'status' not in all_checkups_df.columns or all_checkups_df['status'].isna().any():
            all_checkups_df['status'] = all_checkups_df.apply(compute_status, axis=1)

        # Apply lokasi/jabatan/status filters for consistency
        graf_df = all_checkups_df.copy()
        if filters.get('lokasi'):
            graf_df = graf_df[graf_df['lokasi'] == filters['lokasi']]
        if filters.get('jabatan'):
            filt_clean = ' '.join(filters['jabatan'].split()).strip().lower()
            graf_df = graf_df[graf_df['jabatan'].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True).str.lower() == filt_clean]
        if filters.get('status'):
            graf_df = graf_df[graf_df['status'] == filters['status']]

        # Filter by month or ISO week if provided
        if grafik_filter_mode == 'month' and grafik_month:
            try:
                month_dt = pd.to_datetime(grafik_month + '-01', errors='coerce')
                if pd.notnull(month_dt):
                    month_start = month_dt
                    next_month = (month_dt + pd.offsets.MonthBegin(1))
                    month_end = next_month - pd.Timedelta(days=1)
                    graf_df = graf_df[(graf_df['tanggal_checkup'] >= month_start) & (graf_df['tanggal_checkup'] <= month_end)]
            except Exception:
                pass
        elif grafik_filter_mode == 'week':
            grafik_week = request.GET.get('grafik_week', '')
            if grafik_week:
                try:
                    year_str, week_str = grafik_week.split('-W')
                    year_i, week_i = int(year_str), int(week_str)
                    week_start = pd.to_datetime(f'{year_i}-W{week_i}-1', format='%G-W%V-%u', errors='coerce')
                    week_end = week_start + pd.Timedelta(days=6)
                    if pd.notnull(week_start):
                        graf_df = graf_df[(graf_df['tanggal_checkup'] >= week_start) & (graf_df['tanggal_checkup'] <= week_end)]
                except Exception:
                    pass

        # Aggregate counts per day
        graf_df['date'] = graf_df['tanggal_checkup'].dt.date
        daily = graf_df.groupby(['date', 'status']).size().reset_index(name='count')
        pivot = daily.pivot_table(index='date', columns='status', values='count', fill_value=0)
        pivot = pivot.rename(columns={'Well': 'well', 'Unwell': 'unwell'}).sort_index()
        # Ensure both expected status columns exist as Series to avoid scalar fallbacks
        pivot = pivot.reindex(columns=['well', 'unwell'], fill_value=0)

        # Build Plotly figure
        if not pivot.empty:
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
        latest_check_date_disp = dt_max.strftime('%Y-%m-%d') if pd.notnull(dt_max) else None
    try:
        hist_df = get_checkup_upload_history()
        if hasattr(hist_df, 'empty') and not hist_df.empty:
            latest = hist_df.iloc[0]
            ts_val = latest.get('timestamp', None)
            ts_disp = ts_val.strftime('%Y-%m-%d %H:%M') if pd.notnull(ts_val) else '-'
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
        'grafik_chart_html': grafik_chart_html,
        'grafik_filter_mode': grafik_filter_mode,
    }
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
        {"key": "edit_karyawan", "name": "Edit Karyawan Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
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
        {"key": "edit_karyawan", "name": "Edit Karyawan Data", "url": reverse("manager:edit_karyawan", kwargs={'uid': default_uid}) if default_uid else '#', "icon": "edit"},
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

            result = checkup_uploader.parse_checkup_xls(save_path)
            # Write log entry for this upload
            write_checkup_upload_log(original_name, result)
            request.session['success_message'] = "Excel berhasil di upload!"
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
        'MEDIA_URL': settings.MEDIA_URL,
    }

    return render(request, "manager/data_management.html", context)



# -------------------------
# Tab 5b: Delete Single Employee
# -------------------------
def delete_karyawan(request, uid):
    """Delete a single employee by UID safely and return to main data page."""
    from core.queries import delete_
