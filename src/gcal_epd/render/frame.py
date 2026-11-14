"""
From a screen to the panel: where the photo-frame window sits.

Every screen is drawn at the window's size (layout.WIDTH x HEIGHT). The driver
needs the whole 800x480 panel, so `to_panel` pastes the screen onto a BG
canvas at the window's position: centred, plus an optional nudge for a mat
that does not sit dead centre, `[display] frame_offset_px = [x, y]` in
config.toml or this display's config.local.toml.
"""
import logging

from PIL import Image

from gcal_epd.render.layout import BG, HEIGHT, PANEL_H, PANEL_W, WIDTH

log = logging.getLogger(__name__)

# The centred window's top-left corner on the panel: 52 px / 22 px of
# panel are hidden on the left / top (53 / 23 on the right / bottom).
ORIGIN_X = (PANEL_W - WIDTH) // 2
ORIGIN_Y = (PANEL_H - HEIGHT) // 2

# How far the window can move before part of it falls off the panel.
OFFSET_X_RANGE = (-ORIGIN_X, PANEL_W - WIDTH - ORIGIN_X)
OFFSET_Y_RANGE = (-ORIGIN_Y, PANEL_H - HEIGHT - ORIGIN_Y)


def frame_offset(config: dict) -> tuple[int, int]:
    """[display] frame_offset_px as (x, y); (0, 0) if absent or unusable.

    A bad value is logged and ignored rather than fatal: a typo in the
    config must not leave the panel blank.
    """
    raw = config.get("display", {}).get("frame_offset_px", [0, 0])
    if (
        not isinstance(raw, (list, tuple)) or len(raw) != 2
        or not all(isinstance(v, int) and not isinstance(v, bool) for v in raw)
    ):
        log.warning("Ignoring [display] frame_offset_px = %r: expected [x, y] in pixels.", raw)
        return 0, 0
    x, y = raw
    if not (OFFSET_X_RANGE[0] <= x <= OFFSET_X_RANGE[1]
            and OFFSET_Y_RANGE[0] <= y <= OFFSET_Y_RANGE[1]):
        log.warning(
            "Ignoring [display] frame_offset_px = %r: x must be %d..%d and y %d..%d "
            "to keep the window on the panel.", raw, *OFFSET_X_RANGE, *OFFSET_Y_RANGE,
        )
        return 0, 0
    return x, y


def to_panel(screen: Image.Image, offset: tuple[int, int] = (0, 0)) -> Image.Image:
    """The full 800x480 panel image: `screen` in the window, BG under the mat."""
    if screen.size == (PANEL_W, PANEL_H):
        return screen   # already a whole panel (e.g. a hardware test pattern)
    if screen.size != (WIDTH, HEIGHT):
        raise ValueError(f"expected a {WIDTH}x{HEIGHT} screen, got {screen.size[0]}x{screen.size[1]}")
    panel = Image.new("RGB", (PANEL_W, PANEL_H), BG)
    panel.paste(screen.convert("RGB"), (ORIGIN_X + offset[0], ORIGIN_Y + offset[1]))
    return panel
