"""
Per-glyph font fallback for emoji.

Pillow draws a string with one font and has no fallback of its own, so a
character the CJK font lacks (🎂, 🎉, ✈, ℹ, ...) comes out as a tofu box.
Here a string is split into runs: characters the primary font has stay with
it, characters only the monochrome Noto Emoji font has go to that font, and
the runs are drawn side by side on one baseline. Width is the sum of the
runs, so truncation and underlines stay right for mixed CJK + emoji text.

"Has" means the font's cmap table maps the character, read once per font
file (just that table, with the standard library) and looked up by bisection.
Nothing is rendered to find out, and every character Noto Emoji has and the
primary font lacks falls back, whatever its Unicode category. The emoji font
itself is loaded only when a title first needs it, and a string the primary
font covers on its own is returned and drawn exactly as before.

Without libraqm Pillow does not shape emoji sequences. Noto Emoji draws
their invisible parts (ZWJ, VS15/VS16, tag characters) as nothing, so those
simply fall back like any other character: 👨‍👩‍👧 draws as 👨👩👧. Two marks
would draw a box of their own instead, so only inside a sequence the primary
font cannot draw are they dropped: a skin tone right after an emoji the
fallback draws (👍🏽 draws as 👍), and the keycap after 0-9, # or * (1️⃣ as 1).
"""
import struct
import weakref
from bisect import bisect_left, bisect_right
from functools import lru_cache
from pathlib import Path
from typing import Callable

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

# Zero-width parts of emoji sequences: ZWJ, VS15/VS16, tag characters.
_INVISIBLE = frozenset([0x200D, 0xFE0E, 0xFE0F, *range(0xE0020, 0xE0080)])
_SKIN_TONES = range(0x1F3FB, 0x1F400)
_KEYCAP = 0x20E3
_KEYCAP_BASES = frozenset("0123456789#*")

Coverage = Callable[[str], bool]


# --- cmap: which characters a font file maps -----------------------------

def _format12(table: bytes) -> Callable[[int], bool]:
    (count,) = struct.unpack_from(">I", table, 12)
    flat = struct.unpack_from(f">{3 * count}I", table, 16)  # (start, end, glyph)*
    starts, ends, glyphs = flat[0::3], flat[1::3], flat[2::3]

    def lookup(code: int) -> bool:
        i = bisect_right(starts, code) - 1
        if i < 0 or code > ends[i]:
            return False
        return glyphs[i] + code - starts[i] != 0

    return lookup


def _format4(table: bytes) -> Callable[[int], bool]:
    (seg2,) = struct.unpack_from(">H", table, 6)
    seg = seg2 // 2
    ends = struct.unpack_from(f">{seg}H", table, 14)
    starts = struct.unpack_from(f">{seg}H", table, 16 + seg2)
    deltas = struct.unpack_from(f">{seg}h", table, 16 + 2 * seg2)
    ranges_at = 16 + 3 * seg2
    ranges = struct.unpack_from(f">{seg}H", table, ranges_at)

    def lookup(code: int) -> bool:
        if code > 0xFFFF:
            return False
        i = bisect_left(ends, code)
        if i >= seg or code < starts[i]:
            return False
        if ranges[i] == 0:
            return (code + deltas[i]) & 0xFFFF != 0
        at = ranges_at + 2 * i + ranges[i] + 2 * (code - starts[i])
        if at + 2 > len(table):
            return False
        (glyph,) = struct.unpack_from(">H", table, at)
        return glyph != 0 and (glyph + deltas[i]) & 0xFFFF != 0

    return lookup


def _read_cmap(source, index: int = 0) -> Callable[[int], bool] | None:
    """A code point -> mapped? lookup from the font's Unicode cmap, or None."""
    opened = isinstance(source, (str, Path))
    f = open(source, "rb") if opened else source
    try:
        f.seek(0)
        header = f.read(12)
        if header[:4] == b"ttcf":  # collection: find the face's own table directory
            f.seek(12 + 4 * index)
            (face,) = struct.unpack(">I", f.read(4))
            f.seek(face)
            header = f.read(12)
        (num_tables,) = struct.unpack_from(">H", header, 4)
        directory = f.read(16 * num_tables)
        for i in range(num_tables):
            tag, _, offset, length = struct.unpack_from(">4sIII", directory, 16 * i)
            if tag == b"cmap":
                f.seek(offset)
                cmap = f.read(length)
                break
        else:
            return None
    finally:
        if opened:
            f.close()

    (count,) = struct.unpack_from(">H", cmap, 2)
    best = {}
    for i in range(count):
        platform, encoding, offset = struct.unpack_from(">HHI", cmap, 4 + 8 * i)
        if (platform, encoding) not in ((3, 10), (3, 1), (0, 3), (0, 4), (0, 6)):
            continue  # not a Unicode subtable
        (fmt,) = struct.unpack_from(">H", cmap, offset)
        if fmt in (4, 12):
            best.setdefault(fmt, cmap[offset:])
    if 12 in best:  # covers the emoji planes, not only the BMP
        return _format12(best[12])
    if 4 in best:
        return _format4(best[4])
    return None


def _memoized(lookup: Callable[[int], bool]) -> Coverage:
    seen: dict[str, bool] = {}

    def cover(ch: str) -> bool:
        hit = seen.get(ch)
        if hit is None:
            hit = seen[ch] = lookup(ord(ch))
        return hit

    return cover


_coverage_cache: dict[tuple, Coverage | None] = {}


# Fonts loaded from bytes (Pillow's default font): keyed by their stream,
# which lives as long as the font does.
_stream_coverage: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _coverage_of(key: tuple | None, source, index: int) -> Coverage | None:
    """Coverage of a font file, cached under `key` (None: not cached here)."""
    if key is None or key not in _coverage_cache:
        try:
            lookup = _read_cmap(source, index)
        except (OSError, struct.error, ValueError):
            lookup = None
        cover = _memoized(lookup) if lookup else None
        if key is None:
            return cover
        _coverage_cache[key] = cover
    return _coverage_cache[key]


def _coverage(font) -> Coverage | None:
    """What `font` maps, or None when its cmap cannot be read."""
    path = getattr(font, "path", None)
    index = getattr(font, "index", 0)
    if isinstance(path, (str, Path)):
        return _coverage_of((str(path), index), str(path), index)
    if hasattr(path, "read") and hasattr(path, "seek"):  # font loaded from bytes
        try:
            if path not in _stream_coverage:
                _stream_coverage[path] = _coverage_of(None, path, index)
            return _stream_coverage[path]
        except TypeError:  # a stream that cannot be weakly referenced
            return None
    return None


def _emoji_coverage() -> Coverage | None:
    path = str(EMOJI_FONT_PATH)
    return _coverage_of((path, 0), path, 0)


def has_glyph(font, ch: str) -> bool:
    """True when `font` maps `ch` to a glyph (unknown cmap: assume it does)."""
    cover = _coverage(font)
    return True if cover is None else cover(ch)


# --- the emoji font -------------------------------------------------------

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


# --- runs -----------------------------------------------------------------

def split_runs(text: str, font) -> list[tuple[str, object]]:
    """Split `text` into (substring, font) runs.

    Characters stay with `font` unless it lacks them and the emoji font has
    them. A character neither font has stays with `font` (tofu), so text in
    an unsupported script is still visibly there. A string `font` covers on
    its own comes back unchanged, as one run. Only a skin tone or keycap mark
    `font` lacks, attached to an emoji sequence, is dropped (see above).
    """
    primary = _coverage(font) if isinstance(font, ImageFont.FreeTypeFont) else None
    if primary is None:
        return [(text, font)] if text else []

    emoji_cover: Coverage | None = None
    fallback = None          # the sized emoji font, loaded on first use
    runs: list[tuple[str, object]] = []
    current, chars = font, []
    last, last_is_emoji = "", False   # the last visible character kept
    for ch in text:
        code = ord(ch)
        if primary(ch):
            use = font
        elif ((code in _SKIN_TONES and last_is_emoji)
              or (code == _KEYCAP and last in _KEYCAP_BASES)):
            continue         # unshaped, it would draw a second box
        else:
            if emoji_cover is None:
                emoji_cover = _emoji_coverage() or (lambda _ch: False)
            use = font
            if emoji_cover(ch):
                if fallback is None:
                    fallback = emoji_font(font.size)
                if fallback is not None:
                    use = fallback
        if code not in _INVISIBLE:
            last, last_is_emoji = ch, use is not font
        if use is not current:
            if chars:
                runs.append(("".join(chars), current))
            current, chars = use, []
        chars.append(ch)
    if chars:
        runs.append(("".join(chars), current))
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
