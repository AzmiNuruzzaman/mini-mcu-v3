# users_ui/nurse/nurse_urls.py
from django.urls import path
from . import nurse_views

app_name = "nurse"

urlpatterns = [
    # ---------------- Dashboard ----------------
    path('', nurse_views.nurse_index, name='dashboard'),

    # ---------------- Karyawan Detail / Edit ----------------
    path('karyawan/<str:uid>/', nurse_views.nurse_karyawan_detail, name='karyawan_detail'),
    path('karyawan/<str:uid>/save/', nurse_views.nurse_save_medical_checkup, name='save_checkup'),

    # ---------------- Upload ----------------
    path('upload/', nurse_views.nurse_upload_checkup, name='upload_checkup'),
    path('upload-export/', nurse_views.nurse_upload_export, name='upload_export'),
    path('download-checkup-template/', nurse_views.nurse_download_checkup_template, name='download_checkup_template'),
    path('export-karyawan-data/', nurse_views.nurse_export_karyawan_data, name='export_karyawan_data'),

    # ---------------- QR Codes ----------------
    path('qr/', nurse_views.nurse_qr_interface, name='qr_codes'),
    path('qr/<str:uid>/', nurse_views.nurse_qr_interface, name='qr_detail'),
    path('qr/bulk/', lambda request: nurse_views.nurse_qr_interface(request, bulk=True), name='qr_bulk_download'),

    # ---------------- Avatar Upload ----------------
    path('upload-avatar/', nurse_views.upload_avatar, name='upload_avatar'),
]
