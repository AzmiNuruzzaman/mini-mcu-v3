# users_ui/nurse/nurse_urls.py
from django.urls import path
from . import nurse_views
from users_ui.manager import manager_views

app_name = "nurse"

urlpatterns = [
    # ---------------- Dashboard ----------------
    path('', nurse_views.nurse_index, name='dashboard'),
    # Grafik Kesehatan uses nurse view that delegates to manager's backend logic; Well/Unwell continues to use manager's dashboard
    path('dashboard/grafik/kesehatan/', nurse_views.nurse_grafik_kesehatan, name='nurse_grafik_kesehatan'),
    path('dashboard/grafik/well_unwell/', nurse_views.nurse_grafik_well_unwell, name='nurse_grafik_well_unwell'),
    path('grafik/well_unwell/summary-json/', nurse_views.well_unwell_summary_json, name='well_unwell_summary_json'),

    # ---------------- Grafik JSON API (duplicate manager endpoints under nurse prefix) ----------------
    path('grafik/well-unwell-summary/', manager_views.well_unwell_summary_json, name='grafik_well_unwell_summary_json'),
    path('grafik/health-metrics-summary/', manager_views.health_metrics_summary_json, name='grafik_health_metrics_summary_json'),
    path('grafik/lokasi-list/', manager_views.lokasi_list_json, name='grafik_lokasi_list_json'),
    path('grafik/karyawan-list/', manager_views.karyawan_list_json, name='grafik_karyawan_list_json'),
    path('grafik/diagnostic-log/', manager_views.grafik_diagnostic_log, name='grafik_diagnostic_log'),

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
