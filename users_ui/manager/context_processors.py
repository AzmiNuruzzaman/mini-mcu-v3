# users_ui/manager/context_processors.py
from django.urls import reverse
from core.queries import get_employees
from django.conf import settings
import os
import pandas as pd
from core.helpers import get_mcu_expiry_alerts

def manager_menu(request):
    """Context processor to provide manager menu items to all manager views."""
    if not request.path.startswith('/manager/'):
        return {}

    employees_df = get_employees()
    default_uid = str(employees_df.iloc[0]['uid']) if not employees_df.empty else None

    menu_items = [
        {
            'name': 'Dashboard',
            'url': reverse('manager:dashboard'),
            'icon': 'home',
            'key': 'dashboard'
        },
        {
            'name': 'User Management',
            'url': reverse('manager:user_management'),
            'icon': 'users',
            'key': 'user'
        },
        {
            'name': 'QR Codes',
            'url': reverse('manager:qr_codes'),
            'icon': 'qrcode',
            'key': 'qr'
        },
        {
            'name': 'Upload / Export Data',
            'url': reverse('manager:upload_export'),
            'icon': 'upload',
            'key': 'data'
        },
        {
            'name': 'Hapus Data Karyawan',
            'url': reverse('manager:hapus_data_karyawan'),
            'icon': 'database',
            'key': 'hapus_data_karyawan'
        },
        {
            'name': 'Edit Master Data',
            'url': reverse('manager:edit_karyawan', kwargs={'uid': default_uid}) if default_uid else '#',
            'icon': 'edit',
            'key': 'edit_karyawan'
        }
    ]

    current_path = request.path.rstrip('/')
    active_key = 'dashboard'

    path_prefixes = [
        ('/manager/user-management', 'user'),
        ('/manager/qr', 'qr'),
        ('/manager/upload-export', 'data'),
        ('/manager/manage-uid', 'hapus_data_karyawan'),
        ('/manager/employee', 'edit_karyawan'),
        ('/manager', 'dashboard'),
    ]

    for path, key in path_prefixes:
        if current_path.startswith(path):
            active_key = key
            break

    active_label = next((item['name'] for item in menu_items if item['key'] == active_key), 'Dashboard')

    username = request.session.get('username') or getattr(getattr(request, 'user', None), 'username', None)
    avatar_url = None
    if username:
        avatar_dir = os.path.join(settings.MEDIA_ROOT, 'avatars', 'manager')
        if os.path.isdir(avatar_dir):
            for ext in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
                candidate = os.path.join(avatar_dir, f"{username}.{ext}")
                if os.path.exists(candidate):
                    avatar_url = f"{settings.MEDIA_URL}avatars/manager/{username}.{ext}"
                    break
    role_title = 'Manager'
    try:
        avatar_upload_url = reverse('manager:upload_avatar')
    except Exception:
        avatar_upload_url = None

    return {
        'menu_items': menu_items,
        'active_menu': active_key,
        'active_menu_label': active_label,
        'avatar_url': avatar_url,
        'avatar_upload_url': avatar_upload_url,
        'role_title': role_title,
        'greet_username': True,
    }


def manager_notifications(request):
    """Provide MCU expiry alerts and items to manager views (60-day window)."""
    # Only apply on manager pages
    try:
        path = getattr(request, 'path', '')
        if not str(path).startswith('/manager/'):
            return {}
    except Exception:
        return {}

    # Aggregate counts (expired, due soon)
    try:
        alerts = get_mcu_expiry_alerts(window_days=60)
    except Exception:
        alerts = {"expired": 0, "due_soon": 0, "total": 0}

    items = []
    try:
        df = get_employees()
        if df is not None and not df.empty and 'expired_MCU' in df.columns:
            exp_series = pd.to_datetime(df['expired_MCU'], errors='coerce')
            today = pd.Timestamp.today().normalize()
            window_end = today + pd.Timedelta(days=60)

            expired_rows = df[exp_series.notna() & (exp_series < today)].copy()
            due_rows = df[exp_series.notna() & (exp_series >= today) & (exp_series <= window_end)].copy()

            if not expired_rows.empty:
                expired_rows = expired_rows.sort_values(by='expired_MCU')
                for _, r in expired_rows.iterrows():
                    items.append({
                        "type": "expired",
                        "title": f"{r.get('nama')} ({r.get('jabatan')})",
                        "expired_at": r.get('expired_MCU') or "-",
                        "days_left": None,
                        "uid": str(r.get('uid')) if r.get('uid') else None,
                        "url": reverse('manager:edit_karyawan', kwargs={'uid': str(r.get('uid'))}) if r.get('uid') else None,
                    })
            if not due_rows.empty:
                due_rows = due_rows.sort_values(by='expired_MCU')
                for _, r in due_rows.iterrows():
                    exp_dt = pd.to_datetime(r.get('expired_MCU'), errors='coerce')
                    days_left = int((exp_dt.date() - today.date()).days) if pd.notna(exp_dt) else None
                    items.append({
                        "type": "due_soon",
                        "title": f"{r.get('nama')} ({r.get('jabatan')})",
                        "expired_at": r.get('expired_MCU') or "-",
                        "days_left": days_left,
                        "uid": str(r.get('uid')) if r.get('uid') else None,
                        "url": reverse('manager:edit_karyawan', kwargs={'uid': str(r.get('uid'))}) if r.get('uid') else None,
                    })

            # Limit to a reasonable number in the panel
            if len(items) > 12:
                items = items[:12]
    except Exception:
        # Leave items empty if any error occurs
        pass

    return {
        "mcu_alerts": alerts,
        "mcu_alert_items": items,
        "mcu_alert_window_days": 60,
    }