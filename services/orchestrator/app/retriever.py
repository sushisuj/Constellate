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

from dataclasses import dataclass, field

from . import config
from .store import chunk_from_result
from .textutil import content_words


@dataclass
class Candidate:
    chunk: object
    similarity: float   # cosine similarity from Chroma
    overlap: float      # share of the question's content words found in this chunk
    boost: float        # topic (in practice: same-document) continuity bonus
    score: float


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
                Candidate(chunk=chunk, similarity=similarity, overlap=overlap, boost=boost, score=score)
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates, search_text, was_followup
