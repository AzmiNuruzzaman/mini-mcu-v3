# users_interface/master/master_urls.py
from django.urls import path
from . import master_views

app_name = "master"

urlpatterns = [
    # Master login page
    path("login/", master_views.master_login, name="login"),

    # Master dashboard
    path("", master_views.master_index, name="dashboard"),

    # Master logout
    path("logout/", master_views.master_logout, name="logout"),
]
