# Orchestrator service

The whole backend, and the only FastAPI service the frontend talks to.
Ported from the Chatbot project's `Assistant`/retrieval/generation
pipeline, adapted for arbitrary uploaded documents instead of one curated
handbook. This used to be split across this service (LLM only) and a
separate `ingestion` service (chunking, vector store, knowledge-graph
entity extraction) — see "What changed" below for why that split is gone.

Upload a document (`POST /upload`), ask a question about whatever's been
uploaded so far (`POST /ask`), get a cited, LLM-composed answer back. No
scope gate, no verbatim-quote-only mode, no knowledge graph — see
`app/retriever.py`'s module docstring for the scope-gate reasoning and
`app/llm.py`'s for the model choice.

## What changed (and why)

**The knowledge-graph approach is dropped.** Constellate started as "build
a graph of entities and relationships across documents, retrieve the
relevant subgraph." In practice, entity/relationship extraction against
`nemotron-3-ultra-550b-a55b` took ~2 minutes per chunk — a reasoning model
spending hidden tokens before every answer, the same failure mode
documented in the Chatbot project's own setup notes for a different
reasoning model (`openai/gpt-oss-120b`: 43–400+s per response there). Chatbot's fix
was switching to a plain instruct model; the fix here is adopting Chatbot's
whole proven pipeline instead of continuing to fight the graph approach's
latency. `services/graph` and `services/retrieval` (both were still
just READMEs, never implemented) and `services/ingestion`'s
`graph_extraction.py`/`graph_store.py` are all superseded by this.

**LLM is `meta/llama-3.1-8b-instruct`, not `nemotron-3-ultra-550b-a55b`.**
Same NVIDIA endpoint and key, different model — measured on Chatbot's own
handbook questions at 0.7–12.6s, most under 2s, for the same kind of
grounded quote-and-summarize job this does.

**Plain `openai` SDK, not LangChain.** LangChain's structured-output layer
only earned its keep for entity extraction, which no longer exists. A
plain chat completion is all generation needs now.

**Ingestion is folded in, not a separate service.** The service split
existed to serve extraction-writes-graph / retrieval-reads-graph. With no
graph, that split maps to nothing real — Chatbot itself is one class
(`Assistant`) doing uploads, retrieval, and generation together, and this
mirrors that.

**Uploads are ephemeral, not a shared persistent store.** The old
`ingestion` service kept one Chroma collection shared across every
document ever uploaded, from anyone — a real leak (one conversation's
documents were retrievable from any other). Each upload here gets its own
temp-directory Chroma collection instead, matching Chatbot's own
`upload_document()` pattern. This is still a single-shared-`Assistant`-
instance service, not real multi-tenancy — same scope Chatbot's own
README names as its own limitation, not newly introduced here.

## Status

Implemented and verified as far as this environment allows: every module
imports cleanly, `/health`, `/ask` with no uploads (correct refusal
message), empty-question 400, and `/uploads` all behave correctly against
a live FastAPI `TestClient`. `/upload` was traced all the way through
text extraction → chunking → Chroma collection creation → the embedding
model's download call, which is where it hit this sandbox's network
policy (same wall `services/ingestion` hit before it was confirmed working
against the real NVIDIA/Chroma endpoints on an actual machine). Not yet
confirmed end-to-end for real — that's the next thing to do.

## Running locally

macOS/Linux:

```bash
cd services/orchestrator
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # fill in NVIDIA_API_KEY
.venv/bin/python -m uvicorn app.main:app --reload --port 8001
```

Windows (PowerShell):

```powershell
cd services\orchestrator
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env   # fill in NVIDIA_API_KEY
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8001
```

Then, from any shell (`curl.exe`, not the `Invoke-WebRequest` alias, on
Windows PowerShell):

```bash
curl.exe -X POST http://127.0.0.1:8001/upload -F "file=@/path/to/some.pdf"
curl.exe -X POST http://127.0.0.1:8001/ask -H "Content-Type: application/json" -d "{\"question\": \"What does this say about refunds?\"}"
```

First `/upload` call will be slow — Chroma downloads its ~80MB embedding
model to `~/.cache/chroma` the first time it's used, same as the Chatbot
project.
