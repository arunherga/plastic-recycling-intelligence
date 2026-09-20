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
import re
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


# Google no longer answers these links with an HTTP redirect; it returns a page
# that carries the destination in an attribute and jumps there with script. The
# first live attempt resolved 0 of 20 links for exactly that reason, so the
# response body is inspected when following the link does not move us off the
# aggregator.
_BODY_PATTERNS = (
    re.compile(r'data-n-au="([^"]+)"'),
    re.compile(r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+url=([^"'>\s]+)""", re.I),
    re.compile(r'<link[^>]+rel=[\"\']?canonical[\"\']?[^>]+href=\"([^\"]+)\"', re.I),
)

# Hosts that appear on a redirect page but are never the article itself.
_INFRASTRUCTURE = re.compile(
    r"^https?://([a-z0-9.-]*\.)?(google\.[a-z.]+|gstatic\.com|googleapis\.com|"
    r"youtube\.com|blogger\.com)",
    re.I,
)
_ANY_LINK = re.compile(r'href="(https?://[^"]+)"')


def _from_body(html: str) -> str:
    """Pull the destination out of an aggregator's redirect page."""
    if not html:
        return ""
    for pattern in _BODY_PATTERNS:
        match = pattern.search(html)
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith("http") and not _INFRASTRUCTURE.match(candidate):
                return candidate
    for match in _ANY_LINK.finditer(html[:200000]):
        candidate = match.group(1)
        if not _INFRASTRUCTURE.match(candidate) and not needs_resolution(candidate):
            return candidate
    return ""


def resolve_one(url: str, client) -> str:
    """Follow ``url`` and return where it landed, or ``url`` unchanged."""
    try:
        response = client.get(url)
    except Exception as exc:  # noqa: BLE001 - never fail a run over a link
        LOG.info("could not resolve %s: %s", url[:80], exc)
        return url
    final = str(getattr(response, "url", "") or "")
    if final and not needs_resolution(final):
        return final
    return _from_body(str(getattr(response, "text", "") or "")) or url


def resolve_article_urls(
    articles: Iterable[Article], client, limit: int = 40
) -> tuple[list[Article], int, int]:
    """Resolve aggregator links in place, up to ``limit`` requests.

    Returns ``(articles, resolved, attempted)`` so a run can report how well
    resolution is working rather than silently handing back opaque links.

    ``article_id`` is recomputed from the resolved URL so the seen-article
    store keys on the publisher's address, which is stable across days, rather
    than on an aggregator token that changes.
    """
    items = list(articles)
    budget = limit
    resolved_count = 0
    attempted = 0
    for article in items:
        if budget <= 0:
            break
        if not needs_resolution(article.url):
            continue
        budget -= 1
        attempted += 1
        resolved = normalize_url(resolve_one(article.url, client))
        if resolved and resolved != article.url and not needs_resolution(resolved):
            article.url = resolved
            article.article_id = article_id(resolved)
            if not article.source or "news.google" in article.source.lower():
                article.source = domain_of(resolved)
            resolved_count += 1
        client.sleep()
    return items, resolved_count, attempted
