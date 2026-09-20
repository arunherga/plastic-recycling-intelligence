"""Collapse the same story arriving from several places into one entry.

A single PIB release typically shows up as the original plus four or five
syndicated rewrites. Three signals are used, cheapest first:

1. exact normalized URL
2. exact normalized title
3. fuzzy headline similarity, gated on shared tokens so the comparison stays
   O(n * small) rather than O(n^2) over full strings

When duplicates are found the *preferred* copy wins: a configured authoritative
domain beats an unknown one, then a longer description, then an earlier date.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable, Sequence

from .models import Article
from .normalize import domain_of, title_tokens


def _rank(article: Article, preferred_domains: Sequence[str]) -> tuple:
    """Sort key: lower is better. Used to pick the survivor of a duplicate set."""
    domain = domain_of(article.url)
    try:
        domain_rank = next(
            i for i, d in enumerate(preferred_domains) if domain == d or domain.endswith("." + d)
        )
    except StopIteration:
        domain_rank = len(preferred_domains)
    # Prefer richer entries, then earlier publication (the original beats the rewrite).
    return (domain_rank, -len(article.description or ""), article.published_at or "9999")


def headline_similarity(a: str, b: str) -> float:
    """Similarity of two already-normalized headlines, 0.0-1.0."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def deduplicate(
    articles: Iterable[Article],
    title_similarity_threshold: float = 0.85,
    min_shared_tokens: int = 3,
    preferred_domains: Sequence[str] | None = None,
) -> list[Article]:
    """Return one :class:`Article` per distinct story.

    ``duplicate_count`` on each survivor records how many copies were folded in,
    which is itself a signal — a story carried by eight outlets is a big story.
    """
    preferred_domains = list(preferred_domains or [])
    items = [a for a in articles if a.url]

    # --- pass 1: exact normalized URL ------------------------------------
    by_url: dict[str, list[Article]] = {}
    for article in items:
        by_url.setdefault(article.url, []).append(article)

    url_unique: list[Article] = []
    for group in by_url.values():
        group.sort(key=lambda a: _rank(a, preferred_domains))
        winner = group[0]
        winner.duplicate_count += len(group) - 1
        url_unique.append(winner)

    # --- pass 2 & 3: exact then fuzzy title ------------------------------
    survivors: list[Article] = []
    survivor_tokens: list[set[str]] = []
    exact_title_index: dict[str, int] = {}

    # Process the best candidates first so the survivor of each cluster is the
    # one we would have picked anyway.
    url_unique.sort(key=lambda a: _rank(a, preferred_domains))

    for article in url_unique:
        key = article.normalized_title
        match_index = None

        if key and key in exact_title_index:
            match_index = exact_title_index[key]
        elif key:
            tokens = title_tokens(article.title)
            for idx, existing_tokens in enumerate(survivor_tokens):
                if len(tokens & existing_tokens) < min_shared_tokens:
                    continue
                if headline_similarity(key, survivors[idx].normalized_title) >= title_similarity_threshold:
                    match_index = idx
                    break

        if match_index is None:
            survivors.append(article)
            survivor_tokens.append(title_tokens(article.title))
            if key:
                exact_title_index.setdefault(key, len(survivors) - 1)
        else:
            keeper = survivors[match_index]
            keeper.duplicate_count += 1 + article.duplicate_count
            article.duplicate_of = keeper.article_id
            # Backfill anything the keeper is missing from the discarded copy.
            if not keeper.description and article.description:
                keeper.description = article.description
            if not keeper.published_at and article.published_at:
                keeper.published_at = article.published_at
            for loc in article.location:
                if loc not in keeper.location:
                    keeper.location.append(loc)

    return survivors
