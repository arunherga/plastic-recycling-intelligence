"""Rule-based article classification.

Version 1 is deliberately deterministic: a keyword/rule engine with no model,
no network call and no cost. The public surface is a single ``Classifier``
protocol so an LLM-backed classifier can be dropped in later without touching
the pipeline (see :mod:`src.ai`).
"""

from __future__ import annotations

from typing import Iterable, Protocol

from .matching import contains_any
from .models import Article

# Canonical category vocabulary.
CATEGORIES = (
    "NEW_PLANT",
    "CAPACITY_EXPANSION",
    "BUYER",
    "SELLER",
    "TENDER",
    "REGULATION",
    "PRICE",
    "INVESTMENT",
    "TECHNOLOGY",
    "MACHINERY",
    "EPR",
    "COMPANY_NEWS",
    "MARKET",
    "OTHER",
)

# Ordered so that the most specific signals are evaluated first. An article may
# match any number of these; multi-label is the expected case.
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("NEW_PLANT", (
        "new plant", "new recycling plant", "recycling plant", "sets up plant",
        "to set up", "sets up", "set to open", "commissioned", "commissioning",
        "inaugurat", "greenfield", "foundation stone", "new facility",
        "opens recycling", "new unit", "recycling facility",
    )),
    ("CAPACITY_EXPANSION", (
        "expansion", "expand capacity", "capacity addition", "additional capacity",
        "doubling capacity", "ramp up capacity", "scale up capacity", "brownfield",
        "tonnes per annum", "tpa capacity", "increase capacity", "boost capacity",
    )),
    ("TENDER", (
        "tender", "e-tender", "rfp", "request for proposal", "expression of interest",
        "eoi", "bid", "bidder", "gem portal", "concession agreement",
        "municipal contract", "waste processing contract", "empanel",
        "waste-management contract", "waste management contract",
        "collection contract", "contract awarded", "awarded a contract",
        "signs contract", "civic body signs",
    )),
    ("BUYER", (
        "procure", "procurement", "to buy", "buyer", "buying", "sourcing",
        "offtake", "off-take", "purchase agreement", "supply agreement",
        "rfq", "request for quotation", "seeking suppliers", "vendor registration",
        "recycled content target", "commits to recycled",
    )),
    ("SELLER", (
        "supplier of", "supplies recycled", "launches recycled", "offering recycled",
        "to supply", "sells recycled", "produces recycled", "manufacturer of recycled",
    )),
    ("REGULATION", (
        "regulation", "rules", "notification", "gazette", "amendment", "mandate",
        "mandatory", "ban", "policy", "guidelines", "draft rules", "compliance",
        "pollution control board", "cpcb", "moefcc", "ministry of environment",
        "national green tribunal", "ngt", "plastic waste management rules",
    )),
    ("EPR", (
        "epr", "extended producer responsibility", "epr certificate",
        "epr target", "epr credit", "producer responsibility", "epr portal",
        "epr obligation", "recycled content obligation",
    )),
    ("PRICE", (
        "price", "prices", "pricing", "per kg", "per tonne", "per kilogram",
        "rs/kg", "price rise", "price fall", "market rate", "premium over virgin",
        "cheaper than virgin", "costlier",
    )),
    ("INVESTMENT", (
        "investment", "invests", "investing", "funding", "raises", "raised",
        "series a", "series b", "seed round", "acquisition", "acquires",
        "merger", "stake", "joint venture", "capex", "ipo", "valuation",
    )),
    ("TECHNOLOGY", (
        "chemical recycling", "advanced recycling", "mechanical recycling",
        "pyrolysis", "depolymeris", "depolymeriz", "glycolysis", "enzymatic",
        "ai sorting", "optical sorting", "near-infrared", "nir sorting",
        "solvent", "technology", "innovation", "patent", "pilot plant",
    )),
    ("MACHINERY", (
        "machinery", "machine", "extruder", "extrusion", "pelletiser", "pelletizer",
        "pelletising", "washing line", "shredder", "granulator", "baler",
        "sorting line", "equipment", "conveyor", "agglomerator",
    )),
    ("MARKET", (
        "market", "demand", "consumption", "forecast", "cagr", "growth",
        "imports", "exports", "supply shortage", "oversupply", "capacity utilisation",
        "industry body", "association",
    )),
    ("COMPANY_NEWS", (
        "limited", " ltd", "pvt", "company", "firm", "startup", "start-up",
        "announces", "launches", "partnership", "mou", "tie-up", "signs",
        "appoints", "quarterly results",
    )),
)


class Classifier(Protocol):
    """Anything that can attach categories to an article.

    Implementations must be side-effect free apart from setting
    ``article.category``.
    """

    def classify(self, article: Article) -> list[str]:  # pragma: no cover - protocol
        ...


class KeywordClassifier:
    """Deterministic keyword classifier — the version 1 default."""

    def __init__(self, rules: Iterable[tuple[str, tuple[str, ...]]] | None = None) -> None:
        self.rules = tuple(rules) if rules is not None else RULES

    def classify(self, article: Article) -> list[str]:
        text = article.searchable_text
        labels: list[str] = []
        for label, terms in self.rules:
            if contains_any(text, terms):
                labels.append(label)
        if not labels:
            labels.append("OTHER")
        return labels


def classify_all(articles: Iterable[Article], classifier: Classifier | None = None) -> list[Article]:
    """Classify in place and return the same list, for pipeline chaining."""
    engine = classifier or KeywordClassifier()
    result = []
    for article in articles:
        article.category = engine.classify(article)
        result.append(article)
    return result
