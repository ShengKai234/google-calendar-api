"""Tests for render.text — emoji fall back to Noto Emoji instead of tofu (issue #38)."""
import datetime
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


@pytest.mark.parametrize("text, kept", [
    ("❤️", "❤"),              # VS16
    ("👍🏽", "👍"),             # skin tone
    ("👨‍👩‍👧", "👨👩👧"),          # ZWJ sequence, unshaped without raqm
])
def test_shaping_only_marks_are_dropped(cjk, text, kept):
    assert "".join(s for s, _ in T.split_runs(text, cjk)) == kept


def test_characters_the_primary_font_has_stay_with_it(cjk):
    # Noto Emoji also has digits (for keycaps); the CJK font's must win.
    assert T.split_runs("1️⃣", cjk) == [("1", cjk)]


def test_missing_emoji_font_falls_back_to_the_primary_font(cjk, monkeypatch):
    monkeypatch.setattr(T, "EMOJI_FONT_PATH", Path("/nonexistent/emoji.ttf"))
    assert T.split_runs("生日 🎂", cjk) == [("生日 🎂", cjk)]


def test_bitmap_fonts_never_fall_back():
    font = ImageFont.load_default()
    if isinstance(font, ImageFont.FreeTypeFont):
        pytest.skip("this Pillow's default font is scalable")
    assert T.split_runs("x 🎂", font) == [("x 🎂", font)]


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
