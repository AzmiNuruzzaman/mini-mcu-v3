# accounts/views.py
from django.shortcuts import render, redirect
from django.urls import reverse
from core.queries import get_user_by_username
import bcrypt

from .forms import LoginForm

# -------------------------------------------------------------------
# Role access check (replaces missing auth.roles)
# -------------------------------------------------------------------
def has_login_access(role: str) -> bool:
    """
    Check if a given role is allowed to login manually.
    Example logic:
        - Master, Manager, Tenaga Kesehatan → allowed
        - Karyawan → not allowed via manual login
    """
    allowed_roles = ["Master", "Manager", "Tenaga Kesehatan"]
    return role in allowed_roles

# -------------------------------------------------------------------
# Login view
# -------------------------------------------------------------------
def login_view(request):
    """
    Handle user login.
    Always start with a clean session when accessing /login/.
    """
    # 🔹 Always clear old session each time login page is accessed
    request.session.flush()

    form = LoginForm(request.POST or None)  # ✅ Always define form

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]

        # Get user from Supabase via core.queries
        user = get_user_by_username(username)

        if user and bcrypt.checkpw(password.encode(), user.password.encode()):
            if not has_login_access(user.role):
                request.session["error"] = "❌ Anda tidak memiliki akses login saat ini."
                return render(request, "accounts/login.html", {"form": form})

            # Set session data
            request.session["user_role"] = user.role
            request.session["authenticated"] = True
            request.session["username"] = user.username
            request.session["success"] = f"✅ Login berhasil! Selamat datang, {user.username}."

            return redirect_role(user.role)
        else:
            request.session["error"] = "❌ Username atau password salah!"

    return render(request, "accounts/login.html", {"form": form})




# -------------------------------------------------------------------
# Logout view
# -------------------------------------------------------------------
def logout_view(request):
    """Logout the current user and clear session."""
    if not request.session.get("authenticated"):
        return redirect("/")
        
    request.session.flush()  # Clear all session data
    request.session["info"] = "ℹ️ Logout berhasil. Sampai jumpa!"
    return redirect("/")

# -------------------------------------------------------------------
# Helper to redirect by role
# -------------------------------------------------------------------
def redirect_role(role):
    if role == "Master":
        return redirect("/master/")
    elif role == "Manager":
        return redirect("/manager/")
    elif role == "Tenaga Kesehatan":
        return redirect("/nurse/")
    elif role == "Karyawan":
        return redirect("/karyawan/")
    else:
        # Unknown role - redirect to root which handles login
        return redirect("/")
