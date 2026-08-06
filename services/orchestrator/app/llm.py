"""Answer generation: a real LLM call when NVIDIA_API_KEY is set, a
deterministic offline stub otherwise.

Ported from the Chatbot project's src/llm.py, replacing this service's
original LangChain/ChatNVIDIA implementation. Two things changed along
with the port, not just the file:

- Model is meta/llama-3.1-8b-instruct, not nemotron-3-ultra-550b-a55b.
  The Nemotron model's reasoning overhead made ingestion's entity
  extraction take ~2 minutes per chunk (see the ingestion service's git
  history) -- the exact same failure mode Chatbot's own notes document for
  NVIDIA's other reasoning model (openai/gpt-oss-120b: 43-400+s per
  response). A plain instruct model with no hidden reasoning step is the
  fix in both places, and Chatbot's version is already measured: 0.7-12.6s
  for the same kind of grounded quote-and-summarize job this does.
- Plain openai SDK, not LangChain. LangChain's structured-output layer
  only ever earned its keep here for entity/relationship extraction, which
  no longer exists (see retriever.py's module docstring for why the
  knowledge-graph approach was dropped). A plain chat completion is all
  this needs now.

The LLM backend is NVIDIA's hosted API catalog (build.nvidia.com), which
serves open-weight models -- config.LLM_MODEL -- behind an OpenAI-compatible
endpoint, so the `openai` SDK talks to it via base_url rather than a
NVIDIA-specific client.

Both backends implement the same signature -- generate(question, chunks) ->
(text, backend) -- so callers never need to know which one actually ran, and
nothing here changes when a real key eventually shows up: put NVIDIA_API_KEY
in .env and the real path activates on its own.
"""

import os

from . import config


def generate(question, chunks):
    """chunks: candidate Chunk objects, best match first, non-empty.

    Returns (answer_text, backend), backend being "llm" or "stub" so the
    caller can flag stub answers to the user rather than presenting a
    template as if it were a real generated response.
    """
    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key:
        return _generate_llm(question, chunks, api_key), "llm"
    return _generate_stub(question, chunks), "stub"


def _generate_stub(question, chunks):
    """No network, no dependency, fully deterministic -- exists so the
    whole retrieve -> prompt -> generate -> cite pipeline is exercisable
    before there is an API key to spend."""
    lead = chunks[0]
    others = ", ".join(f"{c.source} — {c.citation}" for c in chunks[1:])
    note = f" (related: {others})" if others else ""
    return f"[stub] Based on {lead.source} — {lead.citation}: {lead.text}{note}"


def _generate_llm(question, chunks, api_key):
    import openai  # deferred: only imported once a key actually exists

    client = openai.OpenAI(base_url=config.LLM_BASE_URL, api_key=api_key)
    # Each block labelled with its source document, not just its section --
    # two different uploaded documents can each have a similarly-named
    # section, and the model needs the document name to attribute
    # correctly when a question draws on more than one.
    context = "\n\n".join(f"[{c.source} — {c.citation}]\n{c.text}" for c in chunks)
    prompt = (
        "Answer the question using ONLY the context below, which is drawn "
        "verbatim from one or more documents, each labelled with its "
        "source. If the context does not contain the answer, say so "
        "plainly rather than guessing.\n\n"
        "Formatting rules, no exceptions:\n"
        "- Plain prose only: no markdown, no asterisks, no bullet lists, "
        "no headers.\n"
        "- Never cite inline. Do not write source names, section titles, "
        "or any bracketed/parenthetical citation markers — no [ ], no "
        "( ), no 【 】, nothing. The interface already displays the "
        "source separately, so repeating it in the answer is redundant.\n"
        "- If more than one source is relevant, you may say so in plain "
        "words (e.g. \"the policy document covers X, and the FAQ covers "
        "Y\") without formal citation syntax.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        max_tokens=config.LLM_MAX_TOKENS,
        # Low, not the API default of 1 -- this is grounded lookup over a
        # handful of retrieved chunks, not creative writing, so answers
        # should stay close to the source text rather than paraphrasing
        # loosely.
        temperature=0.3,
        stream=False,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
