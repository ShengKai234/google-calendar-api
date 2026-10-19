"""English docs are the source; each .zh-TW.md must keep the same shape.

Text is free to differ — that is the translation. What must match is the
skeleton: headings, tables, and every diagram's nodes and arrows, so a
section or a box added to one language cannot silently miss the other.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
PAIRS = [
    (ROOT / "README.md", ROOT / "README.zh-TW.md"),
    (ROOT / "docs" / "ARCHITECTURE.md", ROOT / "docs" / "ARCHITECTURE.zh-TW.md"),
]
IDS = [p[0].relative_to(ROOT).as_posix() for p in PAIRS]


def _split(text: str) -> tuple[list[str], list[list[str]]]:
    """Prose lines outside code fences, and the lines of each mermaid block."""
    prose, diagrams, fence, block = [], [], None, None
    for line in text.splitlines():
        if line.startswith("```"):
            if fence is None:
                fence = line[3:].strip()
                block = [] if fence == "mermaid" else None
            else:
                if block is not None:
                    diagrams.append(block)
                fence, block = None, None
            continue
        if fence is None:
            prose.append(line)
        elif block is not None:
            block.append(line)
    return prose, diagrams


def _skeleton(diagram: list[str]) -> list[str]:
    """A diagram with its words removed: ids, shapes and arrows only."""
    out = []
    for line in diagram:
        line = re.sub(r'"[^"]*"', '""', line).rstrip()
        if re.match(r"\s*participant ", line):
            line = line.split(" as ")[0]
        elif m := re.match(r"(\s*(?:alt|else|opt|loop|note \w+ of \w+))\b", line):
            line = m.group(1)  # block keyword stays, its caption is prose
        elif re.search(r"-+>>|-->>", line):  # sequence message: drop its text
            line = line.split(":")[0]
        out.append(line)
    return out


def _headings(prose):
    return [len(m.group(1)) for line in prose if (m := re.match(r"(#+) ", line))]


def _tables(prose):
    return sum(1 for line in prose if re.match(r"\|\s*-{3,}", line))


@pytest.mark.parametrize("en, zh", PAIRS, ids=IDS)
def test_same_heading_outline(en, zh):
    assert _headings(_split(en.read_text())[0]) == _headings(_split(zh.read_text())[0])


@pytest.mark.parametrize("en, zh", PAIRS, ids=IDS)
def test_same_number_of_tables(en, zh):
    assert _tables(_split(en.read_text())[0]) == _tables(_split(zh.read_text())[0])


@pytest.mark.parametrize("en, zh", PAIRS, ids=IDS)
def test_same_diagrams(en, zh):
    en_d, zh_d = _split(en.read_text())[1], _split(zh.read_text())[1]
    assert len(en_d) == len(zh_d)
    for i, (a, b) in enumerate(zip(en_d, zh_d)):
        assert _skeleton(a) == _skeleton(b), f"diagram {i + 1} differs in structure"


@pytest.mark.parametrize("en, zh", PAIRS, ids=IDS)
def test_each_links_to_the_other(en, zh):
    assert f"]({zh.name})" in en.read_text()
    assert f"]({en.name})" in zh.read_text()
