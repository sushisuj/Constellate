"""Detects which pages of a PDF are likely diagrams or flowcharts, as
opposed to a page of plain text or a scanned photo -- the first step
toward extracting diagram structure (see docs/backend.rst).

Rule-based on purpose: this only has to flag *candidate* pages cheaply.
The actual understanding of what's on a flagged page is a separate,
vision-model extraction step that comes later -- that's the part that
actually costs latency and money (see the project's own lessons-learnt
on why a per-page model call needs to be earned, not assumed). Getting
this detection step wrong toward "flags too many pages" just wastes one
vision call on a page that turns out not to be a diagram; getting it
wrong the other way loses a diagram's structure entirely. So it leans
permissive, not precise.
"""

# A real vector-drawn flowchart or diagram is built from several closed
# shapes -- boxes, mostly -- connected by lines. A page of plain text has
# essentially no closed shapes at all. The tempting first version of this
# counted *any* drawing primitive, but that misfires badly on tables: a
# reportlab-style grid table with borders turns out to produce a dozen-plus
# separate line-drawing objects (one per grid line) with zero rectangles --
# see the git history on this file for the false positive that caused.
# Counting rectangle shapes specifically is what actually tells "a handful
# of boxes" apart from "a grid of lines."
MIN_SHAPE_COUNT = 3

# A single raster image covering most of the page is much more likely a
# scanned photo or screenshot than a vector-drawn diagram -- those are
# already handled by extract.py's per-page OCR fallback, not by diagram
# structure extraction, so a page dominated by one big image is excluded
# here even if it happens to also contain a few stray vector shapes.
LARGE_IMAGE_COVERAGE_THRESHOLD = 0.8


def _is_closed_shape(drawing):
    """True if this PyMuPDF drawing includes an explicit rectangle
    primitive -- what a diagram's boxes/nodes are actually drawn as, as
    opposed to a table's borders, which are typically plain line ('l')
    segments even though there can be a lot of them (see MIN_SHAPE_COUNT
    above for why line count alone isn't a reliable signal)."""
    return any(item[0] == "re" for item in drawing.get("items", []))


def is_diagram_page(page):
    """page: a PyMuPDF (fitz) Page object.

    True if the page looks like a vector-drawn diagram: enough discrete
    box-like shapes to plausibly be nodes, and not dominated by one large
    raster image (more likely a scan or photo).
    """
    shape_count = sum(1 for d in page.get_drawings() if _is_closed_shape(d))
    if shape_count < MIN_SHAPE_COUNT:
        return False

    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return True

    for img in page.get_images(full=True):
        try:
            bbox = page.get_image_bbox(img)
        except ValueError:
            # Image is referenced but not actually placed on this page
            # (can happen with a shared image resource) -- not a factor
            # in whether this page looks like a diagram.
            continue
        coverage = (bbox.width * bbox.height) / page_area
        if coverage >= LARGE_IMAGE_COVERAGE_THRESHOLD:
            return False

    return True


def find_diagram_pages(raw_bytes):
    """Indices of pages in this PDF (0-based) that look like diagrams."""
    import fitz  # PyMuPDF; deferred: only needed once a .pdf is actually uploaded

    pages = []
    with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if is_diagram_page(page):
                pages.append(i)
    return pages
