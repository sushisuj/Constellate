"""Tokenising helpers shared by the chunker and the follow-up memory.

Ported unchanged from the Chatbot project's src/textutil.py -- pure text
processing, nothing handbook-specific in it.
"""

import re

STOPWORDS = {
    "a", "about", "all", "am", "an", "and", "any", "are", "as", "at", "be",
    "been", "being", "but", "by", "can", "could", "did", "do", "does", "doing",
    "done", "for", "from", "get", "give", "go", "had", "has", "have", "he",
    "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is",
    "it", "its", "just", "know", "let", "like", "many", "may", "me", "might",
    "much", "must", "my", "need", "no", "not", "of", "on", "one", "or", "our",
    "out", "over", "please", "said", "say", "shall", "she", "should", "so",
    "some", "such", "tell", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "those", "to", "up", "us", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "would", "you", "your", "yours",
}

# Words that only make sense against something said earlier. Their presence is
# the strongest signal that a question is a follow-up rather than a fresh one.
#
# Kept deliberately tight -- pronouns and demonstratives only. Common
# prepositions and existentials were tried here and had to be removed:
# "about" exempted "what do you think about the election", and "there"
# exempted "is there a swimming pool", both of which should be judged on
# their own words.
REFERRING_WORDS = {
    "it", "its", "they", "them", "their", "that", "this", "these", "those",
    "one", "ones", "he", "she", "him", "her", "same", "another",
}

_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text):
    """Lowercase word tokens, punctuation stripped."""
    return _WORD.findall(text.lower())


def content_words(text):
    """Tokens carrying topic meaning.

    Stopwords, referring words and 1-character tokens are removed. Referring
    words are excluded because they point at earlier context rather than
    naming a subject.
    """
    return [
        t
        for t in tokenize(text)
        if t not in STOPWORDS and t not in REFERRING_WORDS and len(t) > 1
    ]


def has_referring_word(text):
    return any(t in REFERRING_WORDS for t in tokenize(text))


def normalize_whitespace(text):
    """Collapse hard-wrapped source lines into one flowing paragraph."""
    return re.sub(r"\s+", " ", text).strip()
