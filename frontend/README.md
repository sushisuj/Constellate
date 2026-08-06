# Constellate frontend

React + Vite chat UI for `services/orchestrator`. Upload a document (or
remove one, or clear them all), ask questions about it, see cited answers
plus any near-miss "related" sections worth a look.

`src/api.js` is the only place that talks to the backend —
`uploadFile()`, `askQuestion()`, `listUploads()`, `removeUpload()`,
`clearUploads()`, all thin `fetch` wrappers around the orchestrator's
routes. Points at `VITE_API_BASE`, or `http://127.0.0.1:8001` if that's
unset.

`src/App.jsx` holds all UI state (uploads, messages, in-flight
upload/ask). The "Connections used" graph panel renders a real
constellation (Orion, Ursa Major, Cassiopeia, and others), redrawn at
random on load or via its ⟳ button — decorative, not backed by any real
document structure. The handful of gold labels on its stars *are* real,
though: pulled from the uploaded documents' own vocabulary (via each
upload's `keywords` field) once there's something to draw from, falling
back to a generic word bank before that.

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
