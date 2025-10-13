# qr/qr_views.py
import io
import zipfile
import base64
import os

from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings

from users_ui.qr.qr_utils import generate_qr_bytes
from core.queries import get_employees, load_checkups


def qr_detail_view(request, uid=None):
    """
    Render a single QR code for a user (if UID provided) or show selection page.
    """
    employees_df = get_employees()

    # Validate employees data
    if employees_df is None or employees_df.empty or not all(col in employees_df.columns for col in ['uid', 'nama']):
        return render(request, "qr_templates/qr_detail.html", {"error": "Tidak ada data karyawan untuk membuat QR code."})

    # Unique list of employees
    karyawan_data = employees_df[['uid', 'nama']].drop_duplicates().copy()
    # Ensure UID comparison is done as string to avoid type mismatch
    karyawan_data['uid'] = karyawan_data['uid'].astype(str)

    selected_uid = str(uid) if uid else None
    # Default to first available UID if none provided or not found
    if not selected_uid or selected_uid not in set(karyawan_data['uid'].tolist()):
        selected_uid = karyawan_data.iloc[0]['uid']

    # Get selected employee's name
    selected_rows = karyawan_data[karyawan_data['uid'] == selected_uid]
    if selected_rows.empty:
        # Safety: if still not found, show friendly error
        return render(request, "qr_templates/qr_detail.html", {"error": "UID karyawan tidak ditemukan."})
    selected_name = selected_rows.iloc[0]['nama']

    # Build QR URL for app
    server_url = getattr(settings, "APP_BASE_URL", os.getenv("APP_BASE_URL", "")) or request.build_absolute_uri("/").rstrip("/")
    qr_url = f"{server_url}/karyawan/?uid={selected_uid}"

    qr_bytes = generate_qr_bytes(qr_url)
    qr_base64 = base64.b64encode(qr_bytes).decode("utf-8")

    context = {
        "selected_name": selected_name,
        "selected_uid": selected_uid,
        "qr_base64": qr_base64,
    }
    return render(request, "qr_templates/qr_detail.html", context)


def qr_bulk_download_view(request):
    """
    Generate QR codes for all users and return as ZIP download.
    """
    checkups_df = load_checkups()
    
    # Check if checkups_df is empty or missing required columns
    if checkups_df.empty or not all(col in checkups_df.columns for col in ['uid', 'nama']):
        return HttpResponse("Belum ada data medical untuk karyawan.", status=400)

    karyawan_data = checkups_df[['uid', 'nama']].drop_duplicates()
    if karyawan_data.empty:
        return HttpResponse("Belum ada data medical untuk karyawan.", status=400)

    server_url = getattr(settings, "APP_BASE_URL", os.getenv("APP_BASE_URL", "")) or request.build_absolute_uri("/").rstrip("/")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w") as zf:
        for _, row in karyawan_data.iterrows():
            name = row['nama']
            uid = row['uid']
            qr_url = f"{server_url}/karyawan/?uid={uid}"
            qr_bytes = generate_qr_bytes(qr_url)
            zf.writestr(f"{name}_qrcode.png", qr_bytes)

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer, content_type="application/zip")
    response['Content-Disposition'] = 'attachment; filename="all_karyawan_qrcodes.zip"'
    return response
