"""Tests for the Wi-Fi setup panel screens."""
from gcal_epd.render.draw import _QR_QUIET
from gcal_epd.render.layout import HEIGHT, PADDING, PALETTE, WIDTH
from gcal_epd.render.wifi_screens import (
    _BLOCK,
    _GAP,
    _TITLE_H,
    render_wifi_connected,
    render_wifi_setup,
    wifi_qr_payload,
)


def test_wifi_qr_payload_wpa():
    assert wifi_qr_payload("Home", "abcdefgh") == "WIFI:T:WPA;S:Home;P:abcdefgh;;"


def test_wifi_qr_payload_escapes_special_characters():
    assert wifi_qr_payload('a;b,c:d"e\\f', "p;w") == \
        'WIFI:T:WPA;S:a\\;b\\,c\\:d\\"e\\\\f;P:p\\;w;;'


def test_wifi_qr_payload_open_network():
    assert wifi_qr_payload("Cafe", "") == "WIFI:T:nopass;S:Cafe;;"


def test_render_wifi_setup_returns_image(tmp_path):
    img = render_wifi_setup("ePaper-Setup-AB12", "abcdefgh23", "http://10.42.0.1",
                            output_path=str(tmp_path / "w.png"))
    assert img.size == (WIDTH, HEIGHT)


def test_render_wifi_setup_both_qrs_sit_on_white(tmp_path):
    img = render_wifi_setup("ePaper-Setup-AB12", "abcdefgh23", "http://10.42.0.1")
    top = PADDING + _TITLE_H + 22
    for x in (PADDING, PADDING + _BLOCK + _GAP):
        assert img.getpixel((x + _QR_QUIET // 2, top + _QR_QUIET // 2)) == PALETTE["white"]


def test_render_wifi_setup_with_error_and_long_ssid(tmp_path):
    img = render_wifi_setup("ePaper-Setup-" + "X" * 80, "abcdefgh23", "http://10.42.0.1",
                            error="Could not join " + "Y" * 120 + ". Check the password.")
    assert img.size == (WIDTH, HEIGHT)


def test_render_wifi_setup_error_is_drawn_in_red(tmp_path):
    plain = render_wifi_setup("S", "abcdefgh23", "http://10.42.0.1")
    failed = render_wifi_setup("S", "abcdefgh23", "http://10.42.0.1", error="Could not join")

    def colors(img):
        return {c for _, c in img.getcolors(maxcolors=WIDTH * HEIGHT)}

    assert PALETTE["red"] not in colors(plain)
    assert PALETTE["red"] in colors(failed)


def test_render_wifi_connected_returns_image(tmp_path):
    img = render_wifi_connected("Home", output_path=str(tmp_path / "ok.png"))
    assert img.size == (WIDTH, HEIGHT)
