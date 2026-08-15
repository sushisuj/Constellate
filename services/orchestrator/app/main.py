"""Orchestrator service: the FastAPI app Constellate's frontend talks to.

One shared Assistant instance behind a lock -- matches Chatbot's own
webapp.py design (a single-shared-instance local/demo tool, not a
multi-tenant service) rather than attempting real per-visitor session
isolation as part of this port. Chatbot's README names this same tradeoff
explicitly as its own known limitation; it's inherited here, not newly
introduced.
"""

import threading

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import sentiment
from .assistant import Assistant
from .extract import UnsupportedFileType, extract_text
from .schemas import (
    AskRequest,
    AskResponse,
    SentimentRequest,
    SentimentResponse,
    UploadResponse,
)

MAX_QUESTION_CHARS = 500
MAX_UPLOAD_BYTES = 5_000_000
MAX_SENTIMENT_CHARS = 5_000

# Vite's dev server, both hostnames it might bind to. This is a local-dev
# allowlist, not a production one -- tighten before this ever leaves a
# laptop.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(title="Constellate orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
assistant = Assistant()
lock = threading.Lock()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "empty question")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(400, "question too long")
    with lock:
        try:
            reply = assistant.ask(question)
        except Exception as exc:  # noqa: BLE001 -- surfaced as a 502, not a crash
            raise HTTPException(502, f"generation failed: {exc}") from exc
    return AskResponse(
        message=reply.message,
        sources=reply.sources,
        related=reply.related,
        backend=reply.backend,
        flags=reply.flags,
    )


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile):
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "empty file")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file too large")

    try:
        text = extract_text(file.filename, raw_bytes)
    except UnsupportedFileType as exc:
        raise HTTPException(400, str(exc)) from exc

    with lock:
        try:
            uploaded = assistant.upload_document(text, file.filename, raw_bytes=raw_bytes)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return UploadResponse(**uploaded)


@app.get("/uploads")
def uploads_list():
    with lock:
        return {"uploads": assistant.list_uploads()}


@app.post("/uploads/remove")
def upload_remove(filename: str):
    with lock:
        removed = assistant.remove_upload(filename)
    if not removed:
        raise HTTPException(404, "no such uploaded document")
    return {"ok": True}


@app.post("/uploads/clear")
def upload_clear():
    with lock:
        assistant.clear_uploads()
    return {"ok": True}


@app.post("/reset")
def reset():
    with lock:
        assistant.reset_conversation()
    return {"ok": True}


# -- sentiment analysis ------------------------------------------------------
# Stateless: doesn't touch `assistant` or `lock`. Not part of the
# document-QA session -- a one-off classification of whatever text or
# image-with-text is handed to it, unrelated to what's been uploaded.


@app.post("/sentiment", response_model=SentimentResponse)
def sentiment_text(request: SentimentRequest):
    text = request.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    if len(text) > MAX_SENTIMENT_CHARS:
        raise HTTPException(400, "text too long")
    try:
        result = sentiment.analyze(text)
    except Exception as exc:  # noqa: BLE001 -- surfaced as a 502, not a crash
        raise HTTPException(502, f"sentiment analysis failed: {exc}") from exc
    return SentimentResponse(**result)


@app.post("/sentiment/image", response_model=SentimentResponse)
async def sentiment_image(file: UploadFile):
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "empty file")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file too large")

    try:
        text = extract_text(file.filename, raw_bytes)
    except UnsupportedFileType as exc:
        raise HTTPException(400, str(exc)) from exc

    if len(text) > MAX_SENTIMENT_CHARS:
        raise HTTPException(400, "extracted text too long")

    try:
        result = sentiment.analyze(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"sentiment analysis failed: {exc}") from exc
    return SentimentResponse(**result)
