# users_interface/karyawan_urls.py
from django.urls import path
from . import karyawan_views

app_name = "karyawan"

urlpatterns = [
    path('', karyawan_views.karyawan_landing, name='landing'),
    # Minimal read-only grafik endpoints for karyawan QR view
    path('grafik/karyawan-list/', karyawan_views.karyawan_list_json, name='grafik_karyawan_list_json'),
    path('grafik/health-metrics-summary/', karyawan_views.health_metrics_summary_json, name='grafik_health_metrics_summary_json'),
]
