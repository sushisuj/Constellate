"""Conversation memory.

Ported unchanged from the Chatbot project's src/memory.py. There is no
language model here to rewrite a follow-up question, so the memory does it
arithmetically: it decides whether a question is context-dependent and, if
so, splices in the subject matter of the previous answered turn before the
question is embedded.

    Turn 1: "what does the refund policy say"  -> answered, topic=policy-pdf
    Turn 2: "how long is the window"           -> context-dependent
            searched as: "how long is the window refund policy"
            with a scoring boost for chunks in the same uploaded document
"""

from dataclasses import dataclass, field

from . import config
from .textutil import content_words, has_referring_word


@dataclass
class Turn:
    question: str
    topic: str
    terms: list


@dataclass
class Memory:
    turns: list = field(default_factory=list)

    def record(self, question, topic, section):
        """Remember an answered turn. Unanswered turns are deliberately not
        recorded, so a refusal never becomes the context for what follows.

        Only the *section heading* is carried forward, not the question
        that was asked -- carrying the whole question drowns out the one
        word that actually matters in a short follow-up.
        """
        terms = content_words(section)
        self.turns.append(Turn(question=question, topic=topic, terms=terms))

    def clear(self):
        self.turns.clear()

    @property
    def last_topic(self):
        return self.turns[-1].topic if self.turns else None

    def recent_terms(self):
        """Deduplicated terms from recent answered turns, newest first,
        capped so carried context stays a hint rather than the whole query.

        Only turns on the *current* topic contribute -- once the user
        switches subject (in practice: switches which uploaded document
        they're asking about), the previous topic's terms are actively
        misleading.
        """
        topic = self.last_topic
        seen = []
        for turn in reversed(self.turns[-config.MEMORY_TURNS:]):
            if turn.topic != topic:
                continue
            for term in turn.terms:
                if term not in seen:
                    seen.append(term)
        return seen[:config.MAX_CARRIED_TERMS]

    def is_followup(self, question):
        """True when the question cannot stand on its own."""
        if not self.turns:
            return False
        words = content_words(question)
        if len(words) <= config.FOLLOWUP_MAX_CONTENT_WORDS:
            return True
        return has_referring_word(question)

    def resolve(self, question):
        """Return (search_text, preferred_topic).

        preferred_topic is None unless this is a follow-up, so a fresh
        question is never dragged back toward the previous subject.
        """
        if not self.is_followup(question):
            return question, None
        carried = self.recent_terms()
        if not carried:
            return question, None
        return f"{question} {' '.join(carried)}", self.last_topic
