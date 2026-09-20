"""Flag articles that look like an actionable business opportunity.

"Actionable" here means: someone wants to buy recycled material, someone has
put out a tender, someone is looking for a partner or supplier, or a demand
signal has appeared that a Karnataka recycler could respond to.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import Article

OPPORTUNITY_TYPES = ("BUYER", "TENDER", "PARTNERSHIP", "SUPPLIER", "INVESTMENT", "MARKET_DEMAND")

DEFAULT_RULES: list[dict[str, Any]] = [
    {"type": "TENDER", "terms": ["tender", "rfp", "expression of interest", "eoi", "bid invited"]},
    {"type": "BUYER", "terms": ["procure", "procurement", "buyer", "sourcing", "offtake", "rfq"]},
    {"type": "MARKET_DEMAND", "terms": ["recycled content", "post-consumer recycled", "demand for recycled"]},
    {"type": "PARTNERSHIP", "terms": ["partner", "partnership", "mou", "joint venture", "tie-up"]},
    {"type": "SUPPLIER", "terms": ["supplier requirement", "empanel", "vendor onboarding"]},
    {"type": "INVESTMENT", "terms": ["invest", "funding", "acquisition", "capex"]},
]

# Categories that on their own imply an opportunity even without a keyword hit.
IMPLIED_BY_CATEGORY = {
    "TENDER": "TENDER",
    "BUYER": "BUYER",
}


def detect_opportunity(
    article: Article,
    rules: Sequence[dict[str, Any]] | None = None,
    min_score: int = 4,
) -> Article:
    """Set ``business_opportunity`` and ``opportunity_type`` in place.

    The score floor keeps the opportunity list honest: a passing mention of the
    word "partner" in an irrelevant story should not surface as a lead.
    """
    active_rules = list(rules) if rules else DEFAULT_RULES
    text = article.searchable_text

    types: list[str] = []
    for rule in active_rules:
        opp_type = str(rule.get("type", "")).upper()
        if opp_type not in OPPORTUNITY_TYPES:
            continue
        if any(str(term).lower() in text for term in rule.get("terms") or []):
            if opp_type not in types:
                types.append(opp_type)

    for category, opp_type in IMPLIED_BY_CATEGORY.items():
        if category in article.category and opp_type not in types:
            types.append(opp_type)

    if types and article.relevance_score >= min_score:
        article.business_opportunity = True
        article.opportunity_type = types
    else:
        article.business_opportunity = False
        article.opportunity_type = []
    return article


def detect_all(
    articles: Iterable[Article],
    rules: Sequence[dict[str, Any]] | None = None,
    min_score: int = 4,
) -> list[Article]:
    return [detect_opportunity(a, rules, min_score) for a in articles]
