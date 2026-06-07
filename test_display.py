"""
Standalone hardware test for Waveshare 7.3inch e-Paper HAT (F).

Mac (mock mode):
    python test_display.py --mock

Raspberry Pi (real display):
    python test_display.py

Raspberry Pi setup:
    pip install RPi.GPIO spidev
    Copy epd7in3f.py + epdconfig.py from https://github.com/waveshare/e-Paper
    into vendor/waveshare_epd/ (replacing the stubs)
    sudo raspi-config  →  Interface Options → SPI → Enable
"""
import argparse
import sys

from PIL import Image, ImageDraw, ImageFont

WIDTH = 800
HEIGHT = 480

# Exact 7-color palette of Waveshare 7.3" F (ACeP)
PALETTE = {
    "black":  (0,   0,   0),
    "white":  (255, 255, 255),
    "green":  (0,   255, 0),
    "blue":   (0,   0,   255),
    "red":    (255, 0,   0),
    "yellow": (255, 255, 0),
    "orange": (255, 128, 0),
}


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_test_image() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), PALETTE["white"])
    draw = ImageDraw.Draw(img)

    font_lg = _load_font(22)
    font_md = _load_font(15)
    font_sm = _load_font(12)

    # --- Color swatches (top bar) ---
    swatch_w = WIDTH // len(PALETTE)
    for i, (name, color) in enumerate(PALETTE.items()):
        x0 = i * swatch_w
        draw.rectangle([(x0, 0), (x0 + swatch_w - 1, 70)], fill=color)
        text_color = PALETTE["white"] if name in ("black", "blue", "green") else PALETTE["black"]
        draw.text((x0 + 6, 26), name, font=font_sm, fill=text_color)

    # --- Info text ---
    draw.text((16, 84), 'Waveshare 7.3" e-Paper HAT (F)  —  800 × 480  —  7 colors', font=font_lg, fill=PALETTE["black"])
    draw.text((16, 114), "If you can read this clearly, the display driver is working.", font=font_md, fill=PALETTE["black"])

    # --- Vertical grid (pixel ruler) ---
    for x in range(0, WIDTH + 1, 100):
        draw.line([(x, 160), (x, HEIGHT)], fill=PALETTE["black"], width=1)
        draw.text((x + 2, 162), str(x), font=font_sm, fill=PALETTE["black"])

    # --- Horizontal grid ---
    for y in range(160, HEIGHT + 1, 80):
        draw.line([(0, y), (WIDTH, y)], fill=PALETTE["black"], width=1)
        draw.text((2, y + 2), str(y), font=font_sm, fill=PALETTE["black"])

    # --- Color diagonal lines (color bleed / rendering test) ---
    colors = list(PALETTE.values())
    for i, color in enumerate(colors):
        offset = i * 12
        draw.line([(offset, 160), (WIDTH, HEIGHT - offset)], fill=color, width=3)

    return img


def push_to_display(img: Image.Image) -> None:
    try:
        from waveshare_epd import epd7in3f
    except ImportError:
        print("ERROR: waveshare_epd not found.")
        print()
        print("Install steps on Raspberry Pi:")
        print("  1. sudo raspi-config  →  Interface Options → SPI → Enable")
        print("  2. pip install RPi.GPIO spidev")
        print("  3. git clone https://github.com/waveshare/e-Paper")
        print("  4. cd e-Paper/RaspberryPi_JetsonNano/python && pip install .")
        sys.exit(1)

    epd = epd7in3f.EPD()

    print("Initializing display...")
    epd.init()

    print("Clearing display...")
    epd.Clear()

    print("Sending image — full refresh takes ~36 seconds, please wait...")
    epd.display(epd.getbuffer(img))

    print("Done. Putting display to sleep.")
    epd.sleep()


def main() -> None:
    parser = argparse.ArgumentParser(description='Test Waveshare 7.3" e-Paper HAT (F)')
    parser.add_argument("--mock", action="store_true", help="Save PNG instead of pushing to display")
    parser.add_argument("--output", default="test_preview.png", help="Output path for --mock (default: test_preview.png)")
    parser.add_argument("--clear", action="store_true", help="Clear the display and sleep (Raspberry Pi only)")
    args = parser.parse_args()

    if args.clear:
        try:
            from waveshare_epd import epd7in3f
        except ImportError:
            print("ERROR: waveshare_epd not found.")
            sys.exit(1)
        epd = epd7in3f.EPD()
        epd.init()
        epd.Clear()
        epd.sleep()
        print("Display cleared.")
        return

    img = build_test_image()

    if args.mock:
        img.save(args.output)
        print(f"Mock mode: saved to {args.output}")
    else:
        push_to_display(img)


if __name__ == "__main__":
    main()
