# mini_mcu/main_urls.py
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

# --- Root redirect view ---
def root_redirect(request):
    return redirect("/accounts/login/")  # ✅ Always open login first

# --- URL patterns ---
urlpatterns = [
    # Root path → login
    path("", root_redirect, name="root_redirect"),

    # Core sections
    path("manager/", include("users_ui.manager.manager_urls")),
    path("nurse/", include("users_ui.nurse.nurse_urls")),
    path("karyawan/", include("users_ui.karyawan.karyawan_urls")),
    path("app_karyawan", include(("users_ui.karyawan.karyawan_urls", "karyawan"), namespace="karyawan_alias")),
    path("master/", include("users_ui.master.master_urls")),

    # Authentication routes
    path("accounts/", include("accounts.auth_urls")),  # ✅ Login/logout URLs live here
]

# Serve media files in development or when explicitly enabled for Railway Volume
if settings.DEBUG or getattr(settings, "SERVE_MEDIA", False):
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
