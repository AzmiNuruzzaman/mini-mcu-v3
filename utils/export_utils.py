# utils/export_utils.py
import io
import pandas as pd
from zipfile import ZipFile
from core.queries import get_employees
from io import BytesIO
from xlsxwriter.utility import xl_col_to_name
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.formatting.rule import Rule

# -----------------------------
# Generate Karyawan Template Excel (V2 behavior)
# -----------------------------
def generate_karyawan_template_excel(lokasi_filter=None):
    """
    Generate Excel template for Checkup Data:
    - Includes master data (uid, nama, jabatan, lokasi, tanggal_lahir)
    - Adds empty medical columns for manual entry
    - Auto-calculates umur, bmi, and BMI_category
    """
    # Fetch master data
    df = get_employees().copy()

    # Optional lokasi filter
    if lokasi_filter:
        if isinstance(lokasi_filter, str):
            lokasi_filter = [lokasi_filter]
        df = df[df['lokasi'].isin(lokasi_filter)]

    # Ensure essential columns exist
    required_cols = ['uid', 'nama', 'jabatan', 'lokasi', 'tanggal_lahir']
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    # Insert tanggal_checkup and umur columns
    if 'tanggal_checkup' not in df.columns:
        df.insert(df.columns.get_loc('lokasi') + 1, 'tanggal_checkup', None)
    if 'umur' not in df.columns:
        df.insert(df.columns.get_loc('tanggal_lahir') + 1, 'umur', None)

    # Add medical columns if missing
    medical_cols = [
        'tinggi', 'berat', 'lingkar_perut', 'gula_darah_puasa',
        'gula_darah_sewaktu', 'cholesterol', 'asam_urat'
    ]
    for col in medical_cols:
        if col not in df.columns:
            df[col] = None

    # Add BMI and category columns
    df['bmi'] = None
    df['BMI_category'] = None
    df['derajat_kesehatan'] = None  # Add derajat kesehatan column

    # Write Excel with formulas
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Template Checkup")
        workbook = writer.book
        worksheet = writer.sheets["Template Checkup"]

        # Map column letters
        col_letters = {col: xl_col_to_name(idx) for idx, col in enumerate(df.columns)}

        # Write formulas for each row
        for row_idx in range(2, len(df) + 2):  # Excel rows start at 1
            # umur = YEARFRAC(tanggal_lahir, TODAY())
            if 'tanggal_lahir' in col_letters and 'umur' in col_letters:
                worksheet.write_formula(
                    row_idx - 1, df.columns.get_loc('umur'),
                    f'=IF(ISNUMBER({col_letters["tanggal_lahir"]}{row_idx}),INT(YEARFRAC({col_letters["tanggal_lahir"]}{row_idx},TODAY(),1)),"")'
                )

            # bmi = berat / (tinggi/100)^2
            if 'berat' in col_letters and 'tinggi' in col_letters and 'bmi' in col_letters:
                worksheet.write_formula(
                    row_idx - 1, df.columns.get_loc('bmi'),
                    f'=IF({col_letters["tinggi"]}{row_idx}>0,{col_letters["berat"]}{row_idx}/(({col_letters["tinggi"]}{row_idx}/100)^2),0)'
                )

            # BMI_category
            if 'bmi' in col_letters and 'BMI_category' in col_letters:
                worksheet.write_formula(
                    row_idx - 1, df.columns.get_loc('BMI_category'),
                    f'=IF({col_letters["bmi"]}{row_idx}<18.5,"Underweight",IF({col_letters["bmi"]}{row_idx}<25,"Ideal",IF({col_letters["bmi"]}{row_idx}<30,"Overweight","Obese")))'
                )

        # Conditional formatting for derajat_kesehatan (font colors)
        if 'derajat_kesehatan' in df.columns:
            col_letter = col_letters['derajat_kesehatan']
            cell_range = f"{col_letter}2:{col_letter}{len(df)+1}"
            fmt_green = workbook.add_format({'font_color': '#00B050'})
            fmt_yellow = workbook.add_format({'font_color': '#FFC000'})
            fmt_orange = workbook.add_format({'font_color': '#ED7D31'})
            fmt_red = workbook.add_format({'font_color': '#FF0000'})

            for val in ["P1", "P2", "P3"]:
                worksheet.conditional_format(cell_range, {
                    'type': 'text', 'criteria': 'containing', 'value': val, 'format': fmt_green
                })
            worksheet.conditional_format(cell_range, {
                'type': 'text', 'criteria': 'containing', 'value': 'P4', 'format': fmt_yellow
            })
            worksheet.conditional_format(cell_range, {
                'type': 'text', 'criteria': 'containing', 'value': 'P5', 'format': fmt_orange
            })
            for val in ["P6", "P7"]:
                worksheet.conditional_format(cell_range, {
                    'type': 'text', 'criteria': 'containing', 'value': val, 'format': fmt_red
                })

    output.seek(0)
    return output


# -----------------------------
# Export Checkup Data to Excel
# -----------------------------
def export_checkup_data_excel(df: pd.DataFrame):
    """
    Accepts a DataFrame of checkup data and returns Excel bytes.
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Checkup Data")
        wb = writer.book
        ws = writer.sheets["Checkup Data"]

        # Apply conditional font coloring to derajat_kesehatan, if present
        if 'derajat_kesehatan' in df.columns and len(df) > 0:
            idx = df.columns.get_loc('derajat_kesehatan') + 1  # 1-indexed
            col = get_column_letter(idx)
            start_row = 2
            end_row = start_row + len(df) - 1
            rng = f"{col}{start_row}:{col}{end_row}"

            def add_text_rule(text, color_hex):
                dxf = DifferentialStyle(font=Font(color=color_hex))
                rule = Rule(type="containsText", operator="containsText", text=text)
                rule.dxf = dxf
                rule.stop = False
                ws.conditional_formatting.add(rng, rule)

            for t in ["P1", "P2", "P3"]:
                add_text_rule(t, "FF00B050")  # Green
            add_text_rule("P4", "FFFFC000")  # Yellow
            add_text_rule("P5", "FFED7D31")  # Orange
            for t in ["P6", "P7"]:
                add_text_rule(t, "FFFF0000")  # Red

    return output.getvalue()


# -----------------------------
# Generate QR ZIP Bytes (for nurse_upload_checkup)
# -----------------------------
def generate_qr_zip_bytes():
    """
    Placeholder: generate a zip containing QR code files.
    """
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, "w") as zf:
        zf.writestr("dummy_qr.txt", "QR generation not implemented yet")
    zip_buffer.seek(0)
    return zip_buffer.getvalue()
