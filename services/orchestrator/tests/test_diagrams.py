"""Tests for diagrams.py's diagram-page detection -- telling a genuine
vector-drawn flowchart apart from a plain text page, a scanned photo, or
a table, so only real diagram pages get sent through the (expensive)
vision-model extraction step that comes later.

PDF fixtures are built with reportlab at test time, same approach as
test_extract.py: no binary fixtures in git, and what each test PDF
actually contains is readable directly from the test.
"""

import io

import fitz

from app.diagrams import find_diagram_pages, is_diagram_page


def _first_page_is_diagram(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return is_diagram_page(doc[0])


def _pdf_with_flowchart(num_boxes=5):
    """A handful of boxes connected by lines -- the vector-drawing shape
    a real flowchart/diagram takes."""
    from reportlab.pdfgen import canvas

    boxes = [
        (100, 700, 200, 730),
        (100, 600, 200, 630),
        (100, 500, 200, 530),
        (300, 650, 400, 680),
        (300, 550, 400, 580),
    ][:num_boxes]

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for x1, y1, x2, y2 in boxes:
        c.rect(x1, y1, x2 - x1, y2 - y1)
    c.line(150, 700, 150, 630)
    c.line(150, 600, 150, 530)
    c.save()
    return buf.getvalue()


def _pdf_with_plain_text():
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "This is a completely plain text page.")
    c.drawString(100, 680, "No boxes, no arrows, nothing vector-drawn here.")
    c.save()
    return buf.getvalue()


def _pdf_with_large_photo():
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (600, 800), "gray")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawImage(ImageReader(img_buf), 50, 20, width=500, height=750)
    c.save()
    return buf.getvalue()


def _pdf_with_table(rows=5, cols=4):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    data = [[f"r{i}c{j}" for j in range(cols)] for i in range(rows)]
    table = Table(data)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    doc.build([table])
    return buf.getvalue()


class TestIsDiagramPage:
    def test_flowchart_is_detected(self):
        assert _first_page_is_diagram(_pdf_with_flowchart()) is True

    def test_plain_text_is_not_a_diagram(self):
        assert _first_page_is_diagram(_pdf_with_plain_text()) is False

    def test_large_photo_is_not_a_diagram(self):
        assert _first_page_is_diagram(_pdf_with_large_photo()) is False

    def test_a_couple_of_boxes_is_not_enough(self):
        # Below MIN_SHAPE_COUNT -- a stray callout box or two in body text
        # shouldn't be enough to call the page a diagram.
        assert _first_page_is_diagram(_pdf_with_flowchart(num_boxes=2)) is False

    def test_small_table_is_not_a_diagram(self):
        assert _first_page_is_diagram(_pdf_with_table(rows=5, cols=4)) is False

    def test_large_table_is_not_a_diagram(self):
        # A bigger grid produces more line-drawing objects, not more
        # rectangles -- the whole reason MIN_SHAPE_COUNT counts
        # rectangles specifically rather than any drawing primitive (see
        # the module docstring for the false positive this replaced).
        assert _first_page_is_diagram(_pdf_with_table(rows=10, cols=6)) is False


class TestFindDiagramPages:
    def test_finds_the_right_page_in_a_mixed_document(self):
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(100, 700, "Plain text page one.")
        c.showPage()
        for x1, y1, x2, y2 in [(100, 700, 200, 730), (100, 600, 200, 630), (300, 650, 400, 680)]:
            c.rect(x1, y1, x2 - x1, y2 - y1)
        c.line(150, 700, 150, 630)
        c.showPage()
        c.save()

        assert find_diagram_pages(buf.getvalue()) == [1]

    def test_no_diagrams_returns_empty_list(self):
        assert find_diagram_pages(_pdf_with_plain_text()) == []
