"""The panel driver needs a writable directory for lgpio's pipes."""
from gcal_epd import config, epd


def test_lgpio_pipes_go_to_the_data_dir(tmp_path):
    env = {}
    epd.use_writable_lgpio_dir(tmp_path, env)
    assert env["LG_WD"] == str(tmp_path)


def test_an_lg_wd_already_set_is_kept(tmp_path):
    env = {"LG_WD": "/run/mine"}
    epd.use_writable_lgpio_dir(tmp_path, env)
    assert env["LG_WD"] == "/run/mine"


def test_default_is_this_displays_data_dir():
    env = {}
    epd.use_writable_lgpio_dir(env=env)
    assert env["LG_WD"] == str(config.DATA_DIR)


def test_push_sends_the_whole_panel_with_the_screen_in_the_window(monkeypatch, tmp_path):
    """The driver gets 800x480: the window-sized screen pasted at its place."""
    import sys
    import types

    from PIL import Image

    from gcal_epd.render.frame import ORIGIN_X, ORIGIN_Y
    from gcal_epd.render.layout import BG, HEIGHT, PALETTE, PANEL_H, PANEL_W, WIDTH

    shown = []

    class FakeEPD:
        def init(self): pass
        def getbuffer(self, img): return img
        def display(self, buf): shown.append(buf)
        def sleep(self): pass

    pkg = types.ModuleType("waveshare_epd")
    pkg.epd7in3f = types.SimpleNamespace(EPD=FakeEPD)
    monkeypatch.setitem(sys.modules, "waveshare_epd", pkg)
    monkeypatch.setitem(sys.modules, "waveshare_epd.epd7in3f", pkg.epd7in3f)
    monkeypatch.setenv("LG_WD", str(tmp_path))

    screen = Image.new("RGB", (WIDTH, HEIGHT), BG)
    screen.putpixel((0, 0), PALETTE["red"])
    epd.push_to_display(screen, (1, 2))

    (panel,) = shown
    assert panel.size == (PANEL_W, PANEL_H)
    assert panel.getpixel((ORIGIN_X + 1, ORIGIN_Y + 2)) == PALETTE["red"]
