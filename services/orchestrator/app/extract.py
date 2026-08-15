"""Turn uploaded file bytes into plain text, keyed off the file extension.

Started as a straight port of the Chatbot project's src/extract.py, since
this is generic file-format parsing with nothing document-app-specific in
it. Since then, PDF handling grew two things Chatbot's version never
needed: per-page table extraction (pdfplumber, alongside pypdf's flattened
text) and per-page OCR fallback (pytesseract + PyMuPDF) instead of an
all-or-nothing check on the whole document, so a mostly-digital PDF with a
few scanned or diagram pages mixed in doesn't lose just those pages.

Kept separate from chunker.py on purpose: this module's job ends at "here
is the document's text"; chunker.py's job starts once there is text to
split into chunks.
"""

import io

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class UnsupportedFileType(Exception):
    pass


def extract_text(filename, raw_bytes):
    ext = _extension(filename)
    if ext in (".md", ".markdown", ".txt"):
        return raw_bytes.decode("utf-8", errors="replace")
    if ext == ".pdf":
        return _extract_pdf(raw_bytes)
    if ext == ".docx":
        return _extract_docx(raw_bytes)
    if ext in IMAGE_EXTENSIONS:
        return _extract_image(raw_bytes)
    raise UnsupportedFileType(
        f"Unsupported file type '{ext or filename}'. "
        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )


def _extension(filename):
    return f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""


def _extract_pdf(raw_bytes):
    import pypdf  # deferred: only needed once a .pdf is actually uploaded

    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    pages = _append_tables(raw_bytes, pages)
    pages = _ocr_blank_pages(raw_bytes, pages)
    text = "\n\n".join(pages)
    if not text.strip():
        raise UnsupportedFileType(
            "Could not extract any text from this PDF, even with OCR — the "
            "scan quality may be too low to read."
        )
    return text


def _append_tables(raw_bytes, page_texts):
    """Enrich each page's text with any tables pdfplumber finds on it.

    pypdf's extract_text() flattens a table's cells into running prose --
    the grid is gone, so a question like "what's in row 3, column 2"
    has nothing to retrieve against. pdfplumber sees the same page as a
    grid of cells instead, so its output gets appended alongside (not
    instead of) the pypdf text: the flattened prose still helps a
    general mention of a value get found, the row/column rendering is
    what makes a structured lookup answerable.

    Best-effort on purpose -- pdfplumber chokes on some malformed or
    unusual PDFs pypdf handles fine, and losing the table enrichment on
    those is a much smaller problem than losing extraction entirely.
    """
    import pdfplumber  # deferred: only needed once a .pdf is actually uploaded

    try:
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= len(page_texts):
                    break
                for table in page.extract_tables():
                    rendered = _render_table(table)
                    if rendered:
                        page_texts[i] = f"{page_texts[i]}\n\n[Table]\n{rendered}"
    except Exception:
        pass
    return page_texts


def _render_table(rows):
    """rows: pdfplumber's raw table, a list of rows each a list of cell
    strings (or None for an empty cell). Rendered one row per line,
    cells pipe-separated, so the grid survives as plain text a chunker
    and embedder can still handle -- no markdown table syntax, since
    nothing downstream renders markdown."""
    lines = []
    for row in rows:
        cells = [(cell or "").strip() for cell in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


# A page pypdf came back with only a stray character or two on (a lone
# page number, a watermark) still counts as "has text" by a truthiness
# check, but there's nothing on it worth retrieving -- anything under this
# is treated as image-only and sent through OCR instead.
_BLANK_PAGE_CHAR_THRESHOLD = 20


def _ocr_blank_pages(raw_bytes, pages):
    """OCR only the pages pypdf came back near-empty on, not the whole
    document.

    The old version only OCR'd anything if *every* page had zero text --
    fine for a fully scanned PDF, but it meant a normal 40-page PDF with a
    handful of scanned or diagram-only pages mixed in silently lost just
    those pages: the document as a whole had plenty of text, so the
    all-or-nothing check never triggered OCR for them. Checking page by
    page instead means both cases end up handled by the same path: a
    fully scanned PDF has every page under the threshold and gets OCR'd
    in full (the old behaviour), a mixed one only pays the OCR cost for
    the pages that actually need it.
    """
    blank_indices = [
        i for i, text in enumerate(pages) if len(text.strip()) < _BLANK_PAGE_CHAR_THRESHOLD
    ]
    if not blank_indices:
        return pages

    import fitz  # PyMuPDF; deferred: only needed once OCR is actually required
    import pytesseract
    from PIL import Image

    try:
        with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
            for i in blank_indices:
                if i >= len(doc):
                    continue
                # 300 DPI: default (72 DPI) render is too low-res for
                # tesseract to read reliably.
                pixmap = doc[i].get_pixmap(dpi=300)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                ocr_text = pytesseract.image_to_string(image).strip()
                if ocr_text:
                    pages[i] = ocr_text
    except Exception:
        # OCR is best-effort recovery for otherwise-blank pages -- a
        # malformed PDF that trips PyMuPDF shouldn't take down the pages
        # that already extracted fine via pypdf.
        pass
    return pages


def _extract_docx(raw_bytes):
    import docx  # deferred: only needed once a .docx is actually uploaded

    document = docx.Document(io.BytesIO(raw_bytes))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_image(raw_bytes):
    import pytesseract  # deferred: only needed once an image is actually uploaded
    from PIL import Image

    image = Image.open(io.BytesIO(raw_bytes))
    text = pytesseract.image_to_string(image).strip()
    if not text:
        raise UnsupportedFileType(
            "Could not detect any text in this image — OCR found nothing to index."
        )
    return text
