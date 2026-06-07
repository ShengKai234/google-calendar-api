"""
E-ink display push logic.
Only runs on Raspberry Pi with Waveshare driver installed in vendor/.
"""
import logging

from PIL import Image

log = logging.getLogger(__name__)


def push_to_display(img: Image.Image) -> None:
    try:
        from waveshare_epd import epd7in3f
    except ImportError:
        raise RuntimeError(
            "Waveshare driver not found.\n"
            "Make sure vendor/waveshare_epd/epd7in3f.py is the real driver,\n"
            "and run: pip install RPi.GPIO spidev gpiozero"
        )

    epd = epd7in3f.EPD()

    log.info("Initializing display...")
    epd.init()

    log.info("Sending image — full refresh takes ~36 seconds...")
    epd.display(epd.getbuffer(img))

    log.info("Done. Display going to sleep.")
    epd.sleep()
