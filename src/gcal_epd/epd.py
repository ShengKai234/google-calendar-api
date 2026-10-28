"""
E-ink display push logic.
Only runs on Raspberry Pi with Waveshare driver installed in vendor/.
"""
import logging
import os
from pathlib import Path

from PIL import Image

from gcal_epd.config import DATA_DIR

log = logging.getLogger(__name__)


def use_writable_lgpio_dir(data: Path = DATA_DIR, env=os.environ) -> None:
    """Give lgpio somewhere to keep its notification pipes.

    lgpio makes them (.lgd-nfy*) in $LG_WD, else in the working directory.
    The units run in the code directory, which in an installed release
    belongs to root: lgpio then fails, and gpiozero falls back to the sysfs
    pin driver, which current kernels no longer have ("OSError: [Errno 22]
    Invalid argument" on .../gpio/export). The data directory is writable
    by both the app's user and root (the Wi-Fi setup). An LG_WD already set
    is kept. Must run before lgpio is first imported.
    """
    env.setdefault("LG_WD", str(data))


def push_to_display(img: Image.Image) -> None:
    use_writable_lgpio_dir()
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

    log.info("Sending image — a full refresh takes about 15–30 seconds...")
    epd.display(epd.getbuffer(img))

    log.info("Done. Display going to sleep.")
    epd.sleep()
