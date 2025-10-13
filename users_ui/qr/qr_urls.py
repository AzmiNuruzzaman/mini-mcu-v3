# qr/qr_utils.py
import io
import qrcode
from PIL import Image
import plotly.express as px
import zipfile
from typing import List, Dict

# -------------------------------
# QR Code Generation
# -------------------------------
def generate_qr_bytes(qr_data: str) -> bytes:
    """
    Generate a QR code image in memory and return as bytes (PNG).
    """
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.getvalue()


def generate_qr_pil(qr_data: str) -> Image.Image:
    """
    Generate a QR code as PIL Image object (useful for plotting or further processing)
    """
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


# -------------------------------
# Plotly QR Preview
# -------------------------------
def plot_qr(qr_bytes: bytes, title="QR Code") -> px.imshow:
    """
    Return a Plotly figure to preview QR code.
    """
    import plotly.express as px
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(qr_bytes))
    arr = np.array(img)
    fig = px.imshow(arr)
    fig.update_layout(
        title=title,
        xaxis=dict(showticklabels=False),
        yaxis=dict(showticklabels=False),
    )
    return fig


# -------------------------------
# URL / UID Mapping Utilities
# -------------------------------
def build_display_to_uid(checkups_data: List[Dict]) -> Dict[str, str]:
    """
    Build mapping: "Name (UID: ...)" -> uid
    checkups_data: list of dicts with 'uid' and 'nama'
    """
    return {f"{row['nama']} (UID: {row['uid']})": row['uid'] for row in checkups_data}


def build_qr_url(base_url: str, uid: str) -> str:
    """
    Build the URL to embed in QR code
    """
    return f"{base_url}/karyawan/?uid={uid}"


# -------------------------------
# Bulk QR Generation (ZIP)
# -------------------------------
def generate_qr_zip(checkups_data: List[Dict], base_url: str) -> bytes:
    """
    Generate a ZIP file containing all QR codes (PNG) in memory
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w") as zf:
        for row in checkups_data:
            name = row['nama']
            uid = row['uid']
            qr_url = build_qr_url(base_url, uid)
            qr_bytes = generate_qr_bytes(qr_url)
            zf.writestr(f"{name}_qrcode.png", qr_bytes)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()
