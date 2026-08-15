"""Turns a diagram/flowchart page image into a structured graph of nodes
and edges -- a real vision-model call when NVIDIA_API_KEY is set, a
deterministic offline stub otherwise. Same real/stub split as llm.py, for
the same reason: the whole detect -> extract -> store -> retrieve pipeline
needs to be exercisable before there's an API key to spend on it.

Model is meta/llama-3.2-11b-vision-instruct (see config.py):
NVIDIA-hosted, same OpenAI-compatible endpoint llm.py already talks to,
and a plain vision-*instruct* model rather than a reasoning one, for the
latency reasoning llm.py's own docstring and the project's lessons-learnt
already document -- a reasoning model burns hidden tokens "thinking"
before it ever answers, regardless of how simple the question is, and
this runs once per detected diagram page during upload, not once total.
"""

import base64
import json
import os
import re
from dataclasses import dataclass, field

from . import config


@dataclass
class Node:
    id: str
    label: str


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""


@dataclass
class DiagramGraph:
    page: int  # 0-based page index this came from
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    backend: str = ""  # "vision" or "stub" -- mirrors llm.py's Reply.backend

    def to_text(self):
        """Flatten this graph into plain-language prose describing its
        nodes and the relationships between them. What gets indexed for
        retrieval (see the next commit) -- lives here rather than in the
        retrieval module because it's a property of the graph's own
        shape, not of how it later gets searched.
        """
        if not self.nodes:
            return ""
        by_id = {n.id: n.label for n in self.nodes}
        lines = [n.label for n in self.nodes]
        for e in self.edges:
            src = by_id.get(e.source, e.source)
            dst = by_id.get(e.target, e.target)
            if e.label:
                lines.append(f"{src} leads to {dst} ({e.label}).")
            else:
                lines.append(f"{src} leads to {dst}.")
        return " ".join(lines)


_PROMPT = (
    "This image is a diagram or flowchart from a document. Identify every "
    "labelled box, node, or step, and every arrow or connector between "
    "them. Respond with ONLY a JSON object, no other text, no markdown "
    "code fence, in exactly this shape:\n"
    '{"nodes": [{"id": "short-slug", "label": "text as written in the box"}], '
    '"edges": [{"source": "node-id", "target": "node-id", "label": "text on '
    'the arrow, or empty string if unlabeled"}]}\n'
    'Invent short, stable, lowercase, hyphenated slugs for each node\'s "id" '
    "yourself -- they don't need to match anything else in the document, "
    "they only need to be consistent between the nodes list and the edges "
    'list. If the image has no legible nodes at all, respond with '
    '{"nodes": [], "edges": []}.'
)


def extract_diagram_graph(image_bytes, page_index):
    """image_bytes: PNG bytes of one rendered diagram page (see
    diagrams.render_page_png). page_index: 0-based page number, carried
    through so the resulting graph can cite where it came from.
    """
    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key:
        return _extract_vision(image_bytes, page_index, api_key)
    return _extract_stub(page_index)


def _extract_stub(page_index):
    """No network, no dependency, fully deterministic. Mirrors llm.py's
    _generate_stub: one honest, clearly-labelled placeholder rather than
    pretending to have analyzed anything, so a stub graph can never be
    mistaken for a real extraction downstream."""
    node = Node(
        id="diagram",
        label=(
            f"(offline stub) Diagram detected on page {page_index + 1}, "
            "not analyzed -- no NVIDIA_API_KEY configured."
        ),
    )
    return DiagramGraph(page=page_index, nodes=[node], edges=[], backend="stub")


def _extract_vision(image_bytes, page_index, api_key):
    import openai  # deferred: only imported once a key actually exists

    client = openai.OpenAI(base_url=config.LLM_BASE_URL, api_key=api_key)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=config.DIAGRAM_VISION_MODEL,
        max_tokens=config.DIAGRAM_VISION_MAX_TOKENS,
        # Low, not the API default of 1 -- this is structure extraction
        # ("what's actually drawn on this page"), not creative writing.
        temperature=0.1,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
    )
    raw = response.choices[0].message.content
    return _parse_graph(raw, page_index)


def _parse_graph(raw, page_index):
    """Best-effort JSON parsing. A vision model asked for "ONLY JSON"
    still sometimes wraps the object in a markdown code fence or adds a
    sentence before or after it, so this looks for the first {...} block
    in the response rather than assuming the whole reply is clean JSON.
    Malformed or unparseable output comes back as an empty graph (still
    backend="vision", so a caller can tell "the model ran but said
    nothing useful" apart from "no key configured at all").
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return DiagramGraph(page=page_index, nodes=[], edges=[], backend="vision")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return DiagramGraph(page=page_index, nodes=[], edges=[], backend="vision")

    nodes = [
        Node(id=str(n["id"]), label=str(n["label"]))
        for n in data.get("nodes", [])
        if isinstance(n, dict) and n.get("id") and n.get("label")
    ]
    node_ids = {n.id for n in nodes}
    edges = [
        Edge(source=str(e["source"]), target=str(e["target"]), label=str(e.get("label", "")))
        for e in data.get("edges", [])
        if isinstance(e, dict) and e.get("source") in node_ids and e.get("target") in node_ids
    ]
    return DiagramGraph(page=page_index, nodes=nodes, edges=edges, backend="vision")
