"""
Panel screens for Wi-Fi setup.

Two QR codes side by side: the first joins the hotspot (the standard
WIFI: payload phone cameras understand), the second opens the form. The
password is printed too, for phones that cannot scan a Wi-Fi QR.
"""
from PIL import Image, ImageDraw

from gcal_epd.render.draw import _QR_QUIET, _load_font, _text, _truncate
from gcal_epd.render.layout import BG, FG, HEADER_H, HEIGHT, PADDING, PALETTE, WIDTH

_QR = 160  # smaller than the calendar setup QR so two fit beside the text
_BLOCK = _QR + 2 * _QR_QUIET
_GAP = 18
_TITLE_H = 56


def wifi_qr_payload(ssid: str, password: str) -> str:
    """The WIFI: URI scheme; \\ ; , : and " must be backslash-escaped."""
    def esc(value: str) -> str:
        for ch in '\\;,:"':
            value = value.replace(ch, "\\" + ch)
        return value

    if not password:
        return f"WIFI:T:nopass;S:{esc(ssid)};;"
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"


def _qr_block(img: Image.Image, draw: ImageDraw.ImageDraw, data: str, x: int, y: int) -> None:
    """A QR on its own white panel — inverted on black it will not scan."""
    import qrcode
    qr = qrcode.QRCode(box_size=4, border=0)
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=PALETTE["black"],
                           back_color=PALETTE["white"]).convert("RGB")
    qr_img = qr_img.resize((_QR, _QR), Image.NEAREST)
    draw.rectangle([(x, y), (x + _BLOCK, y + _BLOCK)], fill=PALETTE["white"])
    img.paste(qr_img, (x + _QR_QUIET, y + _QR_QUIET))


def render_wifi_setup(
    ap_ssid: str,
    ap_password: str,
    setup_url: str,
    error: str = "",
    output_path: str = "",
    font_path: str = "",
) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    fonts = {
        "xl": _load_font(font_path, 32),
        "lg": _load_font(font_path, 20),
        "pw": _load_font(font_path, 30),
        "md": _load_font(font_path, 15),
        "sm": _load_font(font_path, 13),
    }

    draw.rounded_rectangle(
        [(PADDING, PADDING), (WIDTH - PADDING, PADDING + _TITLE_H)],
        radius=14, outline=FG, width=2,
    )
    _text(draw, (PADDING + 20, PADDING + _TITLE_H / 2), "Wi-Fi Setup", fonts["xl"], FG,
          anchor="lm", bold=1)

    top = PADDING + _TITLE_H + 22
    x1 = PADDING
    x2 = PADDING + _BLOCK + _GAP
    _qr_block(img, draw, wifi_qr_payload(ap_ssid, ap_password), x1, top)
    _qr_block(img, draw, setup_url, x2, top)

    label_y = top + _BLOCK + 12
    _text(draw, (x1, label_y), "1  Join this hotspot", fonts["md"], FG, bold=1)
    _text(draw, (x2, label_y), "2  Open the form", fonts["md"], FG, bold=1)

    text_x = x2 + _BLOCK + 26
    max_w = WIDTH - text_x - PADDING
    y = top
    _text(draw, (text_x, y), "Network", fonts["md"], FG)
    y += 22
    _text(draw, (text_x, y), _truncate(draw, ap_ssid, fonts["lg"], max_w),
          fonts["lg"], PALETTE["yellow"])
    y += 36
    _text(draw, (text_x, y), "Password", fonts["md"], FG)
    y += 22
    _text(draw, (text_x, y), ap_password, fonts["pw"], PALETTE["green"], bold=1)
    y += 50
    _text(draw, (text_x, y), "Then open", fonts["md"], FG)
    y += 22
    _text(draw, (text_x, y), _truncate(draw, setup_url, fonts["lg"], max_w),
          fonts["lg"], PALETTE["yellow"])

    y = label_y + 34
    if error:
        _text(draw, (PADDING, y), _truncate(draw, error, fonts["lg"], WIDTH - 2 * PADDING),
              fonts["lg"], PALETTE["red"], bold=1)
        y += 32
    for line in (
        "This display has no network. Join the hotspot, open the form,",
        "and choose your home Wi-Fi (2.4GHz only).",
    ):
        _text(draw, (PADDING, y), line, fonts["sm"], FG)
        y += 19

    if output_path:
        img.save(output_path)
    return img


def render_wifi_connected(ssid: str, output_path: str = "", font_path: str = "") -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    xl = _load_font(font_path, 44)
    lg = _load_font(font_path, 22)

    draw.rounded_rectangle(
        [(PADDING, PADDING), (WIDTH - PADDING, PADDING + HEADER_H)],
        radius=14, outline=PALETTE["green"], width=3,
    )
    _text(draw, (PADDING + 20, PADDING + HEADER_H / 2), "Wi-Fi connected", xl,
          PALETTE["green"], anchor="lm", bold=1)
    _text(draw, (PADDING + 20, PADDING + HEADER_H + 44),
          _truncate(draw, f"Joined {ssid}. Loading your calendar...", lg,
                    WIDTH - 2 * PADDING - 20),
          lg, FG)

    if output_path:
        img.save(output_path)
    return img
