# users_ui/qr/qr_utils.py
import io
import qrcode
from django.http import HttpResponse

def generate_qr_bytes(data: str) -> bytes:
    """
    Generate QR code as bytes for a given data string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
