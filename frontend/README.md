# Constellate frontend

React + Vite chat UI for `services/orchestrator`. Upload a document, ask
questions about it, see cited answers.

`src/api.js` is the only place that talks to the backend — `uploadFile()`,
`askQuestion()`, `listUploads()`, all thin `fetch` wrappers around the
orchestrator's routes. Points at `VITE_API_BASE`, or
`http://127.0.0.1:8001` if that's unset.

`src/App.jsx` holds all UI state (uploads, messages, in-flight
upload/ask). The "Connections used" graph panel is static decoration, not
wired to real data — see the root README's "What changed" section for why
(short version: there's no knowledge graph behind it anymore).

## Running locally

```bash
npm install
cp .env.example .env   # optional, only needed if the backend isn't on
                        # 127.0.0.1:8001
npm run dev
```

The orchestrator needs to be running too (`services/orchestrator`, port
8001) — CORS is configured there for `localhost:5173`, Vite's default dev
port. If you run the frontend on a different port, add it to
`DEV_ORIGINS` in `services/orchestrator/app/main.py`.
