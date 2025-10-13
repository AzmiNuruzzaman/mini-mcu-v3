# users_ui/manager/context_processors.py
from django.urls import reverse
from core.queries import get_employees
from django.conf import settings
import os

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
            'name': 'Edit Karyawan Data',
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