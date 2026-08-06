"""Split document text into retrievable chunks.

Ported unchanged from the Chatbot project's src/chunker.py. Two strategies:
heading-based (for markdown authored with '##'/'###' structure) and
fixed-size windows as the fallback for anything without that structure --
which is most uploaded documents here, since Constellate's uploads are
arbitrary PDFs/docx/images, not markdown authored like Chatbot's handbook.
Kept both anyway: a markdown upload with real headings still benefits from
heading-based chunking exactly the way it did in Chatbot.
"""

import re
from dataclasses import dataclass

from .textutil import normalize_whitespace


@dataclass
class Chunk:
    id: str
    text: str
    topic: str        # slug, e.g. derived from a heading or the filename
    topic_label: str  # heading as written, or the document's title
    section: str      # heading, or "Part N" for fixed-size chunks
    # Which uploaded document this came from -- distinct from topic_label:
    # two different documents can both have a "Facilities" section (or, for
    # fixed-size chunks, an ambiguous topic_label), and this is what a
    # blended, multi-document answer uses to attribute a passage correctly.
    source: str = "Document"

    @property
    def citation(self):
        return f"{self.topic_label} → {self.section}"

    @property
    def embed_text(self):
        """What gets embedded: headings prepended to the body -- carries
        real retrieval signal beyond the body text alone. Only `text` is
        ever shown back to the user or handed to the LLM as context."""
        return f"{self.topic_label}. {self.section}. {self.text}"


def slugify_topic(heading):
    key = heading.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-")


def chunk_by_heading(markdown_text):
    """Return a list of Chunk, one per '###' section under a '##' topic."""
    chunks = []
    topic_label = "General"
    section = None
    buffer = []

    def flush():
        if section is None:
            return
        body = normalize_whitespace(" ".join(buffer))
        if not body:
            return
        chunks.append(
            Chunk(
                id=f"{slugify_topic(topic_label)}--{len(chunks):03d}",
                text=body,
                topic=slugify_topic(topic_label),
                topic_label=topic_label,
                section=section,
            )
        )

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()

        if line.startswith("### "):
            flush()
            section = line[4:].strip()
            buffer = []
        elif line.startswith("## "):
            flush()
            section = None
            buffer = []
            topic_label = line[3:].strip()
        elif line.startswith("# ") or line.startswith(">"):
            continue
        elif section is not None:
            buffer.append(line)

    flush()
    return chunks


DEFAULT_CHUNK_CHARS = 800
DEFAULT_CHUNK_OVERLAP = 100


def chunk_fixed_size(text, title, chunk_chars=DEFAULT_CHUNK_CHARS, overlap_chars=DEFAULT_CHUNK_OVERLAP):
    """Fallback for text with no heading structure: fixed-size, overlapping
    windows, breaking on whitespace so a chunk doesn't end mid-word.

    Topic and section are both derived from the document's own title, since
    there's no heading to name them -- "Town Guide → Part 2". The overlap
    exists so a fact sitting right at a window boundary isn't split in half
    and lost from both chunks.
    """
    body = normalize_whitespace(text)
    if not body:
        return []

    topic_label = title
    topic = slugify_topic(title)
    chunks = []
    start = 0
    while start < len(body):
        end = min(start + chunk_chars, len(body))
        if end < len(body):
            boundary = body.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        piece = body[start:end].strip()
        if piece:
            chunks.append(
                Chunk(
                    id=f"{topic}--{len(chunks):03d}",
                    text=piece,
                    topic=topic,
                    topic_label=topic_label,
                    section=f"Part {len(chunks) + 1}",
                )
            )
        if end >= len(body):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def humanize_filename(path):
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return stem.title() if stem else "Document"


def load_chunks(path, title=None):
    """'##'/'###'-heading markdown chunks first; if none are found, fall
    back to fixed-size windows instead of returning nothing."""
    text = path.read_text(encoding="utf-8")
    return chunk_text(text, title or humanize_filename(path))


def chunk_text(text, title):
    """Same heading-first, fixed-size-fallback logic as load_chunks, but
    operating on text already in memory -- an uploaded file's bytes have
    already gone through extract.py by the time chunking happens here,
    there's no on-disk document to read a second time the way Chatbot's
    persisted handbook.md needs load_chunks(path) for."""
    chunks = chunk_by_heading(text)
    if chunks:
        return chunks
    return chunk_fixed_size(text, title)
