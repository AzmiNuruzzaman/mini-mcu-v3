# users_interface/karyawan_views.py
from django.shortcuts import render
from django.http import HttpResponse
import pandas as pd
from core.queries import load_checkups, get_employee_by_uid
from core.helpers import compute_status
from datetime import datetime


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

    # Build dashboard-like history for template (same structure manager uses)
    history_dashboard = []
    try:
        if df_user is not None and not df_user.empty:
            df_hist = df_user.copy()
            # Ensure tanggal_checkup is datetime
            if 'tanggal_checkup' in df_hist.columns:
                df_hist['tanggal_checkup'] = pd.to_datetime(df_hist['tanggal_checkup'], errors='coerce')
            df_hist = df_hist.sort_values('tanggal_checkup', ascending=False)

            # Employee info fallbacks
            emp_nama = (emp or {}).get('nama')
            emp_jabatan = (emp or {}).get('jabatan')
            emp_lokasi = (emp or {}).get('lokasi')
            emp_tanggal_lahir_fmt = None
            try:
                tl_raw = (emp or {}).get('tanggal_lahir')
                tl_dt = pd.to_datetime(tl_raw, errors='coerce')
                emp_tanggal_lahir_fmt = tl_dt.strftime('%d/%m/%y') if pd.notna(tl_dt) else None
            except Exception:
                emp_tanggal_lahir_fmt = None
            # MCU dates
            emp_tanggal_mcu = None
            emp_expired_mcu = None
            try:
                mcu_raw = (emp or {}).get('tanggal_MCU')
                mcu_dt = pd.to_datetime(mcu_raw, errors='coerce')
                emp_tanggal_mcu = mcu_dt.strftime('%d/%m/%y') if pd.notna(mcu_dt) else None
            except Exception:
                pass
            try:
                exp_raw = (emp or {}).get('expired_MCU')
                exp_dt = pd.to_datetime(exp_raw, errors='coerce')
                emp_expired_mcu = exp_dt.strftime('%d/%m/%y') if pd.notna(exp_dt) else None
            except Exception:
                pass

            for _, row in df_hist.iterrows():
                # Numeric coercion
                tinggi_n = pd.to_numeric(row.get('tinggi', None), errors='coerce')
                berat_n = pd.to_numeric(row.get('berat', None), errors='coerce')
                bmi_n = pd.to_numeric(row.get('bmi', None), errors='coerce')
                lp_n = pd.to_numeric(row.get('lingkar_perut', None), errors='coerce')
                gdp_n = pd.to_numeric(row.get('gula_darah_puasa', None), errors='coerce')
                gds_n = pd.to_numeric(row.get('gula_darah_sewaktu', None), errors='coerce')
                chol_n = pd.to_numeric(row.get('cholesterol', None), errors='coerce')
                asam_n = pd.to_numeric(row.get('asam_urat', None), errors='coerce')
                # Age (no auto-computation): use provided umur as-is
                umur_val = row.get('umur', None)
                # Date formatting
                tc_dt = pd.to_datetime(row.get('tanggal_checkup'), errors='coerce')
                tanggal_str = tc_dt.strftime('%d/%m/%y') if pd.notna(tc_dt) else None
                # Status using helper
                status_val = compute_status({
                    'gula_darah_puasa': gdp_n if pd.notna(gdp_n) else 0,
                    'gula_darah_sewaktu': gds_n if pd.notna(gds_n) else 0,
                    'cholesterol': chol_n if pd.notna(chol_n) else 0,
                    'asam_urat': asam_n if pd.notna(asam_n) else 0,
                    'bmi': bmi_n if pd.notna(bmi_n) else 0,
                })
                # Derajat kesehatan prefer row, fallback to employee
                dk_val = row.get('derajat_kesehatan', None)
                try:
                    if dk_val is None or (isinstance(dk_val, float) and pd.isna(dk_val)) or (isinstance(dk_val, str) and not dk_val.strip()):
                        dk_val = (emp or {}).get('derajat_kesehatan')
                except Exception:
                    pass

                history_dashboard.append({
                    'uid': str(row.get('uid', uid)),
                    'nama': emp_nama,
                    'jabatan': emp_jabatan,
                    'lokasi': emp_lokasi,
                    'tanggal_lahir': emp_tanggal_lahir_fmt,
                    'umur': int(umur_val) if pd.notna(pd.to_numeric(umur_val, errors='coerce')) else None,
                    'tanggal_checkup': tanggal_str,
                    'tinggi': float(tinggi_n) if pd.notna(tinggi_n) else None,
                    'berat': float(berat_n) if pd.notna(berat_n) else None,
                    'bmi': float(bmi_n) if pd.notna(bmi_n) else None,
                    'lingkar_perut': float(lp_n) if pd.notna(lp_n) else None,
                    'gula_darah_puasa': float(gdp_n) if pd.notna(gdp_n) else None,
                    'gula_darah_sewaktu': float(gds_n) if pd.notna(gds_n) else None,
                    'cholesterol': float(chol_n) if pd.notna(chol_n) else None,
                    'asam_urat': float(asam_n) if pd.notna(asam_n) else None,
                    'tekanan_darah': row.get('tekanan_darah', None),
                    'derajat_kesehatan': str(dk_val) if dk_val is not None else None,
                    'tanggal_MCU': emp_tanggal_mcu,
                    'expired_MCU': emp_expired_mcu,
                    'status': status_val,
                })
    except Exception:
        history_dashboard = []

    # Compute MCU expiry estimate (days until/since expiration)
    mcu_expiry_estimate = None
    try:
        exp_raw = (emp or {}).get('expired_MCU')
        exp_dt = pd.to_datetime(exp_raw, errors='coerce')
        if pd.notna(exp_dt):
            delta_days = (exp_dt.date() - datetime.today().date()).days
            if delta_days > 0:
                mcu_expiry_estimate = f"{delta_days} hari lagi"
            elif delta_days == 0:
                mcu_expiry_estimate = "Hari ini"
            else:
                mcu_expiry_estimate = f"Expired {abs(delta_days)} hari lalu"
    except Exception:
        pass

    context = {
        "employee": emp,
        "latest_checkup": latest_checkup,
        "history_checkups": history_checkups,
        "history_dashboard": history_dashboard,
        "active_submenu": request.GET.get("submenu", "data_karyawan"),
        "active_subtab": request.GET.get("subtab", "profile"),
        "view_only": True,
        "mcu_expiry_estimate": mcu_expiry_estimate,
    }

    return render(request, "manager/edit_karyawan.html", context)
