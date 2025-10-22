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
    # Export history for a specific UID (XLS/PDF)
    path('export-checkup-history-xls/<str:uid>/', nurse_views.nurse_export_checkup_history_by_uid, name='export_checkup_history_by_uid'),
    path('export-checkup-history-pdf/<str:uid>/', nurse_views.nurse_export_checkup_history_by_uid_pdf, name='export_checkup_history_by_uid_pdf'),
    # Export a single checkup row (XLS/PDF)
    path('export-checkup-row-xls/<str:uid>/<int:checkup_id>/', nurse_views.nurse_export_checkup_row, name='export_checkup_row'),
    path('export-checkup-row-pdf/<str:uid>/<int:checkup_id>/', nurse_views.nurse_export_checkup_row_pdf, name='export_checkup_row_pdf'),

    # ---------------- Upload ----------------
    path('upload/', nurse_views.nurse_upload_checkup, name='upload_checkup'),
    path('upload-export/', nurse_views.nurse_upload_export, name='upload_export'),
    path('download-checkup-template/', nurse_views.nurse_download_checkup_template, name='download_checkup_template'),
    path('export-checkup-data/', nurse_views.nurse_export_checkup_data, name='export_checkup_data'),
    path('export-checkup-pdf/', nurse_views.nurse_export_checkup_data_pdf, name='export_checkup_pdf'),
    path('delete-checkup/<int:checkup_id>/', nurse_views.nurse_delete_checkup, name='delete_checkup'),
    path('edit-checkup/<int:checkup_id>/', nurse_views.nurse_edit_checkup, name='edit_checkup'),
    path('export-karyawan-data/', nurse_views.nurse_export_karyawan_data, name='export_karyawan_data'),

    # ---------------- QR Codes ----------------
    path('qr/', nurse_views.nurse_qr_interface, name='qr_codes'),
    path('qr/<str:uid>/', nurse_views.nurse_qr_interface, name='qr_detail'),
    path('qr/bulk/', lambda request: nurse_views.nurse_qr_interface(request, bulk=True), name='qr_bulk_download'),

    # ---------------- Avatar Upload ----------------
    path('upload-avatar/', nurse_views.upload_avatar, name='upload_avatar'),
]
