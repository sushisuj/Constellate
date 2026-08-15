"""Guardrail checks: input-side sanitization on the way in, output-side
validation on the way out.

Deliberately rule-based / heuristic, not a second LLM call. Reasoning
models already cost this app one latency fight (see llm.py's model-choice
comment, or config.py's -- 43-400+s per response from a "reasoning"
model instead of under 15s from a plain instruct one); a guardrail that
calls an LLM to judge the first LLM's output would reintroduce exactly
that problem, once per question, for every question. Rule-based checks
run in microseconds and cost nothing.

Four checks, three distinct guardrail *types*:

- Input sanitization (prompt-injection / jailbreak detection) --
  pattern-matching on the raw question, before it's embedded or sent
  anywhere. See check_injection().
- Output groundedness -- a lexical-overlap heuristic between the answer
  and the context it's supposed to be grounded in. Reuses
  textutil.content_words, the same utility retriever.py already uses for
  ranking candidates, pointed at a different question here: not "which
  chunk is closest" but "did the answer actually use what it was given."
  See score_groundedness().
- Output content safety -- a keyword scan for hostile/toxic language in
  the generated answer. Illustrative, not comprehensive -- a real system
  would use a moderation API or a trained classifier here instead of a
  hardcoded list. See check_content_safety().
- Output format compliance -- llm.py's prompt already instructs the model
  not to use markdown or bracketed citations; this re-checks that
  mechanically rather than trusting the instruction was followed. Markdown
  syntax gets stripped outright (always safe to remove); bracket-citation
  patterns only get flagged, not removed, since uploaded documents can
  legitimately contain square brackets in quoted text and blind-stripping
  would corrupt that. See enforce_format().

A fifth, related mitigation lives in llm.py itself rather than here: the
prompt explicitly tells the model to treat retrieved context as data,
never as instructions, which is the actual defense against indirect
injection via uploaded document content -- see that module's comment.
"""

import re

from .textutil import content_words

# --- Input: prompt-injection / jailbreak detection --------------------------

_INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|prior|above) instructions",
    r"disregard (all |the )?(previous|prior|above)",
    r"forget (all |the )?(previous|prior|above|everything)",
    r"reveal (your |the )?(system prompt|instructions)",
    r"(what|show me) (is |was )?your (system prompt|instructions)",
    r"print your (instructions|system prompt)",
    r"you are now (in )?(developer|jailbreak|dan) mode",
    r"act as if you (have no|had no) (restrictions|rules|guidelines)",
    r"jailbreak",
    r"bypass your (guidelines|rules|instructions)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Deliberately narrow. Broader phrasings like "pretend to be" or "act as"
# are common, legitimate ways to ask a document assistant a question
# ("act as a lawyer and explain this clause") -- including them here would
# trade real false positives for catching attacks that the more specific
# patterns above already cover. A production version of this would be
# tuned against a real corpus of benign and malicious questions rather
# than guessed at.


def check_injection(question):
    """Input-side guardrail. Returns a short reason string if the question
    looks like a prompt-injection / jailbreak attempt, else None.

    Rule-based on purpose -- fast enough to run on every question before
    any retrieval or generation happens, and blocking here means a
    malicious question never costs an API call at all.
    """
    match = _INJECTION_RE.search(question)
    if match:
        return f"input blocked: matched injection pattern {match.group(0)!r}"
    return None


# --- Output: groundedness -----------------------------------------------------

LOW_GROUNDEDNESS_THRESHOLD = 0.25


def score_groundedness(answer, chunks):
    """Output-side guardrail. Fraction of the answer's own content words
    that also appear somewhere in the chunks it was supposed to be
    grounded in. Not a proof the answer is correct -- a paraphrase can
    score low here despite being accurate, and a copied sentence can
    score high despite being cherry-picked out of context -- but it's a
    cheap, model-free signal that costs a dict lookup per word rather
    than a second LLM call.
    """
    answer_words = content_words(answer)
    if not answer_words:
        return 1.0

    context_vocab = set()
    for chunk in chunks:
        context_vocab.update(content_words(chunk.text))

    hits = sum(1 for w in answer_words if w in context_vocab)
    return hits / len(answer_words)


# --- Output: refusal detection -------------------------------------------------

# Phrasing the prompt's own "say so plainly rather than guessing" instruction
# tends to produce when the model declines to answer (see llm.py's prompt).
# Used to skip the groundedness check on refusals: a legitimate "the context
# doesn't cover that" is built to share almost no vocabulary with the source
# text -- that's the whole point of saying the source doesn't cover it -- so
# running it through score_groundedness() and flagging it low_groundedness
# isn't catching a bad answer, it's mislabelling a correct one as suspect.
_REFUSAL_PATTERNS = [
    r"(doesn't|does not) (mention|contain|cover|specify|say|include|state)",
    r"no (mention|information) (of|about)",
    r"(don't|do not) (have|see) (any )?information",
    r"nothing (in|about) the (context|document)",
    r"not (mentioned|specified|covered|stated) in the (context|document)",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), re.IGNORECASE)


def is_refusal(answer):
    """True if the answer looks like it's declining to answer rather than
    attempting one. See score_groundedness()'s docstring above for why a
    refusal needs to be exempted from that check rather than just scoring
    low and getting flagged like any other answer.
    """
    return bool(_REFUSAL_RE.search(answer))


# --- Output: content safety ---------------------------------------------------

# Illustrative only, not a real moderation list -- deliberately mild words
# so the mechanism is provable without putting anything actually
# offensive in the codebase. Swap for a moderation API or trained
# classifier before this guards anything that matters.
_UNSAFE_WORDS = {"stupid", "idiot", "hate", "worthless", "pathetic"}


def check_content_safety(answer):
    """Output-side guardrail. Returns the list of flagged words found in
    the answer, empty if none. A real implementation would call a
    moderation endpoint or a trained toxicity classifier instead of
    matching a hardcoded word list -- this exists to demonstrate the
    check as a distinct guardrail type, not to actually moderate content.
    """
    words = set(content_words(answer))
    return sorted(words & _UNSAFE_WORDS)


# --- Output: format compliance -------------------------------------------------

_MARKDOWN_LINE_RE = re.compile(r"^\s*(#{1,6}\s+|[-*]\s+)", re.MULTILINE)
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BRACKET_CITATION_RE = re.compile(r"\[[^\]]{1,60}\]")


def enforce_format(answer):
    """Output-side guardrail. Strips markdown syntax the prompt already
    told the model not to use (headings, bullet markers, bold asterisks
    -- always safe to remove, since none of it should legitimately appear
    in plain prose). Bracket-citation-shaped text only gets flagged, not
    stripped -- uploaded documents can legitimately contain square
    brackets in quoted text (contract placeholders like "[Client]", for
    instance), and blind-stripping would corrupt that rather than the
    citation the prompt was actually trying to prevent.

    Returns (cleaned_answer, flags).
    """
    cleaned = _MARKDOWN_LINE_RE.sub("", answer)
    cleaned = _MARKDOWN_BOLD_RE.sub(r"\1", cleaned)

    flags = []
    if _BRACKET_CITATION_RE.search(cleaned):
        flags.append("possible_bracket_citation")
    if cleaned != answer:
        flags.append("stray_markdown_stripped")

    return cleaned, flags
