Backend
========

The orchestrator (``services/orchestrator``) is the whole backend, and
the only service the frontend talks to. One FastAPI app, one shared
``Assistant`` instance behind a lock -- document upload and indexing,
retrieval, generation, and follow-up memory all live in the same place,
plus a second, unrelated feature (sentiment classification) that shares
nothing with the document pipeline but the process it runs in.

Backend Responsibilities
---------------------------

``Assistant`` (``app/assistant.py``) owns everything document-related:
indexing an upload into its own persistent collection, merging retrieval
across every uploaded document, handing the winning candidates to an LLM,
running guardrails on the way in and out, and tracking enough
conversation memory to resolve a short follow-up question. It is a
single shared instance, not a session-per-visitor design -- the same
scope Chatbot, the project this was ported from, names as its own known
limitation rather than something newly introduced here.

``app/sentiment.py`` is deliberately separate: it classifies pasted text
or OCR'd image text as positive, negative, or neutral, and touches none
of the state above -- no uploads, no retrieval, no memory. It shares the
same NVIDIA-hosted model and the same real/offline-stub backend pattern
as the document pipeline, but nothing else.

Pipeline
----------

**Upload.** ``POST /upload`` hands the raw file bytes to
``extract.extract_text()`` (``app/extract.py``), which turns whatever
format it is into plain text:

- Markdown/text: decoded directly.
- PDF: ``pypdf`` per page, enriched with any tables ``pdfplumber`` finds
  on that same page (rendered as pipe-delimited rows so the row/column
  structure survives instead of collapsing into unstructured prose), then
  any page pypdf came back near-empty on gets OCR'd individually via
  PyMuPDF + pytesseract -- per page, not the whole document at once, so a
  mostly-digital PDF with a few scanned or diagram-only pages mixed in
  doesn't silently lose just those pages.
- DOCX: ``python-docx`` paragraphs.
- Images: straight to OCR.

That text goes to ``Assistant.upload_document()``, which chunks it
(``chunker.py``: heading-based splitting when the document has real
``##``/``###`` structure, fixed 800-character overlapping windows
otherwise), extracts any diagrams if the upload was a PDF (see "Diagram
Understanding" below), and indexes everything -- text chunks and
flattened diagram chunks together -- into one fresh Chroma collection for
that document (``store.build_index()``). Embeddings are local (ONNX
MiniLM via Chroma's default embedding function), so indexing never costs
an API call.

**Ask.** ``POST /ask`` first runs ``guardrails.check_injection()`` on the
raw question, before any retrieval or generation -- a blocked question
never costs a vector search or an API call. Past that,
``Assistant.ask()`` asks every uploaded document's own ``Retriever`` to
rank candidates against the question (see "Retrieval and Ranking"),
merges the results across all documents, expands the winning candidate
with its document-neighbors and any in-document references it points at,
and hands the top chunks to ``llm.generate()`` (``app/llm.py``) -- a real
call to NVIDIA-hosted ``meta/llama-3.1-8b-instruct`` when
``NVIDIA_API_KEY`` is set, a deterministic offline stub otherwise (see
that module's own docstring for why this model and not a "reasoning"
one). The answer passes through output-side guardrails before it's
returned (see "Guardrails").

Retrieval and Ranking
------------------------

``retriever.py`` deliberately has no scope gate -- no pre-generation
"is this actually in the document" decision that can refuse or hedge a
question outright. Chatbot, the project this pipeline is ported from,
has one, calibrated against a labelled question set for one curated
handbook, in service of a "quote verbatim, never compose" promise.
Constellate composes an answer from arbitrary uploaded documents and has
no labelled question set to calibrate a gate against even if it wanted
one -- so it always searches and always returns ranked candidates, and
"is this actually answerable from what's here" is delegated to the LLM's
own prompt instruction (say so plainly if the context doesn't contain the
answer) rather than a numeric threshold.

Each candidate's score is cosine similarity from Chroma, plus a lexical
term (the fraction of the question's own content words that also appear
in the chunk, weighted by ``config.LEXICAL_WEIGHT``), plus a small
same-document continuity boost (``config.TOPIC_BOOST``) when the question
is a follow-up on the same document as the previous turn (tracked by
``memory.py``). None of these three signals is sophisticated alone; the
combination is what makes the top candidate actually good rather than
merely close in embedding space.

**Long-range context.** Two further steps run only on the single winning
candidate, after ranking, before generation -- deliberately scoped to the
winner rather than every top candidate, so prompt size stays predictable
turn to turn:

- *Neighbor expansion* (``assistant.py``'s ``_expand_with_neighbors``,
  backed by ``Retriever.neighbor_ids()``/``fetch_chunks()``): pulls in the
  winning chunk's immediate document-neighbors, so a fact split across a
  chunk boundary isn't lost just because only one side of it scored well
  on its own.
- *Reference following* (``_expand_with_references``, backed by
  ``references.find_reference_queries()`` and ``Retriever.best_match()``):
  scans the winning chunk's own text for phrases like "as described
  above," "the aforementioned," or "see Section 3," and if it finds one,
  runs a second, targeted search against the same document for whatever
  it's pointing at -- reaching a chunk many chunks away that neighbor
  expansion, being adjacency-only, can't.

``Result.related`` (and the mirrored logic in ``Assistant.ask()``)
surfaces near-miss chunks within ``config.RELATED_MARGIN`` of the winner,
restricted to the winner's own document -- a close result from a
different document reads as noise regardless of score.

Diagram Understanding
-------------------------

A PDF page can hold a real flowchart or diagram, not just prose or a
scan -- OCR alone can read text sitting inside it, but has no notion of
which box connects to which, or what an arrow's label means. Four pieces,
run once at upload time for PDFs only:

- **Detection** (``diagrams.is_diagram_page()``/``find_diagram_pages()``):
  a page is flagged as a candidate diagram if it contains at least
  ``MIN_SHAPE_COUNT`` (3) distinct rectangle drawing primitives, and
  isn't dominated by one large raster image (more likely a scan, already
  handled by the OCR fallback above).
  Counting rectangles specifically, not any drawing primitive, is what
  keeps this from misfiring on ordinary tables -- a table's borders are
  typically plain line segments with zero rectangles, even though a
  larger table can produce a dozen-plus individual line-drawing objects.
- **Extraction** (``diagram_vision.extract_diagram_graph()``): each
  flagged page is rendered to a PNG (``diagrams.render_page_png()``) and
  sent to a vision-capable model -- ``meta/llama-3.2-11b-vision-instruct``
  on the same NVIDIA-hosted endpoint the text model uses, chosen for the
  same reason: a plain vision-instruct model, not a reasoning one, since
  this runs once per detected page during upload and shouldn't become the
  slow part of it. The model is prompted to return strict JSON describing
  nodes (an id and a label) and edges (source id, target id, an optional
  label), parsed defensively -- a response wrapped in a markdown code
  fence, or one that names an edge endpoint that isn't a real node, is
  recovered or dropped rather than raising. With no ``NVIDIA_API_KEY``
  configured, an offline stub returns one honestly-labelled placeholder
  node instead of pretending to have analyzed anything, so the whole
  pipeline is exercisable before there's a key to spend on it.
- **Storage**: each document's extracted graphs are written to
  ``diagrams.json`` alongside its ``chroma/`` collection and
  ``meta.json`` (see "Persistence"). A restart reloads them without
  re-running detection or re-spending a vision call -- exactly as
  expensive as a real generation call, and not something a routine
  restart should redo.
- **Retrieval**: each graph is flattened into plain-language prose
  (``DiagramGraph.to_text()`` -- node labels, then "X leads to Y (edge
  label)." sentences) and turned into a regular ``Chunk``
  (``assistant._diagram_chunks()``), indexed into the exact same Chroma
  collection as the document's text chunks. This is what makes a
  diagram's content show up in ranking, neighbor expansion, and
  reference-following for free -- ``Retriever.rank()`` has no notion of
  where a chunk came from, so a diagram chunk competes and wins on the
  same terms as any paragraph. A diagram chunk's citation reads as
  ``"<document> -> Diagram (page N)"``, distinguishing it from a text
  section at a glance. The raw node/edge structure isn't lost by
  flattening it this way -- it stays available on ``UploadedDoc.diagrams``
  for an actual relationship query later, this is only what gets embedded
  and searched today.

Guardrails
------------

``guardrails.py`` runs four checks, all rule-based rather than a second
LLM call -- a guardrail that calls an LLM to judge the first LLM's answer
would double latency and cost on every single question, which after the
model-choice lesson documented in ``llm.py`` was an easy one to rule out.

- **Input: injection/jailbreak detection** (``check_injection()``) --
  pattern-matching the raw question against phrasings like "ignore
  previous instructions" or "reveal your system prompt," before it's
  embedded or sent anywhere. A match short-circuits ``Assistant.ask()``
  immediately: no retrieval, no generation, no cost. Deliberately narrow
  patterns -- broader phrasing like "act as" is a legitimate way to ask a
  document question ("act as a lawyer and explain this clause") and would
  trade real false positives for attacks the narrower patterns already
  catch.
- **Output: groundedness** (``score_groundedness()``) -- the fraction of
  the answer's own content words that also appear somewhere in the chunks
  it was supposed to be grounded in. Not proof of correctness (a
  paraphrase can score low despite being accurate; a cherry-picked
  sentence can score high despite being misleading), but a free,
  model-free signal. Below ``LOW_GROUNDEDNESS_THRESHOLD`` (0.25), the
  reply carries a ``low_groundedness`` flag.
- **Output: content safety** (``check_content_safety()``) -- a keyword
  scan against a small, deliberately mild, illustrative word list, not a
  real moderation system. Demonstrates the check as a distinct guardrail
  type; a production version would call a moderation API or a trained
  classifier instead.
- **Output: format compliance** (``enforce_format()``) -- strips stray
  markdown the prompt already told the model not to use (headings, bullet
  markers, bold asterisks -- always safe to remove). Bracket-shaped
  citation patterns are only flagged, never stripped: an uploaded
  document can legitimately contain square brackets in quoted text (a
  contract placeholder like ``[Client]``), and blind-stripping would
  corrupt that instead of the citation the prompt was trying to prevent.

A fifth, related defense lives in ``llm.py`` itself rather than here: the
generation prompt explicitly instructs the model to treat retrieved
context as data, never as instructions, no matter what it appears to
contain. This is the actual defense against *indirect* injection via
uploaded document text -- a chunk could legitimately discuss prompt
injection as a topic, or could be an actually malicious sentence planted
to hijack the answer, and the model has no other way to tell those apart.
``check_injection()`` handles the live, typed question instead, by
blocking outright -- that works there because a question is short and
came from a real person, so a false positive just means "try rephrasing";
neither approach makes sense for the other's job.

All flags -- input-blocked, output guardrail flags, or none -- come back
on ``AskResponse.flags``.

Persistence
-------------

Every upload gets its own directory under ``config.UPLOADS_DIR``
(``data/uploads/<random-id>/``), not a shared collection and not a
``tempfile.TemporaryDirectory()`` that vanishes when the process exits.
Inside:

- ``chroma/`` -- that document's own Chroma collection (text chunks plus
  any flattened diagram chunks, embedded together).
- ``meta.json`` -- filename, chunk count, topics, keywords, and a
  diagram count; what ``UploadedDoc.summary()`` returns to the API too.
- ``diagrams.json`` -- present only if the upload produced any diagram
  graphs; the raw node/edge structure for each (see "Diagram
  Understanding").

``Assistant.__init__`` calls ``_load_persisted_uploads()``, which walks
``config.UPLOADS_DIR`` and reconstructs everything from what's on disk --
a fresh ``Retriever`` pointed at the existing ``chroma/`` collection
(nothing gets re-chunked or re-embedded), plus ``diagrams.json`` if it
exists. A partial or corrupt upload directory (the process died mid-write)
is skipped rather than failing the whole service. ``remove_upload()`` and
``clear_uploads()`` just delete the relevant directories outright.

Sentiment Analysis
---------------------

``app/sentiment.py`` classifies pasted text, or OCR'd text from an
uploaded image, as positive, negative, or neutral plus a one-sentence
reason -- entirely separate feature, no shared state with the document
pipeline above. Same two-backend shape as ``llm.py``: a real call to
``meta/llama-3.1-8b-instruct`` when ``NVIDIA_API_KEY`` is set, a small
hardcoded positive/negative word-list heuristic otherwise
(``backend: "llm"|"stub"`` on the response either way, so the frontend
can label a stub result rather than presenting it as a real analysis).
Reuses ``extract.py`` for OCR on image input, and runs
``guardrails.check_injection()`` on the input first -- pasted text and
OCR'd image text are exactly the kind of untrusted content that check
exists for, same reasoning as the live question in ``assistant.py``. A
blocked input comes back with ``label: "blocked"``, a display-worthy
result rather than an exception.
