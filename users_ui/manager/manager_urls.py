# users_ui/manager/manager_urls.py
from django.urls import path
from . import manager_views

app_name = "manager"

urlpatterns = [
    # ===============================
    # TAB 1: DASHBOARD
    # ===============================
    path("", manager_views.dashboard, name="dashboard"),  # dashboard.html

    # Avatar Upload
    path("upload-avatar/", manager_views.upload_avatar, name="upload_avatar"),

    # ===============================
    # TAB 2: USER MANAGEMENT
    # ===============================
    path("user-management/", manager_views.add_new_user, name="user_management"),  # user_management.html
    path("add-new-user/", manager_views.add_new_user, name="add_new_user"),
    path("remove-user/<int:user_id>/", manager_views.remove_user, name="remove_user"),
    path("update-role/<int:user_id>/", manager_views.update_user_role, name="update_user_role"),
    path("change-username/<int:user_id>/", manager_views.change_username, name="change_username"),
    path("reset-password/<int:user_id>/", manager_views.reset_user_password, name="reset_user_password"),

    # ===============================
    # TAB 3: QR CODES
    # ===============================
    path("qr/", manager_views.qr_manager_interface, name="qr_codes"),  # qr_codes.html

    # ===============================
    # TAB 4: UPLOAD / EXPORT DATA
    # ===============================
    path("upload-export/", manager_views.upload_master_karyawan_xls, name="upload_export"),  # upload_export.html
    path("download-template/", manager_views.download_karyawan_template, name="download_karyawan_template"),
    path("download-checkup-template/", manager_views.download_checkup_template, name="download_checkup_template"),
    path("upload-master-karyawan/", manager_views.upload_master_karyawan_xls, name="upload_master_karyawan_xls"),
    path("upload-medical-checkup/", manager_views.upload_medical_checkup_xls, name="upload_medical_checkup_xls"),
    path("export-checkup-data/", manager_views.export_checkup_data_excel, name="export_checkup_data"),
    path("export-master-karyawan/", manager_views.export_master_karyawan_excel, name="export_master_karyawan"),
    # NEW: Export history by UID and single checkup
    path("employee/<str:uid>/export-history/", manager_views.export_checkup_history_by_uid, name="export_checkup_history_by_uid"),
    path("employee/<str:uid>/export-history/pdf/", manager_views.export_checkup_history_by_uid_pdf, name="export_checkup_history_by_uid_pdf"),
    path("employee/<str:uid>/checkup/<int:checkup_id>/export/", manager_views.export_checkup_row, name="export_checkup_row"),
    path("employee/<str:uid>/checkup/<int:checkup_id>/export/pdf/", manager_views.export_checkup_row_pdf, name="export_checkup_row_pdf"),

    # ===============================
    # UPLOAD LOG MANAGEMENT
    # ===============================
    path("delete-upload-log/", manager_views.delete_upload_log, name="delete_upload_log"),
    path("delete-upload-logs-bulk/", manager_views.delete_upload_logs_bulk, name="delete_upload_logs_bulk"),
    path("purge-upload-logs/", manager_views.purge_upload_logs, name="purge_upload_logs"),

    # ===============================
    # TAB 5: HAPUS DATA KARYAWAN (was Data Management)
    # ===============================
    path("manage-uid/", manager_views.manage_karyawan_uid, name="hapus_data_karyawan"),
    path("reset-all-checkups/", manager_views.reset_all_checkups, name="reset_all_checkups"),
    path("reset-all-karyawan/", manager_views.reset_all_karyawan, name="reset_all_karyawan"),
    path("manage-lokasi/", manager_views.manage_lokasi, name="manage_lokasi"),
    path("lokasi/add/", manager_views.add_lokasi, name="add_lokasi"),
    path("delete-karyawan/<str:uid>/", manager_views.delete_karyawan, name="delete_karyawan"),


    # ===============================
    # TAB 6: EMPLOYEE PROFILE / EDIT
    # ===============================
    path("employee/<str:uid>/", manager_views.employee_profile, name="edit_karyawan"),  # edit_karyawan.html
    path("employee/<str:uid>/save-checkup/", manager_views.save_medical_checkup, name="save_medical_checkup"),
    # NEW: Add Karyawan (used by Data Karyawan > Tambah karyawan form)
    path("employee/add/", manager_views.add_karyawan, name="add_karyawan"),
]
