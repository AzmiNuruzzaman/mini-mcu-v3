# users_interface/master/master_views.py
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.conf import settings
import os
from core import queries  # your DB helper module

# -------------------------------------------------------------------
# Hardcoded master credentials (temporary for testing)
# -------------------------------------------------------------------
MASTER_USERNAME = "developer"
MASTER_PASSWORD = "supersecretpassword"

# -------------------------------------------------------------------
# Master login
# -------------------------------------------------------------------
def master_login(request):
    """
    Simple login page for master access.
    """
    if request.session.get("authenticated") and request.session.get("user_role") == "Master":
        return redirect_master_dashboard()

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        if username == MASTER_USERNAME and password == MASTER_PASSWORD:
            # Set session
            request.session["authenticated"] = True
            request.session["user_role"] = "Master"
            request.session["username"] = username
            request.session["success_message"] = "✅ Login berhasil!"
            return redirect_master_dashboard()
        else:
            request.session["error_message"] = "❌ Invalid credentials!"

    return render(request, "master_templates/master_login.html")

# -------------------------
# Master dashboard
# -------------------------
def master_index(request):
    """
    Master dashboard. Accessible only if session 'authenticated' & role=Master.
    """
    if not request.session.get("authenticated") or request.session.get("user_role") != "Master":
        return redirect("master:login")

    # Handle POST actions for user management
    if request.method == "POST":
        action_add = request.POST.get("add_user")
        action_delete = request.POST.get("delete_user")
        action_reset_pw = request.POST.get("reset_user_password")
        action_reset_all_pw = request.POST.get("reset_all_passwords")

        try:
            if action_add is not None:
                username = request.POST.get("username")
                password = request.POST.get("password")
                role = request.POST.get("role")
                # Only allow Manager or Tenaga Kesehatan creation from Master
                role_map = {
                    "Manager": "Manager",
                    "Tenaga Kesehatan": "Tenaga Kesehatan",
                }
                canonical_role = role_map.get(role)
                if not username or not password or not canonical_role:
                    request.session["error_message"] = "Masukkan username, password, dan role yang valid."
                else:
                    queries.add_user(username, password, canonical_role)
                    request.session["success_message"] = f"User {username} berhasil ditambahkan sebagai {canonical_role}."
                return redirect("master:dashboard")

            if action_delete is not None:
                del_username = request.POST.get("del_username")
                user = queries.get_user_by_username(del_username)
                if user:
                    queries.delete_user_by_id(user.id)
                    request.session["success_message"] = f"User {del_username} berhasil dihapus."
                else:
                    request.session["error_message"] = "User tidak ditemukan."
                return redirect("master:dashboard")

            if action_reset_pw is not None:
                reset_username = request.POST.get("reset_username")
                new_password = request.POST.get("new_password")
                if reset_username and new_password:
                    queries.reset_user_password(reset_username, new_password)
                    request.session["success_message"] = f"Password untuk {reset_username} telah direset."
                else:
                    request.session["error_message"] = "Username dan password baru wajib diisi."
                return redirect("master:dashboard")

            if action_reset_all_pw is not None:
                default_pw = request.POST.get("default_pw_all")
                if default_pw:
                    users_df = queries.get_users()
                    for uname in users_df["username"]:
                        queries.reset_user_password(uname, default_pw)
                    request.session["success_message"] = "Semua password berhasil direset."
                else:
                    request.session["error_message"] = "Password default wajib diisi."
                return redirect("master:dashboard")
        except Exception as e:
            request.session["error_message"] = f"Terjadi kesalahan: {e}"
            return redirect("master:dashboard")

    # Fetch user list
    users_df = queries.get_users()

    # Fetch upload history safely
    try:
        batch_history = queries.get_upload_history()
        if batch_history is None:
            batch_history = []
    except AttributeError:
        # settings.UPLOAD_DIR not defined yet
        batch_history = []

    context = {
        "users": users_df.to_dict("records"),
        "history": batch_history if isinstance(batch_history, list) else batch_history.to_dict("records"),
        "manager_count": sum(1 for u in users_df["role"] if u=="Manager"),
        "nurse_count": sum(1 for u in users_df["role"] if u=="Tenaga Kesehatan"),
    }
    return render(request, "master_templates/master_index.html", context)


# -------------------------------------------------------------------
# Master logout
# -------------------------------------------------------------------
def master_logout(request):
    """
    Logout master session.
    """
    request.session.flush()
    request.session["info_message"] = "ℹ️ Logout berhasil."
    return redirect("master:login")


# -------------------------------------------------------------------
# Helper redirect
# -------------------------------------------------------------------
def redirect_master_dashboard():
    return redirect("master:dashboard")
