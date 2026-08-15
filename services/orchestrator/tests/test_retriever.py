"""Tests for retriever.py's two long-range-context additions:

- Neighbor lookup (neighbor_ids/fetch_chunks), which pulls a winning
  chunk's immediate document-neighbors into the generation context so a
  fact split across a chunk boundary isn't lost just because only one
  side of it scored well on its own. See assistant.py's
  _expand_with_neighbors.
- best_match(), which resolves an explicit in-document reference ("as
  described above") to the distant chunk it's actually pointing at. See
  references.py and assistant.py's _expand_with_references.

Uses a fake, offline embedding function instead of chromadb's real ONNX
MiniLM one -- the real one needs a one-time model download that isn't
available in every environment this suite might run in. The fake is
lexical (a hashed bag-of-content-words vector), not random, because
best_match()'s tests need cosine similarity to actually reflect which
chunk shares vocabulary with the query -- a purely random fake would make
those tests flaky.
"""

import hashlib

import pytest

from app import store as store_module
from app.textutil import content_words

_VECTOR_DIM = 64


class _LexicalFakeEmbeddingFn:
    """Deterministic, offline stand-in for chromadb's default embedding
    function. Each text becomes a fixed-length vector by hashing its
    content words into buckets (the "hashing trick") -- not a real
    semantic embedding, but two texts that share vocabulary end up with
    genuinely higher cosine similarity than two that don't, which is
    enough to make best_match()'s tests meaningful without downloading
    the real model.
    """

    def __call__(self, input):
        return [self._vector(text) for text in input]

    def embed_query(self, input):
        return self(input)

    def name(self):
        return "fake-lexical"

    def _vector(self, text):
        vec = [0.0] * _VECTOR_DIM
        for word in content_words(text):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _VECTOR_DIM
            vec[bucket] += 1.0
        return vec


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(store_module, "_embedding_fn", lambda: _LexicalFakeEmbeddingFn())


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


def _distant_reference_text():
    """A document where a definition and the chunk that refers back to it
    ("as described above") land several chunks apart -- not adjacent --
    so it actually exercises reference-following rather than something
    neighbor expansion would already cover. Each "part" is padded with
    unique filler so chunk_fixed_size() (800 chars, see chunker.py) keeps
    it from getting merged together with its neighbors.
    """

    def part(sentence, filler_word, repeat=25):
        return sentence + " " + ((filler_word + " ") * repeat)

    definition = part(
        "The warranty term is defined here as thirty six months from the purchase "
        "date, and customers may file a claim for any defect reported within this "
        "period under company policy.",
        "fillerpartone",
    )
    filler_a = part(
        "Shipping logistics involve coordinating carriers and tracking numbers and "
        "delivery windows across multiple regional warehouses for every order "
        "placed by a customer.",
        "fillerparttwo",
    )
    filler_b = part(
        "Packaging materials are selected based on fragility ratings and average "
        "transit distance to minimize damage during handling and transport "
        "between warehouses.",
        "fillerpartthree",
    )
    reference = part(
        "As described above, the warranty term governs all claims made after "
        "delivery, and this section explains the claims process in detail for "
        "support staff handling customer calls.",
        "fillerpartfour",
    )
    return "\n\n".join([definition, filler_a, filler_b, reference])


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


class TestBestMatch:
    def test_finds_the_chunk_a_reference_actually_points_at(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, _distant_reference_text())
        definition = next(c for c in chunks if "defined here as thirty six months" in c.text)
        reference = next(c for c in chunks if "As described above" in c.text)
        # Sanity-check the fixture itself: definition and reference have
        # to be non-adjacent, otherwise this test wouldn't be proving
        # anything beyond what neighbor lookup already covers.
        assert definition.id not in retriever.neighbor_ids(reference.id)

        match = retriever.best_match(
            "the warranty term governs all claims made after delivery",
            exclude_ids={reference.id},
        )
        assert match is not None
        assert match.chunk.id == definition.id

    def test_excluded_ids_are_never_returned(self, tmp_path):
        retriever, chunks = _build_retriever(tmp_path, _distant_reference_text())
        all_ids = {c.id for c in chunks}
        match = retriever.best_match("warranty term claims", exclude_ids=all_ids)
        assert match is None

    def test_min_score_filters_out_weak_matches(self, tmp_path):
        retriever, _ = _build_retriever(tmp_path, _distant_reference_text())
        match = retriever.best_match("warranty term claims", exclude_ids=set(), min_score=1000.0)
        assert match is None


class TestAssistantReferenceExpansion:
    """Integration check: Assistant.ask() actually follows a reference in
    the winning chunk to the distant chunk it points at, not just
    Retriever having best_match() in isolation."""

    def test_reference_pulls_in_the_distant_definition_chunk(self, tmp_path, monkeypatch):
        from pathlib import Path

        from app import config
        from app.chunker import chunk_text, humanize_filename

        monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path)
        # Force exactly one chunk to win on score alone.
        monkeypatch.setattr(config, "GENERATION_TOP_K", 1)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

        text = _distant_reference_text()
        # Same title Assistant.upload_document() derives internally from
        # the filename, so this chunk's .citation matches what actually
        # comes back in the reply.
        title = humanize_filename(Path("warranty.txt"))
        definition = next(c for c in chunk_text(text, title) if "defined here as thirty six months" in c.text)

        from app.assistant import Assistant

        assistant = Assistant()
        assistant.upload_document(text, "warranty.txt")
        # Vocabulary chosen to overlap heavily with the reference chunk
        # specifically, so it -- not the definition chunk -- wins first;
        # the definition should only show up via reference-following.
        reply = assistant.ask(
            "What does the section on claims explain to support staff handling customer calls?"
        )

        citations = {s["citation"] for s in reply.sources}
        assert definition.citation in citations
