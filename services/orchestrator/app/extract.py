"""Turn uploaded file bytes into plain text, keyed off the file extension.

Ported unchanged from the Chatbot project's src/extract.py, including OCR
support for images and scanned PDFs (pytesseract + PyMuPDF) -- this is
generic file-format parsing with nothing document-app-specific in it.

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
    text = "\n\n".join(pages)
    if text.strip():
        return text
    # No embedded text layer -- most likely a scanned PDF (each page is an
    # image). Fall back to rendering every page and OCR-ing it, the same
    # path _extract_image uses for a standalone image upload.
    text = _ocr_pdf(raw_bytes)
    if not text.strip():
        raise UnsupportedFileType(
            "Could not extract any text from this PDF, even with OCR — the "
            "scan quality may be too low to read."
        )
    return text


def _ocr_pdf(raw_bytes):
    import fitz  # PyMuPDF; deferred: only needed for a scanned PDF
    import pytesseract
    from PIL import Image

    pages = []
    with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
        for page in doc:
            # 300 DPI: default (72 DPI) render is too low-res for tesseract
            # to read reliably.
            pixmap = page.get_pixmap(dpi=300)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            pages.append(pytesseract.image_to_string(image))
    return "\n\n".join(pages).strip()


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
