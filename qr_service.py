import io
import socket
import base64
import urllib.parse
import qrcode
from PIL import Image

def get_local_ip() -> str:
    """Return the primary local network IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # Using a public DNS server address just to route local interface
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

def build_shelf_url(base_url: str, day: str, slot: int = None) -> str:
    """Construct URL for scanning."""
    base = base_url.rstrip("/")
    if slot is not None:
        params = urllib.parse.urlencode({"day": day, "slot": slot})
        return f"{base}/shelf-view?{params}"
    else:
        params = urllib.parse.urlencode({"day": day})
        return f"{base}/shelf-view?{params}"

def build_number_url(base_url: str, slot: int) -> str:
    """Construct URL for scanning number across all days."""
    base = base_url.rstrip("/")
    params = urllib.parse.urlencode({"slot": slot})
    return f"{base}/shelf-view?{params}"

def generate_qr_image(data: str, box_size: int = 8, border: int = 2) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e293b", back_color="#ffffff")
    return img

def generate_qr_bytes(data: str, box_size: int = 8, border: int = 2) -> bytes:
    img = generate_qr_image(data, box_size=box_size, border=border)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generate_qr_base64(data: str, box_size: int = 8, border: int = 2) -> str:
    img_bytes = generate_qr_bytes(data, box_size=box_size, border=border)
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"
