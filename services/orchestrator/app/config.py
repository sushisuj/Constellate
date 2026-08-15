"""Tunable settings for the orchestrator service.

Consolidates what used to be split across Constellate's orchestrator
(LLM settings) and ingestion (chunking) services, plus retrieval/memory
settings ported from Chatbot's src/config.py. The scope-gate thresholds
(ANSWER_THRESHOLD, HEDGE_THRESHOLD, RERANK_*) are deliberately not here --
see retriever.py's module docstring for why there's no gate to calibrate.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Loads NVIDIA_API_KEY (and anything else) from a .env file at the
# orchestrator service root, if one exists, without overriding a key
# already set in the shell environment.
load_dotenv()

# --- Chunking -----------------------------------------------------------
CHUNK_CHARS = 800
CHUNK_OVERLAP = 100

# --- Retrieval / ranking --------------------------------------------------
# How many candidate chunks to pull back from each uploaded document's
# index before ranking.
TOP_K = 5
# Final score = cosine_similarity + LEXICAL_WEIGHT * vocabulary_overlap
#               (+ TOPIC_BOOST when a follow-up stays on the same document)
LEXICAL_WEIGHT = 0.45
TOPIC_BOOST = 0.10
# A second chunk within this distance of the winner is offered as related.
RELATED_MARGIN = 0.12
MAX_RELATED = 2

# --- Long-range context (in-document back-references) ---------------------
# Cap on how many "as described above"-style references inside the winning
# chunk get followed per answer -- keeps prompt size bounded even if a
# chunk contains several referring phrases.
REFERENCE_MAX_QUERIES = 2
# A followed reference's search score has to clear this floor to be
# trusted. Without it, a vague reference with nothing genuinely relevant
# in the document (e.g. "as noted above" where "above" doesn't actually
# define anything) would still pull in whatever ranks highest overall,
# which is noise, not a real match.
REFERENCE_MIN_SCORE = 0.2

# --- Follow-up detection --------------------------------------------------
# A question with this many content words or fewer is treated as a
# follow-up and blended with the previous topic before searching.
FOLLOWUP_MAX_CONTENT_WORDS = 1
# How many previous turns' terms to carry forward.
MEMORY_TURNS = 2
# Hard cap on carried terms, so context stays a hint and never outweighs
# the words the user actually typed.
MAX_CARRIED_TERMS = 6

# --- Generation -----------------------------------------------------------
LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
# meta/llama-3.1-8b-instruct, not one of NVIDIA's "reasoning" models.
# Measured on Chatbot's own handbook questions: 0.7-12.6s, most under 2s,
# for the same kind of grounded quote-and-summarize job this does. A
# reasoning model (nemotron-3-ultra-550b-a55b, tried first here for
# knowledge-graph extraction; openai/gpt-oss-120b, tried first in Chatbot)
# spends hidden tokens reasoning before every answer regardless of
# question complexity -- 43-400+s per response, not usable at this app's
# latency requirements.
LLM_MODEL = "meta/llama-3.1-8b-instruct"
LLM_MAX_TOKENS = 2048
# How many top-ranked chunks (merged across every uploaded document) are
# handed to the LLM as context.
GENERATION_TOP_K = 3

# --- Storage ----------------------------------------------------------------
# Each upload gets its own subdirectory here (a Chroma collection plus a
# small meta.json) so documents survive a server restart. Previously these
# lived in a tempfile.TemporaryDirectory() that vanished the moment the
# process exited -- fine for a quick demo, not for actually using this.
UPLOADS_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
