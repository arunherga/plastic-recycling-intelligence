"""Core data structures shared by every stage of the pipeline.

A single ``Article`` object is created by the normalizer and then enriched in
place by the classifier, the scorer and the opportunity detector. Keeping one
shape end-to-end is what allows sources, classifiers and scorers to be swapped
independently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class RawItem:
    """What a source hands back, before normalization.

    Sources deliberately do as little as possible: fetch, pull out the obvious
    fields, and return. All cleaning happens in :mod:`src.normalize`.
    """

    title: str
    url: str
    source: str = ""
    published_at: Optional[str] = None
    description: str = ""
    # Free-form provenance, e.g. which query or feed produced this item.
    origin: str = ""


@dataclass
class Article:
    """A normalized, enriched article."""

    title: str = ""
    url: str = ""
    source: str = ""
    published_at: str = ""
    description: str = ""
    location: list[str] = field(default_factory=list)
    category: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    relevance_score: int = 0

    # --- enrichment added downstream -------------------------------------
    score_reasons: list[str] = field(default_factory=list)
    business_opportunity: bool = False
    opportunity_type: list[str] = field(default_factory=list)

    # --- internal bookkeeping (not part of the documented schema) --------
    article_id: str = ""
    normalized_title: str = ""
    origin: str = ""
    duplicate_of: Optional[str] = None
    duplicate_count: int = 0
    ai_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def published_date(self) -> Optional[datetime]:
        if not self.published_at:
            return None
        try:
            return datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def searchable_text(self) -> str:
        """Lower-cased haystack used by the classifier and scorer.

        Padded with spaces so that rules can match on `" pp "` and friends
        without catching the middle of another word.
        """
        return f" {self.title} {self.description} ".lower()


@dataclass
class RunStats:
    """Counters surfaced in the executive summary of the daily report."""

    collected: int = 0
    after_topic_gate: int = 0
    unique: int = 0
    new_since_last_run: int = 0
    relevant: int = 0
    high_priority: int = 0
    opportunities: int = 0
    source_errors: list[str] = field(default_factory=list)
    sources_ok: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
