# users_interface/karyawan_views.py
from django.shortcuts import render
from django.http import HttpResponse
import pandas as pd
from core.queries import load_checkups, get_employee_by_uid

def karyawan_landing(request):
    uid = request.GET.get("uid")
    if not uid:
        return HttpResponse("❌ UID tidak ditemukan di URL. Silakan scan QR code yang benar.", status=400)

    # Fetch employee
    try:
        emp_raw = get_employee_by_uid(uid)
        if not emp_raw:
            return HttpResponse("❌ Data karyawan tidak ditemukan.", status=404)
        emp = emp_raw.to_dict() if hasattr(emp_raw, "to_dict") else emp_raw
    except Exception as e:
        return HttpResponse(f"❌ Gagal mengambil data karyawan: {e}", status=500)

    # Fetch checkups
    try:
        df_checkups = load_checkups()
        if df_checkups.empty:
            df_user = pd.DataFrame()
        else:
            df_user = df_checkups[df_checkups["uid"].astype(str) == str(uid)]
            if not df_user.empty:
                df_user["tanggal_checkup"] = pd.to_datetime(df_user["tanggal_checkup"], errors="coerce")
    except Exception as e:
        return HttpResponse(f"❌ Gagal mengambil data checkup: {e}", status=500)

    # Build latest and history in the same shape manager uses
    latest_checkup = None
    history_checkups = []
    try:
        if df_user is not None and not df_user.empty:
            df_sorted = df_user.sort_values("tanggal_checkup", ascending=False)
            latest_row = df_sorted.iloc[0]
            # Compute flags and status
            bmi_n = pd.to_numeric(latest_row.get('bmi', None), errors='coerce')
            gdp_n = pd.to_numeric(latest_row.get('gula_darah_puasa', None), errors='coerce')
            gds_n = pd.to_numeric(latest_row.get('gula_darah_sewaktu', None), errors='coerce')
            chol_n = pd.to_numeric(latest_row.get('cholesterol', None), errors='coerce')
            asam_n = pd.to_numeric(latest_row.get('asam_urat', None), errors='coerce')
            flags = {
                'bmi_high': (pd.notna(bmi_n) and bmi_n >= 30),
                'gdp_high': (pd.notna(gdp_n) and gdp_n > 120),
                'gds_high': (pd.notna(gds_n) and gds_n > 200),
                'chol_high': (pd.notna(chol_n) and chol_n > 240),
                'asam_high': (pd.notna(asam_n) and asam_n > 7),
            }
            # Format date
            dt = pd.to_datetime(latest_row.get("tanggal_checkup"), errors="coerce")
            tanggal_str = dt.strftime("%d/%m/%y") if pd.notna(dt) else ""
            latest_checkup = {
                'tanggal_checkup': tanggal_str,
                'bmi': float(bmi_n) if pd.notna(bmi_n) else None,
                'berat': latest_row.get('berat', None),
                'tinggi': latest_row.get('tinggi', None),
                'lingkar_perut': latest_row.get('lingkar_perut', None),
                'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                'status': (
                    'Unwell' if (
                        (pd.notna(bmi_n) and bmi_n >= 30) or
                        (pd.notna(gdp_n) and gdp_n > 120) or
                        (pd.notna(gds_n) and gds_n > 200) or
                        (pd.notna(chol_n) and chol_n > 240) or
                        (pd.notna(asam_n) and asam_n > 7)
                    ) else 'Well'
                ),
                'flags': flags,
            }
            # History
            for _, row in df_sorted.iterrows():
                bmi_h = pd.to_numeric(row.get('bmi', None), errors='coerce')
                gdp_h = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_h = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_h = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_h = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
                flags_h = {
                    'bmi_high': (pd.notna(bmi_h) and bmi_h >= 30),
                    'gdp_high': (pd.notna(gdp_h) and gdp_h > 120),
                    'gds_high': (pd.notna(gds_h) and gds_h > 200),
                    'chol_high': (pd.notna(chol_h) and chol_h > 240),
                    'asam_high': (pd.notna(asam_h) and asam_h > 7),
                }
                dt_h = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                tanggal_h = dt_h.strftime('%d/%m/%y') if pd.notna(dt_h) else ''
                history_checkups.append({
                    'tanggal_checkup': tanggal_h,
                    'bmi': float(bmi_h) if pd.notna(bmi_h) else None,
                    'berat': row.get('berat', None),
                    'tinggi': row.get('tinggi', None),
                    'lingkar_perut': row.get('lingkar_perut', None),
                    'gula_darah_puasa': float(gdp_h) if pd.notna(gdp_h) else None,
                    'gula_darah_sewaktu': float(gds_h) if pd.notna(gds_h) else None,
                    'cholesterol': float(chol_h) if pd.notna(chol_h) else None,
                    'asam_urat': float(asam_h) if pd.notna(asam_h) else None,
                    'status': (
                        'Unwell' if (
                            (pd.notna(bmi_h) and bmi_h >= 30) or
                            (pd.notna(gdp_h) and gdp_h > 120) or
                            (pd.notna(gds_h) and gds_h > 200) or
                            (pd.notna(chol_h) and chol_h > 240) or
                            (pd.notna(asam_h) and asam_h > 7)
                        ) else 'Well'
                    ),
                    'flags': flags_h,
                })
    except Exception:
        latest_checkup = None
        history_checkups = []

    context = {
        "employee": emp,
        "latest_checkup": latest_checkup,
        "history_checkups": history_checkups,
        "active_submenu": request.GET.get("submenu", "data_karyawan"),
        "active_subtab": request.GET.get("subtab", "profile"),
        "view_only": True,
    }

    return render(request, "manager/edit_karyawan.html", context)
