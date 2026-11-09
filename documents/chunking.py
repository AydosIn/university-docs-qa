"""Split page text into small passages that search can return individually."""

import re
import textwrap
from dataclasses import dataclass

MAX_CHUNK_CHARS = 900
OVERLAP_CHARS = 150

# A piece must leave room for the overlap copied from the previous chunk.
MAX_PIECE_CHARS = MAX_CHUNK_CHARS - OVERLAP_CHARS

# Heading words in English, Uzbek and Russian, such as "Section 2: Exams".
HEADING_PATTERN = re.compile(
    r"^(section|chapter|article|part|bo['ʻ’`]?lim|modda|раздел|глава|статья)\s+\S+",
    re.IGNORECASE,
)
MAX_HEADING_CHARS = 100


@dataclass
class ChunkDraft:
    page_number: int
    section: str
    text: str


def _pieces(text):
    """Yield the text as lines, breaking up any line that is too long."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) <= MAX_PIECE_CHARS:
            yield line
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            yield from textwrap.wrap(sentence, MAX_PIECE_CHARS)


def _overlap_tail(pieces):
    """Return the last pieces of a chunk, within the overlap limit."""
    tail = []
    size = 0
    for piece in reversed(pieces):
        if size + len(piece) + 1 > OVERLAP_CHARS:
            break
        tail.insert(0, piece)
        size += len(piece) + 1
    return tail


def split_text(text):
    """Group pieces into chunks. Neighbouring chunks share a little text.

    The overlap keeps a rule findable even when a chunk boundary falls in the
    middle of it.
    """
    chunks = []
    current = []
    size = 0

    for piece in _pieces(text):
        if current and size + len(piece) + 1 > MAX_CHUNK_CHARS:
            chunks.append("\n".join(current))
            current = _overlap_tail(current)
            size = sum(len(p) + 1 for p in current)
        current.append(piece)
        size += len(piece) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


def _headings(text):
    return [
        line.strip()
        for line in text.splitlines()
        if len(line.strip()) <= MAX_HEADING_CHARS
        and HEADING_PATTERN.match(line.strip())
    ]


def build_chunks(page_texts):
    """Turn a list of page texts into chunks tagged with page and section.

    Chunks never cross a page boundary, so every citation points to one page.
    """
    drafts = []
    current_section = ""

    for page_number, page_text in enumerate(page_texts, start=1):
        for text in split_text(page_text):
            headings = _headings(text)
            section = headings[0] if headings else current_section
            if headings:
                current_section = headings[-1]
            drafts.append(ChunkDraft(page_number, section, text))
    return drafts
