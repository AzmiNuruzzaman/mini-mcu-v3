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
from core.helpers import compute_bmi_category

# -----------------------------
# Generate Karyawan Template Excel (V2 behavior)
# -----------------------------
def generate_karyawan_template_excel(lokasi_filter=None):
    """
    Generate Excel template for Checkup Data:
    - Includes master data (uid, nama, jabatan, lokasi, tanggal_lahir)
    - Adds empty medical columns for manual entry
    - Preserves existing master data values (umur, derajat_kesehatan, bmi, bmi_category)
    - Auto-calculates umur, bmi, and bmi_category ONLY for rows that are missing values
    - Normalizes column name to 'bmi_category' (removes duplicate 'BMI_category')
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
        'gula_darah_sewaktu', 'cholesterol', 'tekanan_darah', 'asam_urat'
    ]
    for col in medical_cols:
        if col not in df.columns:
            df[col] = None

    # Ensure BMI and category columns exist (normalize to 'bmi_category')
    if 'BMI_category' in df.columns and 'bmi_category' not in df.columns:
        df = df.rename(columns={'BMI_category': 'bmi_category'})
    elif 'BMI_category' in df.columns and 'bmi_category' in df.columns:
        # Drop legacy duplicate if both present
        df = df.drop(columns=['BMI_category'])
    if 'bmi' not in df.columns:
        df['bmi'] = None
    if 'bmi_category' not in df.columns:
        df['bmi_category'] = None

    # Ensure derajat_kesehatan column exists (do NOT overwrite existing values)
    if 'derajat_kesehatan' not in df.columns:
        df['derajat_kesehatan'] = None

    # No pre-fill: umur must be provided manually or come from DB/XLS; do not compute
    # Leaving df['umur'] as-is without deriving from tanggal_lahir.

    # Write Excel with formulas (for remaining blanks only)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Template Checkup")
        workbook = writer.book
        worksheet = writer.sheets["Template Checkup"]

        # Map column letters
        col_letters = {col: xl_col_to_name(idx) for idx, col in enumerate(df.columns)}

        # Helper to check if a DF cell is missing
        def _is_missing(val):
            return (val is None) or (isinstance(val, float) and pd.isna(val)) or (isinstance(val, str) and val.strip() == '')

        # Do not write any Excel formulas for umur, bmi, or bmi_category to avoid auto-calculation.
        # Cells will remain blank if values are missing, and should be filled manually as needed.

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
def export_checkup_data_excel(df: pd.DataFrame, enrich: bool = True, columns: list | None = None):
    """
    Returns Excel bytes from the provided DataFrame.
    If enrich=False, exports the DataFrame as-is (optionally restricted to 'columns') with no merging or extra computation.
    If enrich=True (default), enriches with master data (nama, jabatan, lokasi, tanggal_lahir, umur, bmi, bmi_category, derajat_kesehatan, tanggal_MCU, expired_MCU) when missing.
    """
    df = df.copy()

    # Normalize UID column if needed
    if 'uid_id' in df.columns and 'uid' not in df.columns:
        df = df.rename(columns={'uid_id': 'uid'})

    if enrich:
        # Merge with master employee data to fill missing columns
        emp_df = get_employees()
        if emp_df is not None and not emp_df.empty and 'uid' in df.columns:
            master_cols = ['uid', 'nama', 'jabatan', 'lokasi', 'tanggal_lahir', 'umur', 'bmi', 'bmi_category', 'derajat_kesehatan', 'tanggal_MCU', 'expired_MCU']
            for col in master_cols:
                if col not in emp_df.columns:
                    emp_df[col] = None
            merged = df.merge(emp_df[master_cols], on='uid', how='left', suffixes=('', '_master'))
            for col in master_cols:
                if col == 'uid':
                    continue
                col_master = f"{col}_master"
                if col in merged.columns and col_master in merged.columns:
                    merged[col] = merged[col].where(~merged[col].isna(), merged[col_master])
                    merged = merged.drop(columns=[col_master])
                elif col_master in merged.columns and col not in merged.columns:
                    merged[col] = merged[col_master]
                    merged = merged.drop(columns=[col_master])
            df = merged

        # Ensure BMI category is present; compute if missing
        if 'bmi_category' not in df.columns:
            df['bmi_category'] = None
        df['bmi_category'] = df.apply(lambda r: r['bmi_category'] if pd.notna(r.get('bmi_category')) else compute_bmi_category(r.get('bmi')), axis=1)

    # Restrict to specified columns (preserve order) if provided
    if columns:
        cols = [c for c in columns if c in df.columns]
        if cols:
            df = df[cols]

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
# Export Checkup Data to PDF
# -----------------------------
def export_checkup_data_pdf(
    df: pd.DataFrame,
    enrich: bool = True,
    columns: list | None = None,
    orientation: str = 'portrait',
    max_cols_per_table: int = 8,
    title_text: str | None = None,
    logo_path: str | None = None,
    list_style: bool = False,
) -> bytes:
    """
    Returns PDF bytes from the provided DataFrame.
    - If enrich=False, exports the DataFrame as-is (optionally restricted to 'columns') with no merging or extra computation.
    - If enrich=True, enriches with master data similar to Excel export.
    - orientation: 'portrait' (default) or 'landscape'.
    - max_cols_per_table: number of columns per table chunk (tables are stacked vertically to render downward).
    - title_text: optional title at the top.
    - logo_path: optional path to logo image placed top-right.
    - list_style: if True, render each row as a list of field: value items (more professional layout).
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT

    # Normalize and optionally enrich with master data
    df = df.copy()
    if 'uid_id' in df.columns and 'uid' not in df.columns:
        df = df.rename(columns={'uid_id': 'uid'})
    if enrich:
        emp_df = get_employees()
        if emp_df is not None and not emp_df.empty and 'uid' in df.columns:
            master_cols = ['uid', 'nama', 'jabatan', 'lokasi', 'tanggal_lahir', 'umur', 'bmi', 'bmi_category', 'derajat_kesehatan', 'tanggal_MCU', 'expired_MCU']
            for col in master_cols:
                if col not in emp_df.columns:
                    emp_df[col] = None
            merged = df.merge(emp_df[master_cols], on='uid', how='left', suffixes=('', '_master'))
            for col in master_cols:
                if col == 'uid':
                    continue
                col_master = f"{col}_master"
                if col in merged.columns and col_master in merged.columns:
                    merged[col] = merged[col].where(~merged[col].isna(), merged[col_master])
                    merged = merged.drop(columns=[col_master])
                elif col_master in merged.columns and col not in merged.columns:
                    merged[col] = merged[col_master]
                    merged = merged.drop(columns=[col_master])
            df = merged
        if 'bmi_category' not in df.columns:
            df['bmi_category'] = None
        df['bmi_category'] = df.apply(lambda r: r['bmi_category'] if pd.notna(r.get('bmi_category')) else compute_bmi_category(r.get('bmi')), axis=1)

    # Restrict to specified columns (preserve order) if provided
    if columns:
        cols = [c for c in columns if c in df.columns]
        if cols:
            df = df[cols]

    # Prepare data rows (stringify, handle None/NaN)
    def fmt(v):
        try:
            if pd.isna(v):
                return '-'
        except Exception:
            pass
        if v is None:
            return '-'
        return str(v)

    # Determine page orientation
    pagesize = A4 if orientation == 'portrait' else landscape(A4)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)

    elements = []
    styles = getSampleStyleSheet()

    # Header: Title and optional logo
    header_flowables = []
    title_style = ParagraphStyle('TitleLeft', parent=styles['Title'], alignment=TA_LEFT)
    title_para = Paragraph(title_text or "", title_style) if title_text else None
    img_flow = None
    try:
        if logo_path is None:
            import os
            from django.conf import settings
            default_logo = os.path.join(settings.BASE_DIR, 'static', 'images', 'logo.png')
            if os.path.exists(default_logo):
                logo_path = default_logo
        if logo_path:
            img_flow = Image(logo_path)
            img_flow._restrictSize(80, 80)  # Max size
    except Exception:
        img_flow = None
    if title_para or img_flow:
        # Use a 2-column header table: title left, logo right
        hdr_data = [[title_para if title_para else "", img_flow if img_flow else ""]]
        hdr_tbl = Table(hdr_data, colWidths=[None, 100])
        hdr_tbl.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN', (0,0), (0,0), 'LEFT'),
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            # no borders
        ]))
        elements.append(hdr_tbl)
        elements.append(Spacer(1, 12))

    # Content: list-style or tabular
    if list_style:
        # Render each row as a list of field: value items
        cols_to_show = list(df.columns)
        for idx, (_, row) in enumerate(df.iterrows(), start=1):
            # Row header
            elements.append(Paragraph("Data Rekam", styles['Heading4']))
            # Two-column table for field/value pairs for cleaner alignment
            data = []
            for c in cols_to_show:
                label = c.replace('_', ' ').title()
                value = fmt(row[c])
                data.append([Paragraph(f"<b>{label}</b>", styles['Normal']), Paragraph(value, styles['Normal'])])
            tbl = Table(data, colWidths=[120, None])
            tbl.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('FONTSIZE', (0,0), (-1,-1), 9),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            elements.append(tbl)
            elements.append(Spacer(1, 10))
    else:
        # Chunk columns into multiple tables to render downward if too many columns
        all_cols = list(df.columns)
        chunks = [all_cols[i:i+max_cols_per_table] for i in range(0, len(all_cols), max_cols_per_table)]
        for idx, cols in enumerate(chunks, start=1):
            # Title for each chunk
            elements.append(Paragraph(f"Data Bagian {idx}", styles['Heading4']))
            data = [[c.replace('_', ' ').title() for c in cols]]
            for _, row in df[cols].iterrows():
                data.append([fmt(row[c]) for c in cols])
            table = Table(data, repeatRows=1)
            style = TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#f0f0f0')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.HexColor('#333333')),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('FONTSIZE', (0,0), (-1,0), 10),
                ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                ('GRID', (0,0), (-1,-1), 0.25, colors.HexColor('#cccccc')),
                ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fbfbfb')]),
                ('FONTSIZE', (0,1), (-1,-1), 9),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ])
            table.setStyle(style)
            elements.append(table)
            elements.append(Spacer(1, 8))

    doc.build(elements)
    buf.seek(0)
    return buf.getvalue()


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
