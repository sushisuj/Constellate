"""The whole pipeline behind one call: Assistant.ask(question) -> Reply.

Adapted from the Chatbot project's src/assistant.py, specifically the
generate() half of it -- Constellate has no quote-only ask() pipeline and
no skills (remember-your-name, arithmetic, fun facts are Northgate-flavor
extras, not "document search and explain"). What's kept: retrieval merged
across every uploaded document, memory-aware follow-up handling, and
handing the winning candidates to an LLM to compose a cited answer.

Every uploaded document gets its own ephemeral Chroma collection in its
own temp directory (see upload_document) -- same pattern as Chatbot's
Assistant.upload_document(), and for the same reason: no persistent
cross-session store means no risk of one conversation's uploads leaking
into another's answers. This mirrors Chatbot's actual scope (a single
shared instance per running process, not real multi-tenancy) rather than
attempting to solve session isolation as part of this port.
"""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config, llm
from .chunker import chunk_text, humanize_filename
from .memory import Memory
from .retriever import Retriever
from .store import build_index
from .textutil import content_words

# How many distinct keywords to hand back per upload for the frontend's
# decorative constellation labels (see GraphPanel in App.jsx) -- plenty for
# a handful of random picks per redraw without the response getting large.
MAX_KEYWORDS = 60


def _extract_keywords(chunks):
    words = set()
    for chunk in chunks:
        for word in content_words(chunk.text):
            if word.isalpha() and len(word) >= 4:
                words.add(word)
    return list(words)[:MAX_KEYWORDS]


@dataclass
class Reply:
    message: str = ""            # the composed answer
    sources: list = field(default_factory=list)   # [{"source", "citation"}, ...]
    related: list = field(default_factory=list)   # citations of near-miss chunks
    backend: str = ""            # "llm" or "stub" -- see llm.py


@dataclass
class UploadedDoc:
    filename: str
    chunks: int
    topics: list
    retriever: object             # Retriever -- internal, never serialized
    tmpdir: object                 # TemporaryDirectory -- kept alive as long as this is
    keywords: list = field(default_factory=list)  # for the frontend's decorative labels only

    def summary(self):
        return {
            "filename": self.filename,
            "chunks": self.chunks,
            "topics": self.topics,
            "keywords": self.keywords,
        }


REFUSAL = (
    "Nothing has been uploaded yet, so there's no document to answer from. "
    "Upload a document first."
)


class Assistant:
    def __init__(self):
        self.memory = Memory()
        self._uploads = []

    # -- uploads --------------------------------------------------------

    def upload_document(self, text, filename):
        """Index one uploaded document into its own ephemeral collection.
        Added to the list of uploads rather than replacing any already
        there, so multiple documents accumulate across a conversation.
        """
        title = humanize_filename(Path(filename))
        chunks = chunk_text(text, title)

        tmpdir = tempfile.TemporaryDirectory()
        chroma_dir = Path(tmpdir.name) / "chroma"
        collection_name = "doc"
        build_index(chunks, chroma_dir, collection_name, source_label=title)

        retriever = Retriever(chroma_dir, collection_name)
        topics = sorted({c.topic_label for c in chunks})
        keywords = _extract_keywords(chunks)
        doc = UploadedDoc(
            filename=filename,
            chunks=len(chunks),
            topics=topics,
            retriever=retriever,
            tmpdir=tmpdir,
            keywords=keywords,
        )
        self._uploads.append(doc)
        return doc.summary()

    def list_uploads(self):
        return [doc.summary() for doc in self._uploads]

    def remove_upload(self, filename):
        for i, doc in enumerate(self._uploads):
            if doc.filename == filename:
                del self._uploads[i]
                return True
        return False

    def clear_uploads(self):
        self._uploads = []

    # -- pipeline ---------------------------------------------------------

    def ask(self, question):
        """Retrieval merged across every uploaded document, ranked
        together, top candidates handed to the LLM. No scope gate -- see
        retriever.py's module docstring -- so this always attempts an
        answer once at least one document is uploaded; grounding is
        enforced by the prompt instruction in llm.py, not a pre-generation
        threshold.
        """
        if not self._uploads:
            return Reply(message=REFUSAL)

        candidates = []
        search_text = question
        was_followup = False
        for doc in self._uploads:
            doc_candidates, doc_search_text, doc_was_followup = doc.retriever.rank(question, self.memory)
            candidates.extend(doc_candidates)
            # Every doc resolves the same question against the same
            # memory, so these are identical across docs -- just keep one.
            search_text, was_followup = doc_search_text, doc_was_followup
        candidates.sort(key=lambda c: c.score, reverse=True)

        top_candidates = candidates[: config.GENERATION_TOP_K]
        top_chunks = [c.chunk for c in top_candidates]
        answer, backend = llm.generate(question, top_chunks)

        best = top_candidates[0]
        self.memory.record(question, best.chunk.topic, best.chunk.section)

        related = []
        seen = set()
        for cand in candidates[len(top_candidates):]:
            if cand.chunk.topic != best.chunk.topic:
                continue
            if best.score - cand.score > config.RELATED_MARGIN:
                continue
            if cand.chunk.citation in seen:
                continue
            seen.add(cand.chunk.citation)
            related.append(cand.chunk.citation)
            if len(related) >= config.MAX_RELATED:
                break

        return Reply(
            message=answer,
            sources=[{"source": c.source, "citation": c.citation} for c in top_chunks],
            related=related,
            backend=backend,
        )

    # -- session controls ---------------------------------------------------

    def reset_conversation(self):
        self.memory.clear()
