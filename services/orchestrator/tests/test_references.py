"""Tests for references.py's find_reference_queries -- pure text
processing, no chromadb involved, so these run without any embedding
function at all (fake or real).
"""

from app.references import find_reference_queries


class TestFindReferenceQueries:
    def test_finds_query_after_an_above_style_reference(self):
        text = (
            "This page covers claims processing. As described above, the warranty "
            "term governs all claims made after delivery. Nothing else to note."
        )
        queries = find_reference_queries(text, max_queries=2)
        assert queries == ["the warranty term governs all claims made after delivery"]

    def test_finds_multiple_references_in_order(self):
        text = (
            "As described above, the warranty term governs all claims made after "
            "delivery. See Section 3 for the refund exceptions."
        )
        queries = find_reference_queries(text, max_queries=2)
        assert queries == [
            "the warranty term governs all claims made after delivery",
            "for the refund exceptions",
        ]

    def test_respects_max_queries(self):
        text = (
            "As described above, term one applies here. See Section 3 for term two. "
            "The aforementioned term three also applies in this case."
        )
        queries = find_reference_queries(text, max_queries=1)
        assert len(queries) == 1

    def test_no_reference_phrase_returns_nothing(self):
        text = "This is a completely ordinary sentence with no back-references in it."
        assert find_reference_queries(text, max_queries=2) == []

    def test_reference_with_nothing_useful_after_it_falls_back_to_before(self):
        # The reference sits right at the end -- nothing meaningful comes
        # after it, so the snippet before the reference should be used.
        text = "The refund window is thirty days from the purchase date, as noted above."
        queries = find_reference_queries(text, max_queries=2)
        assert queries
        assert "refund window" in queries[0] or "thirty days" in queries[0]

    def test_reference_at_start_of_a_chunk_still_finds_a_query(self):
        # Mirrors a real chunk boundary: the chunk starts mid-sentence,
        # with the reference near the very beginning and nothing coherent
        # before it (see the module docstring for why this matters).
        text = (
            "filler filler filler filler as described above, the warranty term "
            "governs all claims made after delivery, and this section explains "
            "the claims process in detail for support staff handling customer calls."
        )
        queries = find_reference_queries(text, max_queries=2)
        assert queries
        assert "warranty term governs" in queries[0]

    def test_short_remainder_is_skipped(self):
        # Only one content word left after stripping the reference phrase
        # and nothing usable before it either -- shouldn't produce a query
        # that's really just noise.
        text = "As noted above, ok."
        assert find_reference_queries(text, max_queries=2) == []
