"""Tests for retriever.py's neighbor-lookup additions -- pulling a winning
chunk's immediate document-neighbors into the generation context so a fact
split across a chunk boundary isn't lost just because only one side of it
scored well on its own (see assistant.py's _expand_with_neighbors).

Uses a fake, offline embedding function instead of chromadb's real ONNX
MiniLM one. Semantic similarity isn't what's under test here -- only
whether neighbor_ids()/fetch_chunks() find the right chunks by position --
and the real embedding function needs a one-time model download that
isn't available in every environment this suite might run in.
"""

import hashlib

import pytest

from app import store as store_module


class _FakeEmbeddingFn:
    """Deterministic, offline stand-in for chromadb's default embedding
    function: hashes each string into a short vector. Not semantically
    meaningful -- just enough for chromadb's add()/query() machinery to
    run without reaching the network for the real model."""

    def __call__(self, input):
        return [[b / 255.0 for b in hashlib.sha256(text.encode()).digest()[:8]] for text in input]

    def embed_query(self, input):
        return self(input)

    def name(self):
        return "fake"


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(store_module, "_embedding_fn", lambda: _FakeEmbeddingFn())


# Long enough that chunk_fixed_size() (see chunker.py) splits it into
# several 800-character parts -- short text would just come back as one
# chunk, which is useless for testing neighbor relationships.
LONG_TEXT = (
    ("The warranty term is defined here as thirty six months from purchase date. " * 15)
    + ("Filler content to push length further along in the document text body. " * 20)
    + "As described above, the warranty term governs all claims made after delivery."
)


def _build_retriever(tmp_path, text, title="Warranty Policy"):
    from app.chunker import chunk_text
    from app.retriever import Retriever

    chunks = chunk_text(text, title)
    store_module.build_index(chunks, tmp_path, "doc", source_label=title)
    return Retriever(tmp_path, "doc"), chunks


class TestNeighborLookup:
    def test_ordered_ids_match_document_order(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, LONG_TEXT)
        assert retriever._ordered_ids == [c.id for c in chunks]
        assert len(chunks) >= 3  # otherwise the tests below aren't testing anything real

    def test_first_chunk_has_only_a_next_neighbor(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, LONG_TEXT)
        assert retriever.neighbor_ids(chunks[0].id) == [chunks[1].id]

    def test_last_chunk_has_only_a_previous_neighbor(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, LONG_TEXT)
        assert retriever.neighbor_ids(chunks[-1].id) == [chunks[-2].id]

    def test_middle_chunk_has_both_neighbors(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, LONG_TEXT)
        assert set(retriever.neighbor_ids(chunks[1].id)) == {chunks[0].id, chunks[2].id}

    def test_unknown_chunk_id_has_no_neighbors(self, tmp_path):
        retriever, _ = _build_retriever(tmp_path, LONG_TEXT)
        assert retriever.neighbor_ids("not-a-real-id--999") == []

    def test_fetch_chunks_returns_matching_content(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, LONG_TEXT)
        fetched = retriever.fetch_chunks([chunks[2].id])
        assert len(fetched) == 1
        assert fetched[0].id == chunks[2].id
        assert fetched[0].text == chunks[2].text

    def test_fetch_chunks_empty_list_returns_empty(self, tmp_path):
        retriever, _ = _build_retriever(tmp_path, LONG_TEXT)
        assert retriever.fetch_chunks([]) == []


class TestAssistantNeighborExpansion:
    """Integration check: Assistant.ask() actually wires neighbor
    expansion in, not just Retriever having the methods in isolation."""

    def test_winner_neighbors_ride_along_into_generation_context(self, tmp_path, monkeypatch):
        from app import config

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        # Force exactly one chunk to win on score alone, so any extra
        # source in the reply can only have come from neighbor expansion.
        monkeypatch.setattr(config, "GENERATION_TOP_K", 1)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

        from app.assistant import Assistant

        assistant = Assistant()
        assistant.upload_document(LONG_TEXT, "warranty.txt")
        reply = assistant.ask("What does the warranty term say?")

        assert reply.backend == "stub"
        assert len(reply.sources) >= 2
