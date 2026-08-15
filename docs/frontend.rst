Frontend
=========

A single-page React app (Vite), built to be the one UI on top of the
orchestrator API (see :doc:`api`). No routing, no client-side state
management library -- one root component (``App``) holding everything in
``useState``, and two smaller components that manage their own state
because nothing they do needs to be shared (``SentimentCard``,
``ConsentModal``).

Frontend Structure
----------------------

.. code-block:: text

   frontend/src/
     main.jsx     entry point -- mounts <App /> into #root
     App.jsx      everything: components, state, the whole UI
     App.css      component styles
     index.css    CSS custom properties (theme colors, fonts), global resets
     api.js       thin fetch wrapper around the orchestrator's HTTP API

Everything the app actually does lives in ``App.jsx`` -- there was never
enough distinct UI surface here to justify splitting into a
``components/`` directory, so it stayed one file with several component
functions in it rather than one component per file.

Main Views and Components
-----------------------------

**App** -- the root component. Owns upload state, chat message history,
the current question draft, in-flight loading flags, and whether the
consent modal has been accepted. Renders the header, the upload row, the
chat card (message history plus the input bar), the decorative
``GraphPanel``, and ``SentimentCard`` underneath as a separate feature.

**ConsentModal** -- a full-screen blocking overlay shown until the user
explicitly accepts it (see "Consent and Disclaimer" below). Not a
dismiss-by-clicking-outside pattern deliberately: the only way past it is
the accept button itself.

**GraphPanel** -- the "Connections used" constellation panel. Purely
decorative (see "Decorative Elements" below) -- redraws to a new random
real constellation on mount, on a manual reshuffle click, and whenever
the uploaded documents' vocabulary changes.

**ConstellationMark** -- the small four-point star logo mark next to the
"Constellate" wordmark in the header, and again inside ``ConsentModal``.
A tiny inline SVG, not an image asset.

**SentimentCard** -- a self-contained card for the unrelated sentiment
feature (see :doc:`backend`'s "Sentiment Analysis"). Owns its own text
input, loading, error, and result state; nothing here is shared with
``App``'s document-QA state, matching the backend split.

API Client
------------

``src/api.js`` is a thin wrapper around ``fetch``, one function per
orchestrator endpoint: ``uploadFile``, ``askQuestion``, ``listUploads``,
``removeUpload``, ``clearUploads``, ``analyzeSentimentText``,
``analyzeSentimentImage``. Every function routes its response through a
shared ``unwrap()`` helper, which throws on a non-2xx response using the
server's own ``detail`` message when the body is JSON (falling back to
the response's status text otherwise) -- callers show that message
directly rather than a generic "something went wrong."

``API_BASE`` reads from ``VITE_API_BASE`` (an env var, see
:doc:`getting-started`), defaulting to ``http://127.0.0.1:8001`` for
local development against the orchestrator's default port.

Decorative Elements
------------------------

The "Connections used" panel is real constellations (Orion, Ursa Major,
Cassiopeia, and others) picked at random and redrawn with a small random
rotation each time, not a visualization of anything document-related --
there is no knowledge graph behind Constellate anymore (see
:doc:`architecture`'s "Architectural Changes"), so this is brand
decoration, not a UI element making a data claim. The shape itself is
always a real constellation's actual star layout; nothing about *which*
stars connect to which is invented.

What *is* real: a handful of the labelled stars draw their text from the
actual vocabulary of whatever's been uploaded (``documentWords`` in
``App.jsx``, sourced from each upload's ``keywords`` field), falling back
to a generic pipeline-flavored word bank before anything has been
uploaded. So the shape is decoration, but the words dotted across it
change based on real content once there is some.

Consent and Disclaimer
---------------------------

Two related but distinct pieces, both added so a first-time user has to
actively acknowledge how the app can fail before they can use it, not
just stumble into it:

- **The consent modal** (``ConsentModal``) blocks the upload button and
  the question input entirely on first use -- both are separately wired
  to stay disabled while consent hasn't been given, on top of the overlay
  itself blocking clicks. It explains, in plain terms, that the AI can
  misread a document, cite the wrong section, or state something
  confidently the source text doesn't actually support, and warns against
  uploading sensitive personal, financial, medical, or legal information.
  Accepting it writes a flag to ``localStorage``
  (``constellate-consent-v1``) so it doesn't reappear on later visits in
  the same browser -- real acknowledgement once, not repeated friction on
  every reload.
- **The static disclaimer** is a small, always-visible line under the
  chat input ("Constellate can make mistakes. Verify important answers
  against the source document.") -- present regardless of consent state,
  so the reminder doesn't disappear the moment someone gets past the
  modal once. Distinct from the per-answer ``low_groundedness`` flag note
  (see :doc:`backend`'s "Guardrails"), which only shows up on a specific
  answer the groundedness heuristic actually flagged; the disclaimer is
  unconditional.
