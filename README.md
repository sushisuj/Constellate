# Constellate

*a document search and explain assistant*

Constellate answers questions grounded in whatever documents you've
uploaded — PDFs, Word docs, plain text/markdown, and images or scanned
PDFs via OCR — citing its sources and saying so plainly when the answer
isn't in what's been uploaded.

The pipeline (upload → chunk → embed → retrieve → compose) is ported from
a sibling project, a university handbook chatbot, adapted for arbitrary
documents instead of one curated handbook: no scope gate, no verbatim-
quote-only mode, always composes an answer. An earlier direction — a
knowledge graph of entities and relationships across documents, answering
"how do these connect" rather than just "what does this say" — was tried
first and dropped; see `services/orchestrator/README.md`'s "What changed"
section for the full reasoning (short version: the model needed for
entity extraction was too slow to be usable).

## Architecture

Two pieces:

- **`services/orchestrator`** — the whole backend. FastAPI, one service:
  document upload and indexing, retrieval, and LLM-composed answers, all
  in one place (previously split across `orchestrator` and `ingestion`
  when the design was graph-based; see its README for why that split no
  longer applies).
- **`frontend`** — React chat UI (Vite). Wired to the orchestrator: upload
  a document, remove or clear uploads, ask a question, see the answer
  with citations and near-miss "related" sections. The "Connections used"
  graph panel is real constellations (Orion, Ursa Major, and others),
  picked and redrawn at random purely for brand decoration — no document
  data behind the shape itself, though the small gold labels on a few
  stars are drawn from the uploaded documents' own vocabulary once
  there's something to draw from.

LLM backend is NVIDIA's hosted NIM models (free tier, `build.nvidia.com`),
model `meta/llama-3.1-8b-instruct` — see
`services/orchestrator/app/llm.py`.

## Status

`services/orchestrator` is implemented and verified as far as this
environment allows (see its own README's Status section) — not yet
confirmed against the real NVIDIA/Chroma endpoints on an actual machine.
`frontend` now calls it directly (upload, remove, clear, ask, list
uploads) — the JS builds cleanly and the API calls were traced by hand
against the backend's routes, but the two haven't been run against each
other on a real machine yet either. That's the next thing to confirm.

Uploads now persist across a backend restart (`data/uploads/`, gitignored
— see `services/orchestrator/README.md`'s "What changed" section). The
reload-on-restart path was verified with a stubbed-out Chroma so the file
logic itself is exercised end to end, but not yet with the real
dependency stack on an actual machine.

## Running locally

Both pieces need to be running at once, in two terminals.

Backend — see `services/orchestrator/README.md` for full setup (Python
venv, `NVIDIA_API_KEY`, `uvicorn --port 8001`).

Frontend:

```bash
cd frontend
npm install
cp .env.example .env   # optional -- only needed if the backend isn't on
                        # 127.0.0.1:8001
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). Upload a
document, then ask about it. If the backend isn't running, the upload/ask
actions will show an error banner rather than hanging silently.
