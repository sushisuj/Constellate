# Orchestrator service

The whole backend, and the only FastAPI service the frontend talks to.
Ported from the Chatbot project's `Assistant`/retrieval/generation
pipeline, adapted for arbitrary uploaded documents instead of one curated
handbook. This used to be split across this service (LLM only) and a
separate `ingestion` service (chunking, vector store, knowledge-graph
entity extraction) — see "What changed" below for why that split is gone.

Upload a document (`POST /upload`), ask a question about whatever's been
uploaded so far (`POST /ask`), get a cited, LLM-composed answer back.
Remove one upload (`POST /uploads/remove?filename=...`) or all of them
(`POST /uploads/clear`); list what's currently loaded (`GET /uploads`);
reset the follow-up memory without touching uploads (`POST /reset`). No
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

**Each upload gets its own Chroma collection, and it's no longer
ephemeral.** The old `ingestion` service kept one Chroma collection shared
across every document ever uploaded, from anyone — a real leak (one
conversation's documents were retrievable from any other). Each upload
here still gets its own collection, but it now lives under
`data/uploads/<id>/` instead of a `tempfile.TemporaryDirectory()` that
vanished the moment the process exited — a small `meta.json` sits next to
each collection, and `Assistant.__init__` reloads whatever's there on
startup, so uploads survive a restart. This is still a
single-shared-`Assistant`-instance service, not real multi-tenancy — same
scope Chatbot's own README names as its own limitation, not newly
introduced here. Persistence and multi-tenancy are separate problems;
only the first one is solved.

**CORS is wired for local dev.** The frontend runs on Vite's dev server
(`localhost:5173`), a different origin than this API (`localhost:8001`),
so `app/main.py` adds `CORSMiddleware` allowing that origin specifically.
It's a hardcoded dev allowlist (`DEV_ORIGINS`), not meant to survive
contact with a real deployment.

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

The persistence path (upload → restart → reload, plus remove/clear
deleting their directories) was verified separately, against a stubbed-out
Chroma standing in for the real one — this sandbox couldn't get the real
`chromadb` package's full dependency chain (it pulls in OpenTelemetry's
gRPC exporter, which needs a C extension this environment couldn't build)
installed to test it directly. The file-handling logic itself — writing
and reading `meta.json`, reconstructing `UploadedDoc`s, deleting
directories on remove/clear — is exercised end to end by that test; what's
still unconfirmed is that exact same logic running against the real
Chroma on an actual machine.

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
