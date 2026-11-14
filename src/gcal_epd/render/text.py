"""
Per-glyph font fallback for emoji.

Pillow draws a string with one font and has no fallback of its own, so a
character the CJK font lacks (🎂, 🎉, ✈, ...) comes out as a tofu box. Here a
string is split into runs: characters the primary font has stay with it,
characters only the monochrome Noto Emoji font has go to that font, and the
runs are drawn side by side on one baseline. Width is the sum of the runs, so
truncation and underlines stay right for mixed CJK + emoji text.

Kept cheap for a Pi Zero: only symbol characters (Unicode category S*, or
anything from U+1F000 up) are looked up at all, so CJK and Latin text never
is; each lookup is cached per font file and character; and a string the
primary font covers on its own is drawn exactly as before, in one call.

Without libraqm Pillow does not shape emoji sequences, so the joiners and
modifiers that only make sense when shaped (ZWJ, VS15/VS16, skin tones,
keycap, tag characters) are dropped: 👍🏽 draws as 👍 and 👨‍👩‍👧 as 👨👩👧.
"""
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

EMOJI_FONT_PATH = (
    Path(__file__).parent.parent.parent.parent
    / "assets" / "fonts" / "NotoEmoji-VariableFont_wght.ttf"
)

# Noto Emoji draws a little larger than the CJK font at the same size;
# this brings an emoji to about the height of a CJK character.
EMOJI_SCALE = 0.95
# The font is variable (300-700). Bold keeps its thin outlines solid once
# the image is reduced to the panel's seven colors.
EMOJI_WEIGHT = 700

# Below this every character is Latin, Greek, Cyrillic or similar: the
# primary font has them (or no fallback would help), so skip the lookup.
_FALLBACK_FROM = 0x2000
_EMOJI_PLANE = 0x1F000  # from here on, always worth a lookup

# A code point no font maps: whatever it renders as is the font's .notdef.
_MISSING = "\U0010FFFD"
_PROBE_SIZE = 48  # large enough that a box-like glyph (□) differs from .notdef

_DROPPED = frozenset(
    [0x200D, 0xFE0E, 0xFE0F, 0x20E3]
    + list(range(0x1F3FB, 0x1F400))   # skin tone modifiers
    + list(range(0xE0020, 0xE0080))   # tag characters (subdivision flags)
)

_glyph_cache: dict[tuple, bool] = {}


def _is_freetype(font) -> bool:
    return isinstance(font, ImageFont.FreeTypeFont)


def _face_key(font) -> tuple:
    path = getattr(font, "path", None)
    if isinstance(path, (str, Path)):
        return (str(path), getattr(font, "index", 0))
    return ("id", id(font))


def _fingerprint(font, ch: str) -> tuple:
    mask = font.getmask(ch)
    return mask.size, bytes(mask), font.getlength(ch)


@lru_cache(maxsize=None)
def _probe(path: str, index: int) -> tuple[ImageFont.FreeTypeFont, tuple]:
    """The face at a fixed size, and what its .notdef looks like there."""
    font = ImageFont.truetype(path, _PROBE_SIZE, index=index)
    return font, _fingerprint(font, _MISSING)


def has_glyph(font, ch: str) -> bool:
    """True when `font` has a real glyph for `ch`, not its .notdef box."""
    key = _face_key(font) + (ch,)
    cached = _glyph_cache.get(key)
    if cached is None:
        if key[0] == "id":
            probe, notdef = font, _fingerprint(font, _MISSING)
        else:
            probe, notdef = _probe(*key[:2])
        cached = _fingerprint(probe, ch) != notdef
        _glyph_cache[key] = cached
    return cached


def _may_be_emoji(ch: str, code: int) -> bool:
    return code >= _EMOJI_PLANE or (
        code >= _FALLBACK_FROM and unicodedata.category(ch)[0] == "S")


@lru_cache(maxsize=None)
def _load_emoji(path: str, size: int) -> ImageFont.FreeTypeFont | None:
    try:
        font = ImageFont.truetype(path, size)
    except OSError:  # font not shipped: fall back to tofu, never crash
        return None
    try:
        font.set_variation_by_axes([EMOJI_WEIGHT])
    except (OSError, AttributeError):  # FreeType without variation support
        pass
    return font


def emoji_font(size: float) -> ImageFont.FreeTypeFont | None:
    """The emoji font matching a primary font of `size` px, or None."""
    return _load_emoji(str(EMOJI_FONT_PATH), max(1, round(size * EMOJI_SCALE)))


def split_runs(text: str, font) -> list[tuple[str, object]]:
    """Split `text` into (substring, font) runs, dropping shaping-only marks.

    Characters stay with `font` unless it lacks them and the emoji font has
    them. A missing character neither font has stays with `font` (tofu), so
    text in an unsupported script is still visibly there.
    """
    fallback = emoji_font(font.size) if _is_freetype(font) else None
    runs: list[tuple[str, object]] = []
    for ch in text:
        code = ord(ch)
        if code in _DROPPED:
            continue
        use = font
        if (fallback is not None and _may_be_emoji(ch, code)
                and not has_glyph(font, ch) and has_glyph(fallback, ch)):
            use = fallback
        if runs and runs[-1][1] is use:
            runs[-1] = (runs[-1][0] + ch, use)
        else:
            runs.append((ch, use))
    return runs


def needs_fallback(runs, font) -> bool:
    """True unless `runs` is one run (or none) in `font` alone."""
    return any(f is not font for _, f in runs)


def runs_width(draw, runs) -> float:
    return sum(draw.textlength(s, font=f) for s, f in runs)


def text_width(draw, text: str, font) -> float:
    return runs_width(draw, split_runs(text, font))


def draw_runs(draw, xy, runs, font, anchor: str = "la", **kwargs) -> None:
    """Draw `runs` on one line as if they were `text` drawn with `font`.

    The horizontal anchor (l/m/r) applies to the whole line; the vertical
    one is resolved against the primary `font`, then every run is drawn on
    that font's baseline so CJK and emoji glyphs line up.
    """
    x, y = xy
    h, v = anchor[0], anchor[1]
    total = runs_width(draw, runs)
    if h == "m":
        x -= total / 2
    elif h == "r":
        x -= total

    sample = "".join(s for s, f in runs if f is font) or "M"
    top_v = font.getbbox(sample, anchor="l" + v)[1]
    top_s = font.getbbox(sample, anchor="ls")[1]
    baseline = y + top_v - top_s

    for s, f in runs:
        draw.text((x, baseline), s, font=f, anchor="ls", **kwargs)
        x += draw.textlength(s, font=f)
