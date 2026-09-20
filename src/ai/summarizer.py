"""Optional "why it matters" summaries for the top-scoring articles only.

Design rules that keep this genuinely optional:

* The pipeline calls :func:`build_summarizer` unconditionally; with AI disabled
  it gets a :class:`NullSummarizer` that does nothing.
* Only the ``ai.max_articles`` highest-scoring articles are ever sent.
* Any provider failure degrades to the deterministic rule-based explanation.
"""

from __future__ import annotations

import logging
from typing import Iterable, Protocol

from ..models import Article

LOG = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an analyst supporting a plastic recycling business in Udupi, Karnataka, India. "
    "Explain in at most two sentences why a news item matters commercially to that business. "
    "Be concrete about material type, location, buyer, tender or regulation. No preamble."
)


class Summarizer(Protocol):
    enabled: bool

    def summarize(self, articles: Iterable[Article]) -> list[Article]:
        ...


class NullSummarizer:
    """The version 1 default: returns articles untouched."""

    enabled = False

    def summarize(self, articles: Iterable[Article]) -> list[Article]:
        return list(articles)


class LLMSummarizer:
    """Adds ``ai_summary`` to the highest-scoring articles."""

    enabled = True

    def __init__(self, provider, max_articles: int = 8) -> None:
        self.provider = provider
        self.max_articles = max_articles

    def summarize(self, articles: Iterable[Article]) -> list[Article]:
        items = list(articles)
        ranked = sorted(items, key=lambda a: a.relevance_score, reverse=True)[: self.max_articles]
        for article in ranked:
            prompt = (
                f"Headline: {article.title}\n"
                f"Source: {article.source}\n"
                f"Locations: {', '.join(article.location) or 'unspecified'}\n"
                f"Categories: {', '.join(article.category)}\n"
                f"Summary: {article.description or 'n/a'}\n\n"
                "Why does this matter to a plastic recycler in coastal Karnataka?"
            )
            text = self.provider.complete(prompt, SYSTEM_PROMPT)
            if text:
                article.ai_summary = text
        return items


def build_summarizer(ai_config: dict | None) -> Summarizer:
    """Return a working summarizer, or a no-op if AI is off or unreachable."""
    settings = dict(ai_config or {})
    if not settings.get("enabled"):
        return NullSummarizer()

    from .providers import get_provider

    provider = get_provider(str(settings.get("provider", "")), settings)
    if provider is None:
        LOG.warning("unknown AI provider %r; continuing without AI", settings.get("provider"))
        return NullSummarizer()
    if not provider.available():
        LOG.warning("AI provider %s unavailable; continuing without AI", provider.name)
        return NullSummarizer()
    return LLMSummarizer(provider, int(settings.get("max_articles", 8)))
