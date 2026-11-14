"""Tests for render.text — emoji fall back to Noto Emoji instead of tofu (issue #38)."""
import datetime
import struct
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from gcal_epd.domain.event import CalendarEvent
from gcal_epd.render import text as T
from gcal_epd.render.draw import _text, _textw, _truncate, render
from gcal_epd.render.layout import (
    BG,
    COL_TITLE_X,
    FG,
    ROW_H,
    TW_TZ,
    UNDERLINE_DROP,
    WIDTH,
    build_layout,
)

ROOT = Path(__file__).parent.parent.parent
CJK_PATH = str(ROOT / "assets/fonts/NotoSansCJKtc-Regular.otf")
COMMON_EMOJI = "🎂🎉😀✈❤"  # the ones the issue lists as tofu


@pytest.fixture
def cjk():
    return ImageFont.truetype(CJK_PATH, 23)


@pytest.fixture
def draw():
    return ImageDraw.Draw(Image.new("RGB", (WIDTH, 60), BG))


def test_emoji_font_ships():
    assert T.EMOJI_FONT_PATH.is_file()
    assert (T.EMOJI_FONT_PATH.parent / "NotoEmoji-OFL.txt").is_file()


# --- glyph lookup ---

def test_cjk_font_lacks_the_common_emoji(cjk):
    for ch in COMMON_EMOJI:
        assert not T.has_glyph(cjk, ch), ch


def test_cjk_font_has_its_own_characters(cjk):
    for ch in "媽A★♥☀□":  # □ looks like .notdef but is a real glyph
        assert T.has_glyph(cjk, ch), ch


def test_emoji_font_has_the_common_emoji():
    font = T.emoji_font(23)
    for ch in COMMON_EMOJI:
        assert T.has_glyph(font, ch), ch


# --- splitting into runs ---

def test_plain_text_is_one_run_in_the_primary_font(cjk):
    runs = T.split_runs("媽媽生日 ★ Meeting", cjk)
    assert runs == [("媽媽生日 ★ Meeting", cjk)]
    assert not T.needs_fallback(runs, cjk)


def test_emoji_go_to_the_emoji_font(cjk):
    runs = T.split_runs("媽媽生日 🎂 🎉 ✈", cjk)
    emoji = T.emoji_font(cjk.size)
    assert runs == [("媽媽生日 ", cjk), ("🎂", emoji), (" ", cjk),
                    ("🎉", emoji), (" ", cjk), ("✈", emoji)]
    assert T.needs_fallback(runs, cjk)


def test_every_common_emoji_falls_back(cjk):
    runs = T.split_runs(COMMON_EMOJI, cjk)
    assert runs == [(COMMON_EMOJI, T.emoji_font(cjk.size))]


def test_info_sign_falls_back(cjk):
    """ℹ is a letter (Ll), not a symbol, yet still an emoji the CJK font lacks."""
    assert not T.has_glyph(cjk, "ℹ")
    assert T.split_runs("ℹ️ 說明", cjk) == [("ℹ\ufe0f", T.emoji_font(cjk.size)), (" 說明", cjk)]


def test_everything_noto_emoji_has_and_the_primary_lacks_falls_back(cjk):
    emoji = T.emoji_font(cjk.size)
    checked = 0
    for code in range(0x20, 0x20000):
        ch = chr(code)
        if T.has_glyph(cjk, ch) or not T.has_glyph(emoji, ch):
            continue
        if code in T._SKIN_TONES or code == T._KEYCAP:
            continue  # standalone they fall back too, checked below
        assert T.split_runs(ch, cjk) == [(ch, emoji)], hex(code)
        checked += 1
    assert checked > 1000


def test_marks_outside_an_emoji_sequence_are_kept(cjk):
    emoji = T.emoji_font(cjk.size)
    assert T.split_runs("🏽", cjk) == [("🏽", emoji)]
    assert T.split_runs("A\u20e3", cjk) == [("A", cjk), ("\u20e3", emoji)]


@pytest.mark.parametrize("text, kept", [
    ("👍🏽", "👍"),                      # skin tone after an emoji
    ("👨🏽\u200d💻", "👨\u200d💻"),       # ... inside a ZWJ sequence
    ("1️⃣", "1\ufe0f"),                  # keycap after its base
    ("#\u20e3", "#"),
])
def test_visible_marks_of_unshaped_sequences_are_dropped(cjk, text, kept):
    assert "".join(s for s, _ in T.split_runs(text, cjk)) == kept


@pytest.mark.parametrize("text", [
    "❤️", "👨\u200d👩\u200d👧", "🏴\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "A\u200dB", "☀️ 晴",
])
def test_invisible_marks_are_kept(cjk, text):
    """ZWJ, VS16 and tags draw as nothing in Noto Emoji: kept, never tofu."""
    runs = T.split_runs(text, cjk)
    assert "".join(s for s, _ in runs) == text
    for s, f in runs:
        for ch in s:
            assert T.has_glyph(f, ch), (hex(ord(ch)), f)


def test_primary_text_with_marks_stays_unchanged():
    """A primary font that has the marks keeps them all, in one run."""
    font = T.emoji_font(23)  # Noto Emoji maps ZWJ, VS16, skin tones, keycap
    for text in ("👍🏽 ok", "1️⃣", "👨\u200d👩\u200d👧", "A\u200dB"):
        assert T.split_runs(text, font) == [(text, font)]


def test_characters_the_primary_font_has_stay_with_it(cjk):
    # Noto Emoji also has digits (for keycaps); the CJK font's must win.
    assert T.split_runs("1", cjk) == [("1", cjk)]


def test_emoji_font_is_loaded_only_when_needed(cjk, monkeypatch):
    def boom(size):
        raise AssertionError("emoji font loaded for text that needs none")

    monkeypatch.setattr(T, "emoji_font", boom)
    assert T.split_runs("媽媽生日 ★ Meeting " * 50, cjk) == [("媽媽生日 ★ Meeting " * 50, cjk)]


def test_missing_emoji_font_falls_back_to_the_primary_font(cjk, monkeypatch):
    monkeypatch.setattr(T, "EMOJI_FONT_PATH", Path("/nonexistent/emoji.ttf"))
    assert T.split_runs("生日 🎂", cjk) == [("生日 🎂", cjk)]


def test_bitmap_fonts_never_fall_back():
    font = ImageFont.load_default()
    if isinstance(font, ImageFont.FreeTypeFont):
        pytest.skip("this Pillow's default font is scalable")
    assert T.split_runs("x 🎂", font) == [("x 🎂", font)]


# --- cmap parsing ---

def _format4(segments) -> bytes:
    """A cmap format 4 subtable; segments are (start, end, delta, glyphs or None)."""
    seg = len(segments)
    ends = [e for _, e, _, _ in segments]
    starts = [s for s, _, _, _ in segments]
    deltas = [d for _, _, d, _ in segments]
    arrays, offsets = [], []
    for i, (_, _, _, glyphs) in enumerate(segments):
        if glyphs is None:
            offsets.append(0)
        else:  # bytes from idRangeOffset[i] to its slice of glyphIdArray
            offsets.append(2 * (seg - i) + 2 * len(arrays))
            arrays += glyphs
    body = struct.pack(f">{seg}H", *ends) + b"\0\0" + struct.pack(f">{seg}H", *starts)
    body += struct.pack(f">{seg}h", *deltas) + struct.pack(f">{seg}H", *offsets)
    body += struct.pack(f">{len(arrays)}H", *arrays)
    return struct.pack(">7H", 4, 14 + len(body), 0, 2 * seg, 0, 0, 0) + body


def test_cmap_format4_lookup():
    lookup = T._format4(_format4([
        (0x41, 0x43, 1 - 0x41, None),          # A-C -> glyphs 1-3 by delta
        (0x2139, 0x213B, 0, [7, 0, 9]),        # via glyphIdArray; U+213A unmapped
        (0xFFFF, 0xFFFF, 1, None),             # terminator maps to .notdef
    ]))
    assert [lookup(c) for c in (0x40, 0x41, 0x43, 0x44)] == [False, True, True, False]
    assert [lookup(c) for c in (0x2139, 0x213A, 0x213B)] == [True, False, True]
    assert not lookup(0xFFFF)
    assert not lookup(0x1F382)  # beyond the BMP


def test_cmap_agrees_with_what_pillow_draws(cjk):
    """Mapped glyphs differ from .notdef; unmapped ones render exactly as it."""
    notdef = bytes(cjk.getmask("\U0010FFFD"))
    for ch in "媽A★♥☀□→—" + COMMON_EMOJI + "ℹ\u2122\u2194":
        assert T.has_glyph(cjk, ch) == (bytes(cjk.getmask(ch)) != notdef), hex(ord(ch))


def test_unreadable_font_never_falls_back(tmp_path):
    bogus = tmp_path / "x.ttf"
    bogus.write_bytes(b"not a font")
    assert T._coverage_of(("bogus", 0), str(bogus), 0) is None


# --- width, truncation, drawing ---

def test_width_is_the_sum_of_the_runs(draw, cjk):
    title = "媽媽生日 🎂 🎉 ✈"
    expected = sum(draw.textlength(s, font=f) for s, f in T.split_runs(title, cjk))
    assert _textw(draw, title, cjk) == pytest.approx(expected)
    assert _textw(draw, title, cjk, bold=2) == pytest.approx(expected + 4)
    # Not the width of three tofu boxes in the CJK font.
    assert _textw(draw, title, cjk) != pytest.approx(draw.textlength(title, font=cjk))


def test_truncate_measures_mixed_text(draw, cjk):
    title = "很長的標題 " + COMMON_EMOJI * 10
    limit = 300
    out = _truncate(draw, title, cjk, limit)
    assert out.endswith("…")
    assert _textw(draw, out, cjk) <= limit
    # One more character would not have fit.
    assert _textw(draw, title[:len(out)] + "…", cjk) > limit


def _truncate_linear(draw, text, font, max_width):
    """The original one-character-at-a-time algorithm, as a reference."""
    if _textw(draw, text, font) <= max_width:
        return text
    while text and _textw(draw, text + "…", font) > max_width:
        text = text[:-1]
    return text + "…"


@pytest.mark.parametrize("text", [
    "", "短", "媽媽生日 🎂 🎉 ✈", "Plain ASCII title that is long enough to be cut " * 3,
    "很長的標題 " + COMMON_EMOJI * 10, "ℹ️" * 40, "a" * 15, "a" * 16, "a" * 17,
])
@pytest.mark.parametrize("limit", [-5, 0, 10, 60, 300, 480])
def test_truncate_matches_the_linear_reference(draw, cjk, text, limit):
    assert _truncate(draw, text, cjk, limit) == _truncate_linear(draw, text, cjk, limit)


def _ink(img: Image.Image) -> tuple | None:
    return Image.eval(img.convert("L"), lambda v: 255 if v > 128 else 0).getbbox()


def test_emoji_are_drawn_with_the_emoji_font(cjk):
    """The pixels are Noto Emoji's cake, not the CJK font's .notdef box."""
    def paint(fn):
        img = Image.new("RGB", (80, 40), BG)
        fn(ImageDraw.Draw(img))
        return img

    ours = paint(lambda d: _text(d, (4, 20), "🎂", cjk, FG, anchor="lm"))
    tofu = paint(lambda d: d.text((4, 20), "🎂", font=cjk, fill=FG, anchor="lm"))
    emoji = T.emoji_font(cjk.size)
    direct = paint(lambda d: d.text((4, 20), "🎂", font=emoji, fill=FG, anchor="lm"))
    assert ours.tobytes() != tofu.tobytes()
    # Same glyph; the vertical placement follows the CJK baseline instead.
    assert _ink(ours)[2] - _ink(ours)[0] == _ink(direct)[2] - _ink(direct)[0]


def test_plain_text_draws_exactly_as_before(cjk):
    def paint(fn):
        img = Image.new("RGB", (200, 40), BG)
        fn(ImageDraw.Draw(img))
        return img.tobytes()

    assert (paint(lambda d: _text(d, (190, 20), "媽媽生日", cjk, FG, anchor="rm", bold=1))
            == paint(lambda d: d.text((190, 20), "媽媽生日", font=cjk, fill=FG, anchor="rm",
                                      stroke_width=1, stroke_fill=FG)))


@pytest.mark.parametrize("anchor", ["la", "lm", "rm", "ls"])
def test_mixed_text_honours_the_anchor(cjk, anchor):
    """Mixed text lands where the same text in one font would, give or take a pixel."""
    def ink(text):
        img = Image.new("RGB", (400, 80), BG)
        _text(ImageDraw.Draw(img), (200, 40), text, cjk, FG, anchor=anchor)
        return _ink(img)

    mixed, plain = ink("生日🎂快樂"), ink("生日日快樂")
    if anchor[0] == "l":
        assert abs(mixed[0] - plain[0]) <= 1
    else:
        assert abs(mixed[2] - plain[2]) <= 1
    assert abs(mixed[3] - plain[3]) <= 4   # emoji descend a little, not a row


def test_title_underline_spans_the_mixed_title(tmp_path):
    title = "媽媽生日 🎂 🎉 ✈"
    start = datetime.datetime.now(TW_TZ).strftime("%Y-%m-%dT09:00:00")
    events = [CalendarEvent(start=start, title=title, calendar_name="Home")]
    img = render(events, output_path=str(tmp_path / "out.png"), font_path=CJK_PATH)

    row = build_layout(events)[0]
    y = int(row.y + ROW_H / 2 + UNDERLINE_DROP)
    lit = [x for x in range(COL_TITLE_X, WIDTH) if img.getpixel((x, y)) == FG]
    expected = _textw(ImageDraw.Draw(img), title, ImageFont.truetype(CJK_PATH, 23))
    assert lit[0] == COL_TITLE_X
    assert abs(lit[-1] - (COL_TITLE_X + expected)) <= 1


def test_default_font_from_bytes_falls_back_too():
    font = ImageFont.load_default(23)
    if not isinstance(font, ImageFont.FreeTypeFont):
        pytest.skip("this Pillow's default font is a bitmap")
    runs = T.split_runs("x 🎂", font)
    assert runs == [("x ", font), ("🎂", T.emoji_font(23))]
