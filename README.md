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
- **`frontend`** — React chat UI (Vite). Not yet wired to the backend —
  still the default scaffold.

LLM backend is NVIDIA's hosted NIM models (free tier, `build.nvidia.com`),
model `meta/llama-3.1-8b-instruct` — see
`services/orchestrator/app/llm.py`.

## Status

`services/orchestrator` is implemented and verified as far as this
environment allows (see its own README's Status section) — not yet
confirmed against the real NVIDIA/Chroma endpoints on an actual machine.
`frontend` hasn't been touched yet; it's still `create-vite`'s default
template with no connection to the backend.

## Running locally

See `services/orchestrator/README.md` for backend setup (Python venv,
`NVIDIA_API_KEY`, `uvicorn`). The frontend has its own `npm install` /
`npm run dev` under `frontend/` — see `frontend/README.md`.
