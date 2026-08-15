"""The whole pipeline behind one call: Assistant.ask(question) -> Reply.

Adapted from the Chatbot project's src/assistant.py, specifically the
generate() half of it -- Constellate has no quote-only ask() pipeline and
no skills (remember-your-name, arithmetic, fun facts are Northgate-flavor
extras, not "document search and explain"). What's kept: retrieval merged
across every uploaded document, memory-aware follow-up handling, and
handing the winning candidates to an LLM to compose a cited answer.

Every uploaded document gets its own Chroma collection in its own
directory under config.UPLOADS_DIR (see upload_document), one per
document rather than one shared collection -- so there's no risk of one
conversation's uploads leaking into another's answers. Unlike the
temp-directory version this replaced, these directories are persistent:
a small meta.json sits alongside each collection, and __init__ reloads
whatever's there on startup, so uploads survive a server restart. This
still mirrors Chatbot's actual scope (a single shared instance per
running process, not real multi-tenancy) rather than attempting to solve
session isolation as part of this port -- persistence and multi-tenancy
are separate problems, and only the first one is addressed here.
"""

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config, guardrails, llm
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
    flags: list = field(default_factory=list)      # guardrail results -- see guardrails.py


@dataclass
class UploadedDoc:
    filename: str
    chunks: int
    topics: list
    retriever: object             # Retriever -- internal, never serialized
    doc_dir: Path                  # holds chroma/ and meta.json; deleted on remove/clear
    keywords: list = field(default_factory=list)  # for the frontend's decorative labels only

    def summary(self):
        # Also what gets written to meta.json -- upload_document() dumps
        # this straight to disk so _load_persisted_uploads() can rebuild
        # everything but the retriever from it on the next startup.
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
        self._load_persisted_uploads()

    # -- uploads --------------------------------------------------------

    def _load_persisted_uploads(self):
        """Rebuild self._uploads from whatever's on disk under
        config.UPLOADS_DIR -- each subdirectory is one earlier upload's
        chroma/ collection plus the meta.json upload_document() wrote for
        it. Only the Retriever gets reconstructed; nothing gets
        re-chunked or re-embedded.
        """
        if not config.UPLOADS_DIR.exists():
            return
        for doc_dir in sorted(config.UPLOADS_DIR.iterdir()):
            meta_path = doc_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
                retriever = Retriever(doc_dir / "chroma", "doc")
            except Exception:
                # Partial/corrupt directory, e.g. the process died mid-
                # write -- skip it rather than fail the whole service.
                continue
            self._uploads.append(
                UploadedDoc(
                    filename=meta["filename"],
                    chunks=meta["chunks"],
                    topics=meta["topics"],
                    retriever=retriever,
                    doc_dir=doc_dir,
                    keywords=meta.get("keywords", []),
                )
            )

    def upload_document(self, text, filename):
        """Index one uploaded document into its own persistent collection
        under config.UPLOADS_DIR. Added to the list of uploads rather than
        replacing any already there, so multiple documents accumulate
        across a conversation.
        """
        title = humanize_filename(Path(filename))
        chunks = chunk_text(text, title)

        doc_dir = config.UPLOADS_DIR / uuid.uuid4().hex[:12]
        doc_dir.mkdir(parents=True, exist_ok=True)
        chroma_dir = doc_dir / "chroma"
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
            doc_dir=doc_dir,
            keywords=keywords,
        )
        (doc_dir / "meta.json").write_text(json.dumps(doc.summary()))
        self._uploads.append(doc)
        return doc.summary()

    def list_uploads(self):
        return [doc.summary() for doc in self._uploads]

    def remove_upload(self, filename):
        for i, doc in enumerate(self._uploads):
            if doc.filename == filename:
                shutil.rmtree(doc.doc_dir, ignore_errors=True)
                del self._uploads[i]
                return True
        return False

    def clear_uploads(self):
        for doc in self._uploads:
            shutil.rmtree(doc.doc_dir, ignore_errors=True)
        self._uploads = []

    # -- pipeline ---------------------------------------------------------

    def ask(self, question):
        """Retrieval merged across every uploaded document, ranked
        together, top candidates handed to the LLM. No scope gate -- see
        retriever.py's module docstring -- so this always attempts an
        answer once at least one document is uploaded; grounding is
        enforced by the prompt instruction in llm.py, not a pre-generation
        threshold (and re-checked afterwards, heuristically -- see below).

        Runs guardrails.check_injection() first, before retrieval or
        generation, on every question regardless of upload state -- a
        blocked question shouldn't cost an API call, or even a vector
        search.
        """
        blocked = guardrails.check_injection(question)
        if blocked:
            return Reply(
                message=(
                    "That question reads like an attempt to change my "
                    "instructions rather than ask about a document, so I'm "
                    "not going to answer it as asked. Rephrase it as a "
                    "question about what's been uploaded."
                ),
                flags=["blocked_injection"],
            )

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
        top_chunks = self._expand_with_neighbors(top_candidates, top_chunks)
        answer, backend = llm.generate(question, top_chunks)

        # Output-side guardrails -- see guardrails.py for what each of
        # these actually checks and why it's rule-based rather than a
        # second LLM call. Format enforcement can rewrite the answer
        # (stripping stray markdown); the other two only ever add flags,
        # never change what's returned.
        answer, format_flags = guardrails.enforce_format(answer)
        flags = list(format_flags)
        if guardrails.score_groundedness(answer, top_chunks) < guardrails.LOW_GROUNDEDNESS_THRESHOLD:
            flags.append("low_groundedness")
        flags.extend(f"unsafe_word:{w}" for w in guardrails.check_content_safety(answer))

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
            flags=flags,
        )

    def _expand_with_neighbors(self, top_candidates, top_chunks):
        """Pull in the winning chunk's immediate document-neighbors, so a
        fact that happens to sit right at a chunk boundary isn't lost just
        because retrieval only scored one side of it well.

        Deliberately scoped to the single top-ranked candidate, not every
        chunk in top_chunks -- expanding all of them would let the prompt
        grow unpredictably every single question. This only handles a
        fact split across *adjacent* chunks; a reference to something
        defined many chunks away (e.g. a term defined on page 3, used on
        page 40) needs the winning chunk's text to actually be followed,
        which is a separate piece of work.
        """
        if not top_candidates:
            return top_chunks

        winner = top_candidates[0]
        retriever = winner.source_retriever
        if retriever is None:
            return top_chunks

        have_ids = {c.id for c in top_chunks}
        neighbor_ids = [
            cid for cid in retriever.neighbor_ids(winner.chunk.id, radius=1) if cid not in have_ids
        ]
        if not neighbor_ids:
            return top_chunks

        return top_chunks + retriever.fetch_chunks(neighbor_ids)

    # -- session controls ---------------------------------------------------

    def reset_conversation(self):
        self.memory.clear()
