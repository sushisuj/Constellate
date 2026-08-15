API Reference
==============

The orchestrator exposes one HTTP API, all under a single FastAPI app
(``app/main.py``). No authentication anywhere -- this is a
single-shared-instance local/demo service, not a multi-tenant one; see
:doc:`backend` for that scope note. Every endpoint below follows the same
shape: Purpose, Auth required, Input, Success behaviour, Error cases, and
which frontend feature actually calls it.

Health
--------

``GET /health``

**Auth required:** No.

**Input:** None.

**Success behaviour:** Returns ``{"ok": true}``. Doesn't touch the shared
``Assistant`` instance or its lock -- a plain liveness check.

**Error cases:** None expected.

**Frontend feature:** Not called by the frontend today; exists for manual
or infrastructure health checks.

Upload Endpoints
-------------------

POST /upload
~~~~~~~~~~~~~~~

**Purpose:** Extract, chunk, embed, and index one document (and, for a
PDF, detect and extract any diagrams on it), adding it to the set of
documents ``/ask`` can answer from.

**Auth required:** No.

**Input:** ``multipart/form-data`` with one field, ``file``. Supported
extensions: ``.md``, ``.markdown``, ``.txt``, ``.pdf``, ``.docx``,
``.jpg``, ``.jpeg``, ``.png``, ``.webp``. Capped at
``MAX_UPLOAD_BYTES`` (5,000,000 bytes).

**Success behaviour:** ``200`` with an ``UploadResponse``:

.. code-block:: json

   {
     "filename": "policy.pdf",
     "chunks": 14,
     "topics": ["Policy"],
     "keywords": ["warranty", "claim", "delivery", "..."],
     "diagram_count": 1
   }

``chunks`` counts text chunks and flattened diagram chunks together (see
:doc:`backend`'s "Diagram Understanding"). The upload is appended to the
in-memory list of uploads, and persisted under
``data/uploads/<id>/`` so it survives a restart.

**Error cases:**

- ``400`` -- empty file body.
- ``400`` -- file exceeds ``MAX_UPLOAD_BYTES``.
- ``400`` -- unsupported file extension, or a PDF/image extraction
  produced no usable text (``extract.UnsupportedFileType``).
- ``400`` -- chunking produced zero chunks (``ValueError`` from
  ``store.build_index()``, e.g. an empty extracted-text document).

**Frontend feature:** The "+ Upload document" button in ``App.jsx``
(``uploadFile()`` in ``api.js``), disabled while a prior upload is still
in flight and until the consent modal has been accepted (see
:doc:`frontend`).

GET /uploads
~~~~~~~~~~~~~~~

**Purpose:** List every document currently loaded, so the frontend can
restore its upload chips on page load (documents persist across a
backend restart; the frontend does not).

**Auth required:** No.

**Input:** None.

**Success behaviour:** ``200`` with ``{"uploads": [UploadResponse, ...]}``,
one entry per currently-loaded document, in upload order.

**Error cases:** None expected.

**Frontend feature:** Called once on mount (``App.jsx``'s initial
``useEffect``) to populate the upload chips from whatever the backend
already has loaded.

POST /uploads/remove
~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose:** Remove one uploaded document -- deletes its Chroma
collection, ``meta.json``, and ``diagrams.json`` from disk, and drops it
from the in-memory list.

**Auth required:** No.

**Input:** Query parameter ``filename`` (the exact filename returned by
``/upload`` or ``/uploads``).

**Success behaviour:** ``200`` with ``{"ok": true}``.

**Error cases:** ``404`` -- no upload with that filename is currently
loaded.

**Frontend feature:** The × button on each upload chip
(``handleRemoveUpload()`` in ``App.jsx``).

POST /uploads/clear
~~~~~~~~~~~~~~~~~~~~~~~

**Purpose:** Remove every uploaded document at once.

**Auth required:** No.

**Input:** None.

**Success behaviour:** ``200`` with ``{"ok": true}``, even if there was
nothing to clear.

**Error cases:** None expected.

**Frontend feature:** The "Clear all" button, shown only once at least
one document is uploaded.

Ask Endpoint
--------------

POST /ask
~~~~~~~~~~~~

**Purpose:** Answer a question grounded in whatever's currently uploaded.

**Auth required:** No.

**Input:** JSON body ``{"question": "..."}``. Capped at
``MAX_QUESTION_CHARS`` (500 characters after stripping).

**Success behaviour:** ``200`` with an ``AskResponse``:

.. code-block:: json

   {
     "message": "The warranty term is thirty six months from purchase.",
     "sources": [{"source": "Policy", "citation": "Policy → Part 1"}],
     "related": ["Policy → Part 2"],
     "backend": "llm",
     "flags": []
   }

``backend`` is ``"llm"`` for a real generated answer or ``"stub"`` for
the deterministic offline fallback (no ``NVIDIA_API_KEY`` configured) --
the frontend labels stub answers explicitly rather than presenting a
template as a real response. ``flags`` can include ``blocked_injection``
(the question itself was blocked -- see below), ``low_groundedness``,
``unsafe_word:<word>``, ``stray_markdown_stripped``, or
``possible_bracket_citation``; see :doc:`backend`'s "Guardrails" for what
each one means. A blocked question short-circuits before retrieval or
generation ever runs -- ``message`` explains why in plain language, and
``sources``/``related`` come back empty.

If nothing has been uploaded yet, this still returns ``200`` with a
plain refusal message (not an error) explaining that a document needs to
be uploaded first.

**Error cases:**

- ``400`` -- empty question after stripping.
- ``400`` -- question exceeds ``MAX_QUESTION_CHARS``.
- ``502`` -- generation itself raised (e.g. the NVIDIA API call failed)
  -- surfaced as an HTTP error rather than crashing the service.

**Frontend feature:** The chat input bar (``handleAsk()`` in
``App.jsx``), disabled while a previous question is still in flight and
until the consent modal has been accepted.

Session Endpoints
--------------------

POST /reset
~~~~~~~~~~~~~~

**Purpose:** Clear follow-up memory (what the previous turn was about)
without touching any uploaded documents.

**Auth required:** No.

**Input:** None.

**Success behaviour:** ``200`` with ``{"ok": true}``. The next question
after this is treated as fresh, not a follow-up to whatever came before.

**Error cases:** None expected.

**Frontend feature:** Not wired into the UI today; exists on the API for
manual use or a future "new conversation" control.

Sentiment Endpoints
-----------------------

Unrelated to the document-QA endpoints above -- no shared state, no
uploads, no retrieval. See :doc:`backend`'s "Sentiment Analysis".

POST /sentiment
~~~~~~~~~~~~~~~~~~~

**Purpose:** Classify pasted text as positive, negative, or neutral.

**Auth required:** No.

**Input:** JSON body ``{"text": "..."}``. Capped at
``MAX_SENTIMENT_CHARS`` (5,000 characters after stripping).

**Success behaviour:** ``200`` with a ``SentimentResponse``:

.. code-block:: json

   {
     "label": "positive",
     "explanation": "The reviewer praises the product's build quality.",
     "backend": "llm",
     "flags": []
   }

``label`` can also come back as ``"blocked"`` if the input itself tripped
``guardrails.check_injection()`` -- a normal, display-worthy result with
``flags: ["blocked_injection"]``, not an error.

**Error cases:**

- ``400`` -- empty text after stripping.
- ``400`` -- text exceeds ``MAX_SENTIMENT_CHARS``.
- ``502`` -- classification itself raised.

**Frontend feature:** The "Analyze text" button in ``SentimentCard``.

POST /sentiment/image
~~~~~~~~~~~~~~~~~~~~~~~~~

**Purpose:** OCR an uploaded image, then classify the extracted text the
same way ``/sentiment`` does.

**Auth required:** No.

**Input:** ``multipart/form-data`` with one field, ``file`` (an image;
same size cap as ``/upload``, ``MAX_UPLOAD_BYTES``).

**Success behaviour:** ``200`` with a ``SentimentResponse``, same shape
as ``/sentiment``.

**Error cases:**

- ``400`` -- empty file, file too large, or OCR found no text
  (``extract.UnsupportedFileType``).
- ``400`` -- OCR'd text exceeds ``MAX_SENTIMENT_CHARS``.
- ``502`` -- classification itself raised.

**Frontend feature:** The "Analyze an image" button in ``SentimentCard``.

API Error Handling
----------------------

Every error response is JSON with a ``detail`` field
(FastAPI's ``HTTPException`` default shape), which is what the frontend's
``api.js`` reads and surfaces directly rather than showing a generic
"something went wrong."

- ``400`` -- the request itself is invalid: empty/oversized input, an
  unsupported file type, or a file that produced no usable content.
  Always the caller's to fix.
- ``404`` -- (uploads only) referenced a filename that isn't currently
  loaded.
- ``502`` -- the orchestrator's own call to an upstream model failed
  (generation or sentiment classification). Distinguished from ``400``
  deliberately: this isn't a bad request, it's this service failing to
  do its job.

**CORS.** ``app/main.py`` adds ``CORSMiddleware`` allowing exactly the
origins Vite's dev server binds to (``localhost:5173`` and
``127.0.0.1:5173``, see ``DEV_ORIGINS``). This is a hardcoded local-dev
allowlist, not a production-ready policy -- it would need to be
tightened (or made configurable) before this service was ever deployed
somewhere a browser could reach it from an origin other than a
developer's own machine.
