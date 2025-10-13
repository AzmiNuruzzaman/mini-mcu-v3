# users_interface/karyawan_urls.py
from django.urls import path
from . import karyawan_views

app_name = "karyawan"

urlpatterns = [
    path('', karyawan_views.karyawan_landing, name='landing'),
]
