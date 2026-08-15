"""Tests for making diagram graphs actually retrievable -- assistant.py's
_diagram_chunks(), which flattens a DiagramGraph into a Chunk that rides
the exact same chunk/embed/retrieve pipeline as this document's text, and
the Assistant.ask() integration on top of it.

Uses the same offline, lexical fake embedding function as test_retriever.py
and test_assistant_diagrams.py, and monkeypatches diagram_vision's actual
extraction call to return a realistic graph directly -- the stub graph's
own boilerplate text ("Diagram detected, not analyzed") isn't meaningful
content to search on, so testing that retrieval finds *real* diagram
content needs a graph that actually has some.
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
    # See test_assistant_diagrams.py's own fixture for why config has to
    # be imported before the key gets deleted.
    from app import config  # noqa: F401

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def _pdf_with_flowchart_page():
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


def _approval_process_graph(page=1):
    """A realistic flowchart graph -- an approval process -- standing in
    for what a real vision extraction would return, so tests can search
    for actual content instead of the stub's generic placeholder text."""
    from app.diagram_vision import DiagramGraph, Edge, Node

    return DiagramGraph(
        page=page,
        backend="vision",
        nodes=[
            Node(id="submit", label="Submit Application"),
            Node(id="review", label="Manager Review"),
            Node(id="approved", label="Approved, funds released"),
            Node(id="rejected", label="Rejected, applicant notified"),
        ],
        edges=[
            Edge(source="submit", target="review"),
            Edge(source="review", target="approved", label="meets criteria"),
            Edge(source="review", target="rejected", label="missing documents"),
        ],
    )


class TestDiagramChunks:
    def test_graph_becomes_a_chunk_with_diagram_section_label(self):
        from app.assistant import _diagram_chunks

        chunks = _diagram_chunks([_approval_process_graph(page=2)], "Loan Policy", start_index=5)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.section == "Diagram (page 3)"  # page is 0-based, section is human-facing
        assert chunk.topic_label == "Loan Policy"
        assert "Submit Application" in chunk.text
        assert "Manager Review" in chunk.text

    def test_chunk_id_continues_the_text_chunk_numbering(self):
        from app.assistant import _diagram_chunks

        chunks = _diagram_chunks([_approval_process_graph()], "Loan Policy", start_index=5)
        assert chunks[0].id == "loan-policy--005"

    def test_multiple_graphs_get_sequential_ids(self):
        from app.assistant import _diagram_chunks

        graphs = [_approval_process_graph(page=1), _approval_process_graph(page=3)]
        chunks = _diagram_chunks(graphs, "Loan Policy", start_index=5)
        assert [c.id for c in chunks] == ["loan-policy--005", "loan-policy--006"]

    def test_graph_with_no_nodes_produces_no_chunk(self):
        from app.diagram_vision import DiagramGraph

        from app.assistant import _diagram_chunks

        empty_graph = DiagramGraph(page=0, backend="vision", nodes=[], edges=[])
        assert _diagram_chunks([empty_graph], "Loan Policy", start_index=0) == []


class TestDiagramContentIsRetrievable:
    def test_a_question_about_diagram_content_surfaces_the_diagram_citation(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant
        import app.diagram_vision as diagram_vision_module

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        # Stand in for a real vision-model response -- see module docstring.
        monkeypatch.setattr(
            diagram_vision_module, "extract_diagram_graph", lambda png, page: _approval_process_graph(page)
        )

        assistant = Assistant()
        assistant.upload_document(
            "placeholder extracted text", "loan-policy.pdf", raw_bytes=_pdf_with_flowchart_page()
        )

        reply = assistant.ask(
            "What happens after Submit Application if the review finds missing documents?"
        )

        citations = {s["citation"] for s in reply.sources}
        assert any("Diagram" in c for c in citations)

    def test_diagram_content_appears_in_the_answer_text(self, tmp_path, monkeypatch):
        from app import config
        from app.assistant import Assistant
        import app.diagram_vision as diagram_vision_module

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        monkeypatch.setattr(
            diagram_vision_module, "extract_diagram_graph", lambda png, page: _approval_process_graph(page)
        )

        assistant = Assistant()
        assistant.upload_document(
            "placeholder extracted text", "loan-policy.pdf", raw_bytes=_pdf_with_flowchart_page()
        )

        reply = assistant.ask("What happens if a loan application is missing documents during review?")

        # Offline stub backend just echoes the winning chunk's own text
        # (see llm.py's _generate_stub) -- a real generation call would
        # paraphrase instead, but this still proves the diagram's actual
        # content reached generation, not just its citation.
        assert reply.backend == "stub"
        assert "Rejected" in reply.message or "missing documents" in reply.message
