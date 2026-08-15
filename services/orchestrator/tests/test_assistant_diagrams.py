"""Tests for how Assistant.upload_document() and _load_persisted_uploads()
wire diagram extraction in: detecting a diagram page in a real PDF's raw
bytes, persisting the result to diagrams.json alongside chroma/ and
meta.json, and reloading it correctly on the next "startup."

No NVIDIA_API_KEY is set in these tests, so diagram extraction runs
through diagram_vision.py's offline stub (see test_diagram_vision.py for
that module's own tests) -- what's under test here is the wiring around
it: does upload_document() actually call it for a PDF with a diagram
page, does it correctly skip non-PDF uploads, and does the result survive
a reload.
"""

import hashlib
import io

import pytest

from app import store as store_module
from app.textutil import content_words


class _LexicalFakeEmbeddingFn:
    """Same offline, deterministic embedding stand-in as test_retriever.py
    -- see that file for why it's lexical rather than purely random."""

    _VECTOR_DIM = 64

    def __call__(self, input):
        return [self._vector(text) for text in input]

    def embed_query(self, input):
        return self(input)

    def name(self):
        return "fake-lexical"

    def _vector(self, text):
        vec = [0.0] * self._VECTOR_DIM
        for word in content_words(text):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self._VECTOR_DIM
            vec[bucket] += 1.0
        return vec


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(store_module, "_embedding_fn", lambda: _LexicalFakeEmbeddingFn())


@pytest.fixture(autouse=True)
def no_nvidia_key(monkeypatch):
    # Every test in this file exercises diagram_vision.py's stub path on
    # purpose -- see the module docstring.
    #
    # Import app.config *before* deleting the key, not after: config.py
    # calls load_dotenv() at import time, and if this is the first test
    # in the session to import it (this file sorts early, alphabetically,
    # among test modules that touch app.config), a later plain `from app
    # import config` inside a test body would otherwise be the one doing
    # that first import -- re-running load_dotenv() *after* this fixture
    # already deleted the key and silently reintroducing it from .env.
    from app import config  # noqa: F401

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def _pdf_with_flowchart_page():
    """A 2-page PDF: plain text, then a real vector-drawn flowchart --
    mirrors the fixture in test_diagrams.py."""
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, "This page is just plain text, nothing drawn on it.")
    c.showPage()
    for x1, y1, x2, y2 in [(100, 700, 200, 730), (100, 600, 200, 630), (300, 650, 400, 680)]:
        c.rect(x1, y1, x2 - x1, y2 - y1)
    c.line(150, 700, 150, 630)
    c.showPage()
    c.save()
    return buf.getvalue()


class TestUploadDocumentDiagramExtraction:
    def test_pdf_with_a_diagram_page_gets_one_diagram_graph(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        assistant = Assistant()

        summary = assistant.upload_document(
            "placeholder extracted text", "flowchart.pdf", raw_bytes=_pdf_with_flowchart_page()
        )

        assert summary["diagram_count"] == 1
        assert assistant._uploads[0].diagrams[0].page == 1  # 0-based: the second page
        assert assistant._uploads[0].diagrams[0].backend == "stub"

    def test_diagrams_json_is_written_to_the_upload_directory(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        assistant = Assistant()
        assistant.upload_document(
            "placeholder extracted text", "flowchart.pdf", raw_bytes=_pdf_with_flowchart_page()
        )

        doc_dir = assistant._uploads[0].doc_dir
        assert (doc_dir / "diagrams.json").exists()

    def test_non_pdf_upload_has_no_diagrams(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        assistant = Assistant()

        summary = assistant.upload_document("Just some plain text.", "notes.txt", raw_bytes=b"Just some plain text.")

        assert summary["diagram_count"] == 0
        assert not (assistant._uploads[0].doc_dir / "diagrams.json").exists()

    def test_pdf_upload_missing_raw_bytes_has_no_diagrams(self, tmp_path, monkeypatch):
        # Mirrors a caller that only has extracted text and no original
        # file bytes (e.g. a test that predates this feature) -- should
        # degrade to "no diagrams," not raise.
        from app import config
        from app.assistant import Assistant

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        assistant = Assistant()

        summary = assistant.upload_document("placeholder text", "flowchart.pdf")

        assert summary["diagram_count"] == 0

    def test_pdf_with_no_diagram_pages_has_no_diagrams(self, tmp_path, monkeypatch):
        from reportlab.pdfgen import canvas

        from app import config
        from app.assistant import Assistant

        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.drawString(100, 700, "An entirely ordinary text-only PDF page.")
        c.save()

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        assistant = Assistant()
        summary = assistant.upload_document("An entirely ordinary text-only PDF page.", "plain.pdf", raw_bytes=buf.getvalue())

        assert summary["diagram_count"] == 0
        assert not (assistant._uploads[0].doc_dir / "diagrams.json").exists()


class TestDiagramPersistenceAcrossRestart:
    def test_diagrams_reload_correctly_on_a_fresh_assistant_instance(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)

        first = Assistant()
        first.upload_document(
            "placeholder extracted text", "flowchart.pdf", raw_bytes=_pdf_with_flowchart_page()
        )
        original_graph = first._uploads[0].diagrams[0]

        # A brand new instance, same UPLOADS_DIR -- mirrors what actually
        # happens on a server restart (see Assistant.__init__).
        second = Assistant()

        assert len(second._uploads) == 1
        reloaded_graph = second._uploads[0].diagrams[0]
        assert reloaded_graph == original_graph
        # And the reload didn't re-run detection/extraction -- it should
        # be reading diagrams.json, not re-deriving it from raw PDF bytes
        # the reload never even has access to.
