"""Word-boundary term matching.

Every rule engine in this project (topic gate, classifier, scorer, opportunity
detector) decides by looking for configured terms in an article's text. Doing
that with a plain substring test is wrong in a way that is easy to miss and
ruinous in practice: ``"pp"`` matches *a*pp*roves*, ``"ps"`` matches *to*ps*,
``"pet"`` matches com*pet*ition and ``"ban"`` matches ur*ban* and *Ban*galore.
A run using substring matching filed highway-tender and pharmaceutical-patent
stories as plastics news.

So terms are matched on word boundaries instead. Multi-word phrases still work
("plastic waste management rules"), and internal punctuation is tolerated so
``off-take`` matches ``off take`` and ``off-take`` alike.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Sequence

# Characters that count as "inside a word". A term must not be flanked by these.
_BOUNDARY = r"(?<![A-Za-z0-9]){}(?![A-Za-z0-9])"


@lru_cache(maxsize=4096)
def compile_term(term: str) -> re.Pattern[str]:
    """Compile one configured term into a boundary-anchored pattern.

    Whitespace and hyphens in the term are treated interchangeably, so a single
    configured spelling covers the ways publishers write it.
    """
    cleaned = str(term).strip().lower()
    parts = [re.escape(p) for p in re.split(r"[\s\-_/]+", cleaned) if p]
    if not parts:
        # A term of only punctuation can never match anything.
        return re.compile(r"(?!x)x")
    body = r"[\s\-_/]*".join(parts)
    return re.compile(_BOUNDARY.format(body), re.IGNORECASE)


def contains_term(text: str, term: str) -> bool:
    """Does ``text`` contain ``term`` as a whole word or phrase?"""
    if not text or not term:
        return False
    return compile_term(term).search(text) is not None


def matched_terms(text: str, terms: Iterable[str]) -> list[str]:
    """Every term from ``terms`` present in ``text``, in the given order."""
    if not text:
        return []
    return [t for t in terms if contains_term(text, t)]


def contains_any(text: str, terms: Iterable[str]) -> bool:
    """True if any term matches. Stops at the first hit."""
    if not text:
        return False
    return any(contains_term(text, t) for t in terms)


def count_matches(text: str, terms: Sequence[str]) -> int:
    return len(matched_terms(text, terms))
