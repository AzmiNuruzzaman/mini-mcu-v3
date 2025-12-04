import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or os.getenv("SECRET_KEY")
DEBUG = os.getenv("DJANGO_DEBUG", os.getenv("DEBUG", "True")).lower() == "true"
APP_BASE_URL = os.getenv("APP_BASE_URL")
SERVE_MEDIA = os.getenv("DJANGO_SERVE_MEDIA", "False").lower() == "true"

ALLOWED_HOSTS = os.getenv(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1"
).split(",")
CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost,http://127.0.0.1"
).split(",")
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# -----------------------------
# Installed Apps
# -----------------------------
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # our apps
    "core",
    "accounts",
    "users_ui.qr",
    "users_ui",                  # main umbrella app
    "users_ui.karyawan",         # sub-apps registered properly
    "users_ui.nurse",
    "users_ui.manager",
    "users_ui.master",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # 👈 add this
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",     # 👈 and this
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mini_mcu.main_urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "mini_mcu" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "users_ui.manager.context_processors.manager_menu",
                "users_ui.manager.context_processors.manager_notifications",
                "users_ui.nurse.context_processors.nurse_menu",
                "users_ui.nurse.context_processors.nurse_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "mini_mcu.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB"),
        "USER": os.environ.get("POSTGRES_USER"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        "HOST": "db",
        "PORT": 5432,
    }
}


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

# -----------------------------
# Static & Media
# -----------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [
    BASE_DIR / "static",   # where your static/images/logo.png lives
]

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
os.makedirs(STATIC_ROOT, exist_ok=True)

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.getenv("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

# Add upload directories for saving uploaded files and logs
UPLOAD_DIR = MEDIA_ROOT / "uploads"
UPLOAD_CHECKUPS_DIR = UPLOAD_DIR / "checkups"
UPLOAD_LOG_DIR = UPLOAD_DIR / "logs"
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_CHECKUPS_DIR, exist_ok=True)
os.makedirs(UPLOAD_LOG_DIR, exist_ok=True)
# -----------------------------
# Default primary key
# -----------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -----------------------------
# Authentication Redirects
# -----------------------------
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/manager/"   # or "/nurse/" depending on role
LOGOUT_REDIRECT_URL = "/"

# Production security hardening (only when not DEBUG)
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SECURE_HSTS_PRELOAD = os.getenv("DJANGO_HSTS_PRELOAD", "False").lower() == "true"
