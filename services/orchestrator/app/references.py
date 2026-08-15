"""Detects when a chunk of retrieved text depends on something defined
elsewhere in the same document -- "as described above," "see Section 3,"
"the aforementioned policy" -- and turns each one into a search query that
can find the chunk actually being pointed at.

Rule-based, not a second LLM call, for the same reasoning guardrails.py
documents for its own checks: this only has to recognise a handful of
common referring phrases, not parse English, and it runs on every answer,
so it needs to be instant and free.

This is the second half of "preserve long-range context" inside one
document. The first half (assistant.py's _expand_with_neighbors) handles a
fact split across an *adjacent* chunk boundary. This handles a chunk that
explicitly points at something defined many chunks away -- a term defined
on page 3, used on page 40 -- which neighbor expansion can't reach because
page 3 and page 40 aren't neighbors.
"""

import re

from .textutil import content_words

# Deliberately broad phrasing, not grammar-aware -- catches the common
# ways a document points back at itself without trying to actually parse
# the sentence around it.
_REFERENCE_PATTERNS = [
    re.compile(
        r"as (?:defined|described|mentioned|stated|noted|discussed|outlined) "
        r"(?:above|earlier|previously)",
        re.I,
    ),
    re.compile(r"the aforementioned", re.I),
    re.compile(
        r"as (?:defined|described|mentioned|stated|noted|discussed|outlined) "
        r"in (?:the )?(?:section|part|chapter|appendix)(?:\s+\S+)?",
        re.I,
    ),
    re.compile(r"see (?:section|part|chapter|appendix)\s+\S+", re.I),
]

# How far to look for a query around a match, and how much of that to
# keep. Deliberately NOT sentence-splitting first: a chunk is a fixed-size
# character window (see chunker.py), so the text right before or after a
# match is very often a fragment of a sentence that actually started or
# ends in a *different* chunk -- there may be no sentence-ending
# punctuation nearby at all. Clipping a bounded window instead of trying
# to find "the sentence" avoids pulling in an entire chunk's worth of
# unrelated text as the query when that happens.
_MAX_QUERY_CHARS = 200

# Below this many content words, whatever text got clipped isn't enough to
# search on -- querying with it would just return the overall top-scoring
# chunk regardless of relevance, not something the reference actually
# pointed at.
_MIN_QUERY_CONTENT_WORDS = 2


def _clip_after(text):
    clipped = text[:_MAX_QUERY_CHARS]
    end = re.search(r"[.!?]", clipped)
    if end:
        clipped = clipped[: end.start()]
    return clipped.strip(" ,.:;")


def _clip_before(text):
    clipped = text[-_MAX_QUERY_CHARS:]
    last_boundary = None
    for boundary in re.finditer(r"[.!?]\s", clipped):
        last_boundary = boundary.end()
    if last_boundary is not None:
        clipped = clipped[last_boundary:]
    return clipped.strip(" ,.:;")


def find_reference_queries(text, max_queries):
    """One search query per back-reference found in `text`, up to
    max_queries, in the order they appear.

    For each match, the query is a bounded snippet of text right after
    the reference ("as described above, the warranty term governs all
    claims" -> query "the warranty term governs all claims") -- that's
    usually where the referring phrase's actual subject shows up. If
    there's nothing usable after it (the reference sits at the very end
    of the chunk), the snippet immediately before it is used instead.
    """
    matches = []
    for pattern in _REFERENCE_PATTERNS:
        matches.extend(pattern.finditer(text))
    matches.sort(key=lambda m: m.start())

    queries = []
    for match in matches:
        if len(queries) >= max_queries:
            break
        candidate = _clip_after(text[match.end() :])
        if len(content_words(candidate)) < _MIN_QUERY_CONTENT_WORDS:
            candidate = _clip_before(text[: match.start()])
        if len(content_words(candidate)) >= _MIN_QUERY_CONTENT_WORDS:
            queries.append(candidate)
    return queries
