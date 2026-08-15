"""Retrieval and re-ranking -- deliberately no scope gate.

Adapted from the Chatbot project's src/retriever.py, which decides
in_scope() before ever searching and can refuse a question outright
(REFUSE) or hedge it (HEDGE) based on calibrated thresholds tuned against
a labelled question set for one specific handbook. That gate exists to
serve "quote verbatim, never compose" -- a trust promise specific to a
single, curated corpus. Constellate has neither: it composes an answer
from arbitrary user-uploaded documents, and has no labelled question set
to calibrate a gate against even if it wanted one.

So this version always searches and always returns ranked candidates --
the "is this actually in the document" judgment is delegated to the LLM's
own prompt instruction (see llm.py: "if the context does not contain the
answer, say so plainly rather than guessing") rather than a pre-generation
numeric threshold. What's kept from the original: the similarity + lexical
overlap + topic-continuity scoring, because that's what makes the top
candidates actually good, independent of whether there's a refuse/hedge
decision layered on top.
"""

import re
from dataclasses import dataclass, field

from . import config
from .store import chunk_from_result
from .textutil import content_words

# Chunk ids end in a zero-padded index assigned in document order (see
# chunker.py: "{topic}--{NNN}"), so this recovers original document order
# by position even across a heading change, where the topic-slug prefix
# differs from one chunk to the next but the running index doesn't.
_CHUNK_INDEX_RE = re.compile(r"--(\d+)$")


@dataclass
class Candidate:
    chunk: object
    similarity: float   # cosine similarity from Chroma
    overlap: float      # share of the question's content words found in this chunk
    boost: float        # topic (in practice: same-document) continuity bonus
    score: float
    # Which Retriever this candidate came from -- not part of its identity
    # or its score, just plumbing so assistant.py can ask the right
    # document's collection for this chunk's neighbors without having to
    # re-derive which upload a chunk belongs to from its text/source label.
    source_retriever: object = None


@dataclass
class Result:
    question: str
    search_text: str
    was_followup: bool
    candidates: list = field(default_factory=list)

    @property
    def best(self):
        return self.candidates[0] if self.candidates else None

    @property
    def related(self):
        """Near-miss sections worth pointing at, restricted to the winner's
        own topic (in practice: the same uploaded document) -- a result
        from a different document reads as noise, however close the score.
        """
        if not self.candidates:
            return []
        winner = self.candidates[0]
        out = []
        for cand in self.candidates[1:]:
            if cand.chunk.topic != winner.chunk.topic:
                continue
            if winner.score - cand.score <= config.RELATED_MARGIN:
                out.append(cand)
            if len(out) >= config.MAX_RELATED:
                break
        return out


class Retriever:
    def __init__(self, chroma_dir, collection_name):
        from .store import get_collection

        self.collection = get_collection(chroma_dir, collection_name)
        self._ordered_ids = self._load_ordered_ids()

    def _load_ordered_ids(self):
        """This document's chunk ids, sorted back into original document
        order -- lets neighbor_ids() work by position instead of trying to
        parse and compare topic-slug prefixes, which change from chunk to
        chunk in a heading-structured document."""
        try:
            all_ids = self.collection.get(include=[])["ids"]
        except Exception:
            return []

        def index_of(chunk_id):
            match = _CHUNK_INDEX_RE.search(chunk_id)
            return int(match.group(1)) if match else 0

        return sorted(all_ids, key=index_of)

    def neighbor_ids(self, chunk_id, radius=1):
        """Ids of the `radius` chunks immediately before and after
        chunk_id in document order. Empty if chunk_id isn't in this
        document (e.g. it came from a different upload)."""
        if chunk_id not in self._ordered_ids:
            return []
        pos = self._ordered_ids.index(chunk_id)
        lo = max(0, pos - radius)
        hi = min(len(self._ordered_ids), pos + radius + 1)
        return [cid for cid in self._ordered_ids[lo:hi] if cid != chunk_id]

    def fetch_chunks(self, chunk_ids):
        """Look up specific chunks by id, e.g. the neighbors neighbor_ids()
        just named. Returns whatever Chroma actually has for those ids,
        in no particular order -- callers that care about order (none do
        yet) should sort the result themselves."""
        if not chunk_ids:
            return []
        raw = self.collection.get(ids=chunk_ids, include=["documents", "metadatas"])
        return [
            chunk_from_result(doc, meta, cid)
            for doc, meta, cid in zip(raw["documents"], raw["metadatas"], raw["ids"])
        ]

    def chunk_overlap(self, question, chunk):
        """Fraction of the question's content words that occur in this
        one chunk's own text (body + section + topic heading). Not a gate
        -- just one term in the ranking score below."""
        words = content_words(question)
        if not words:
            return 0.0
        chunk_vocab = set(content_words(chunk.text))
        chunk_vocab.update(content_words(chunk.section))
        chunk_vocab.update(content_words(chunk.topic_label))
        hits = sum(1 for w in words if w in chunk_vocab)
        return hits / len(words)

    def rank(self, question, memory=None):
        """Search this document's index and score candidates. Always
        searches -- no scope gate, no empty-candidates-means-refuse path.
        See module docstring.

        Returns (candidates, search_text, was_followup).
        """
        search_text, preferred_topic = (
            memory.resolve(question) if memory else (question, None)
        )
        was_followup = search_text != question

        raw = self.collection.query(
            query_texts=[search_text],
            n_results=config.TOP_K,
            include=["documents", "metadatas", "distances"],
        )
        docs = raw["documents"][0]
        metas = raw["metadatas"][0]
        dists = raw["distances"][0]
        ids = raw["ids"][0]

        candidates = []
        for doc, meta, dist, cid in zip(docs, metas, dists, ids):
            chunk = chunk_from_result(doc, meta, cid)
            similarity = 1.0 - dist
            overlap = self.chunk_overlap(question, chunk)
            boost = (
                config.TOPIC_BOOST
                if preferred_topic and chunk.topic == preferred_topic
                else 0.0
            )
            score = similarity + config.LEXICAL_WEIGHT * overlap + boost
            candidates.append(
                Candidate(
                    chunk=chunk,
                    similarity=similarity,
                    overlap=overlap,
                    boost=boost,
                    score=score,
                    source_retriever=self,
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates, search_text, was_followup
