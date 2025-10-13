# mini_mcu/wsgi.py
import os
from django.core.wsgi import get_wsgi_application

# Set default settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mini_mcu.settings')

# Get WSGI application
application = get_wsgi_application()
