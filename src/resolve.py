"""Turn aggregator redirect links into the publisher's own URL.

Google News RSS does not hand out the article's real address. It returns an
opaque ``news.google.com/rss/articles/CBMi...`` link that only redirects when
followed. Those links are unreadable in a report, impossible to deduplicate
against the same story arriving from a direct feed, and they hide which
publisher you are about to open.

Resolving every collected item would mean hundreds of requests, so this runs
late — only for the handful of articles that will actually appear in the
report — and it fails soft: an unresolvable link is simply left as it was.
"""

from __future__ import annotations

import logging
from typing import Iterable

from .models import Article
from .normalize import article_id, domain_of, normalize_url

LOG = logging.getLogger(__name__)

# Hosts whose links are redirects rather than articles. Compared against
# domain_of(), which has already stripped a leading "www.".
AGGREGATOR_HOSTS = ("news.google.com", "news.bing.com", "bing.com")


def needs_resolution(url: str) -> bool:
    host = domain_of(url)
    return any(host == h or host.endswith("." + h) for h in AGGREGATOR_HOSTS)


def resolve_one(url: str, client) -> str:
    """Follow ``url`` and return where it landed, or ``url`` unchanged."""
    try:
        response = client.get(url)
    except Exception as exc:  # noqa: BLE001 - never fail a run over a link
        LOG.info("could not resolve %s: %s", url[:80], exc)
        return url
    final = str(getattr(response, "url", "") or "")
    if not final or needs_resolution(final):
        return url
    return final


def resolve_article_urls(articles: Iterable[Article], client, limit: int = 40) -> list[Article]:
    """Resolve aggregator links in place, newest-first, up to ``limit``.

    ``article_id`` is recomputed from the resolved URL so the seen-article
    store keys on the publisher's address, which is stable across days, rather
    than on an aggregator token that changes.
    """
    items = list(articles)
    budget = limit
    for article in items:
        if budget <= 0:
            break
        if not needs_resolution(article.url):
            continue
        budget -= 1
        resolved = normalize_url(resolve_one(article.url, client))
        if resolved and resolved != article.url:
            article.url = resolved
            article.article_id = article_id(resolved)
            if not article.source or "news.google" in article.source.lower():
                article.source = domain_of(resolved)
        client.sleep()
    return items
