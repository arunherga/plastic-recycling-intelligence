"""Transparent relevance scoring.

Every point added carries a human-readable reason, so a score can always be
explained in the report rather than appearing as an unaccountable number. Rules
live in ``config.yaml`` — changing what the agent cares about should never
require changing code.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import Article

# Used only when no rules are supplied (e.g. in isolated unit tests).
DEFAULT_RULES: list[dict[str, Any]] = [
    {"reason": "Karnataka", "points": 3, "terms": ["karnataka"]},
    {"reason": "Udupi / Mangaluru / Dakshina Kannada", "points": 3,
     "terms": ["udupi", "mangaluru", "mangalore", "dakshina kannada"]},
    {"reason": "Nearby southern states", "points": 2,
     "terms": ["kerala", "goa", "maharashtra", "tamil nadu"]},
    {"reason": "Recycled granules / pellets", "points": 3, "terms": ["granule", "pellet"]},
    {"reason": "Target polymers (HDPE / PP / LDPE / PET)", "points": 3,
     "terms": ["hdpe", "ldpe", "polypropylene", "pet bottle"]},
    {"reason": "Buyer / procurement / supplier requirement", "points": 4,
     "terms": ["procure", "procurement", "buyer", "supplier"]},
    {"reason": "Tender", "points": 4, "terms": ["tender", "rfp", "eoi"]},
    {"reason": "New recycling plant", "points": 3, "terms": ["new plant", "sets up", "commission"]},
    {"reason": "Capacity expansion", "points": 2, "terms": ["expansion", "capacity addition"]},
    {"reason": "Investment / funding / acquisition", "points": 2,
     "terms": ["investment", "funding", "acquisition"]},
    {"reason": "Major regulatory change", "points": 2,
     "terms": ["notification", "amendment", "epr", "cpcb", "moefcc"]},
    {"reason": "Recycling technology", "points": 1,
     "terms": ["chemical recycling", "pyrolysis", "ai sorting"]},
    {"reason": "Machinery / equipment", "points": 1, "terms": ["machinery", "extruder"]},
]


def score_article(article: Article, rules: Sequence[dict[str, Any]] | None = None) -> Article:
    """Score one article in place.

    Each rule fires at most once, so an article that says "Karnataka" five times
    does not out-rank one that says it once and also mentions a tender.
    """
    active_rules = list(rules) if rules else DEFAULT_RULES
    text = article.searchable_text

    total = 0
    reasons: list[str] = []
    for rule in active_rules:
        terms = rule.get("terms") or []
        if any(str(term).lower() in text for term in terms):
            total += int(rule.get("points", 0))
            reason = str(rule.get("reason", "")).strip()
            if reason and reason not in reasons:
                reasons.append(reason)

    # A story carried by many outlets is more likely to matter. Capped so that
    # syndication volume can never dominate substance.
    if article.duplicate_count >= 3:
        total += 1
        reasons.append(f"Widely reported ({article.duplicate_count + 1} outlets)")

    article.relevance_score = total
    article.score_reasons = reasons
    return article


def score_all(articles: Iterable[Article], rules: Sequence[dict[str, Any]] | None = None) -> list[Article]:
    """Score every article and return them sorted by score, newest first."""
    scored = [score_article(a, rules) for a in articles]
    scored.sort(key=lambda a: (-a.relevance_score, a.published_at or ""), reverse=False)
    scored.sort(key=lambda a: (a.relevance_score, a.published_at or ""), reverse=True)
    return scored
