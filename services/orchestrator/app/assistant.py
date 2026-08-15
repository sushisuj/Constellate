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

from . import config, diagram_vision, diagrams, guardrails, llm, references
from .chunker import Chunk, chunk_text, humanize_filename, slugify_topic
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


def _diagram_chunks(diagram_graphs, title, start_index):
    """Turn extracted diagram graphs into Chunk objects that ride the
    same chunk/embed/retrieve pipeline as this document's text (see
    chunker.py's Chunk) -- this is what makes a diagram's content show
    up in ranking, neighbor expansion, and reference-following exactly
    like any text chunk, for free, rather than needing a second parallel
    retrieval path.

    The graph's own node/edge structure isn't lost by flattening it this
    way -- it's still sitting in doc.diagrams (see UploadedDoc), available
    for an actual relationship query later. This is only what gets
    embedded and searched.

    start_index continues the same running id counter chunk_text() used
    for this document's text chunks, so ids stay in the one numbering
    scheme retriever.py's neighbor lookup already parses (chunk ids end
    in a document-order index -- see retriever.py's _CHUNK_INDEX_RE).
    """
    topic = slugify_topic(title)
    chunks = []
    for offset, graph in enumerate(diagram_graphs):
        text = graph.to_text()
        if not text:
            # A vision extraction that ran but found nothing legible
            # (backend="vision", zero nodes) -- nothing worth indexing,
            # as opposed to the offline stub, which always has at least
            # its one honestly-labelled placeholder node.
            continue
        chunks.append(
            Chunk(
                id=f"{topic}--{start_index + offset:03d}",
                text=text,
                topic=topic,
                topic_label=title,
                section=f"Diagram (page {graph.page + 1})",
                source=title,
            )
        )
    return chunks


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
    doc_dir: Path                  # holds chroma/, meta.json, diagrams.json; deleted on remove/clear
    keywords: list = field(default_factory=list)  # for the frontend's decorative labels only
    # DiagramGraph objects extracted from this document's pages (PDFs
    # only -- see Assistant._extract_diagrams). Kept on the object itself
    # rather than only in diagrams.json so retrieval doesn't have to hit
    # disk again for something already loaded into memory.
    diagrams: list = field(default_factory=list)

    def summary(self):
        # Also what gets written to meta.json -- upload_document() dumps
        # this straight to disk so _load_persisted_uploads() can rebuild
        # everything but the retriever (and diagrams -- see
        # _load_diagrams) from it on the next startup. Only a count goes
        # here, not the full graphs -- those already have their own file
        # (diagrams.json) so this doesn't duplicate them.
        return {
            "filename": self.filename,
            "chunks": self.chunks,
            "topics": self.topics,
            "keywords": self.keywords,
            "diagram_count": len(self.diagrams),
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
        it, and diagrams.json if that upload had any. Only the Retriever
        gets reconstructed; nothing gets re-chunked, re-embedded, or
        re-sent to the vision model -- diagram extraction is exactly as
        expensive as generation, so it isn't something a routine restart
        should ever redo.
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
                diagram_graphs = self._load_diagrams(doc_dir)
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
                    diagrams=diagram_graphs,
                )
            )

    def _load_diagrams(self, doc_dir):
        diagrams_path = doc_dir / "diagrams.json"
        if not diagrams_path.exists():
            return []
        raw = json.loads(diagrams_path.read_text())
        return [diagram_vision.DiagramGraph.from_dict(d) for d in raw]

    def _extract_diagrams(self, raw_bytes, filename):
        """Detect and extract diagram graphs from a PDF upload's raw
        bytes. Non-PDF uploads (markdown, docx, a plain image) have
        nothing to scan for -- diagrams.py's page-based detection only
        makes sense for a multi-page PDF.

        Best-effort by design, same reasoning as extract.py's table
        enrichment: a malformed PDF that trips PyMuPDF's drawing
        inspection, or a page the vision model can't make sense of,
        shouldn't take down the whole upload over a feature that's
        additive on top of the text that's already been extracted.
        """
        if not raw_bytes or not filename.lower().endswith(".pdf"):
            return []
        try:
            page_indices = diagrams.find_diagram_pages(raw_bytes)
        except Exception:
            return []

        graphs = []
        for page_index in page_indices:
            try:
                png = diagrams.render_page_png(raw_bytes, page_index)
                graphs.append(diagram_vision.extract_diagram_graph(png, page_index))
            except Exception:
                continue
        return graphs

    def upload_document(self, text, filename, raw_bytes=None):
        """Index one uploaded document into its own persistent collection
        under config.UPLOADS_DIR. Added to the list of uploads rather than
        replacing any already there, so multiple documents accumulate
        across a conversation.

        raw_bytes is optional and only used for diagram extraction (see
        _extract_diagrams) -- callers that already have plain text and no
        original file bytes (e.g. tests) can omit it and simply get no
        diagrams, same as any non-PDF upload.
        """
        title = humanize_filename(Path(filename))
        text_chunks = chunk_text(text, title)
        diagram_graphs = self._extract_diagrams(raw_bytes, filename)
        diagram_chunks = _diagram_chunks(diagram_graphs, title, start_index=len(text_chunks))
        # Diagram chunks ride the exact same collection as this
        # document's text -- see _diagram_chunks' own docstring for why
        # that's what makes them retrievable, neighbor-expandable, and
        # reference-followable for free.
        all_chunks = text_chunks + diagram_chunks

        doc_dir = config.UPLOADS_DIR / uuid.uuid4().hex[:12]
        doc_dir.mkdir(parents=True, exist_ok=True)
        chroma_dir = doc_dir / "chroma"
        collection_name = "doc"
        build_index(all_chunks, chroma_dir, collection_name, source_label=title)

        retriever = Retriever(chroma_dir, collection_name)
        topics = sorted({c.topic_label for c in all_chunks})
        keywords = _extract_keywords(all_chunks)

        doc = UploadedDoc(
            filename=filename,
            chunks=len(all_chunks),
            topics=topics,
            retriever=retriever,
            doc_dir=doc_dir,
            keywords=keywords,
            diagrams=diagram_graphs,
        )
        if diagram_graphs:
            (doc_dir / "diagrams.json").write_text(
                json.dumps([d.to_dict() for d in diagram_graphs])
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
        top_chunks = self._expand_with_references(top_candidates, top_chunks)
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

    def _expand_with_references(self, top_candidates, top_chunks):
        """Follow explicit in-document references inside the winning
        chunk ("as defined above," "see Section 3") to the distant chunk
        they're actually pointing at -- the gap neighbor expansion can't
        close, since page 3 and page 40 aren't each other's neighbors.

        Scoped to the winner's own text only, same reasoning as
        _expand_with_neighbors: following references from every top
        candidate would make prompt size unpredictable turn to turn.
        """
        if not top_candidates:
            return top_chunks

        winner = top_candidates[0]
        retriever = winner.source_retriever
        if retriever is None:
            return top_chunks

        have_ids = {c.id for c in top_chunks}
        added = []
        queries = references.find_reference_queries(
            winner.chunk.text, max_queries=config.REFERENCE_MAX_QUERIES
        )
        for query in queries:
            match = retriever.best_match(
                query, exclude_ids=have_ids, min_score=config.REFERENCE_MIN_SCORE
            )
            if match is None:
                continue
            have_ids.add(match.chunk.id)
            added.append(match.chunk)

        return top_chunks + added

    # -- session controls ---------------------------------------------------

    def reset_conversation(self):
        self.memory.clear()
