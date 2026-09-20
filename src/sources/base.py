"""Shared plumbing for every source.

The contract is deliberately tiny: a source has a ``name`` and a ``fetch()``
that returns ``RawItem`` objects. It must never raise for an ordinary network
problem — the collector treats an exception as a hard failure of that source,
and one flaky website should not take a daily run down with it.
"""

from __future__ import annotations

import logging
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass
from typing import Any, Iterable

import requests

from ..models import RawItem

LOG = logging.getLogger(__name__)


class SourceError(Exception):
    """Raised for failures the collector should report but survive."""


@dataclass
class HttpClient:
    """Small requests wrapper with timeout, retries and a descriptive UA."""

    user_agent: str = "plastic-recycling-intelligence/1.0"
    timeout: int = 20
    retries: int = 2
    delay: float = 1.0

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        headers.update(kwargs.pop("headers", {}) or {})

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.get(url, headers=headers, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    # Linear backoff is plenty for feeds; we are not hammering.
                    time.sleep(self.delay * (attempt + 1))
        raise SourceError(f"HTTP request failed for {url}: {last_error}") from last_error

    def sleep(self) -> None:
        """Politeness pause between consecutive requests to one host."""
        if self.delay:
            time.sleep(self.delay)


class Source:
    """Base class for all collectors."""

    name = "source"

    def __init__(self, config: dict[str, Any], client: HttpClient) -> None:
        self.config = config or {}
        self.client = client
        self.errors: list[str] = []
        # Notes are things worth printing but not failures — a query that
        # legitimately had no news today is not a broken source.
        self.notes: list[str] = []

    def fetch(self) -> list[RawItem]:  # pragma: no cover - interface
        raise NotImplementedError

    # -- helpers ----------------------------------------------------------
    def record_error(self, context: str, exc: Exception | str) -> None:
        """Log a sub-failure (one feed, one query) and keep going."""
        message = f"{self.name}: {context}: {exc}"
        self.errors.append(message)
        LOG.warning(message)

    def record_note(self, context: str, detail: str) -> None:
        """Log something informational that is not a failure."""
        message = f"{self.name}: {context}: {detail}"
        self.notes.append(message)
        LOG.info(message)


def parse_feed_entries(content: bytes | str, feed_name: str, origin: str) -> Iterable[RawItem]:
    """Parse RSS/Atom bytes into :class:`RawItem` objects.

    ``feedparser`` sets ``bozo`` on malformed feeds but usually still returns
    usable entries, so a parse warning is not by itself a reason to discard the
    feed.
    """
    import feedparser  # imported here so the module stays importable without it

    parsed = feedparser.parse(content)
    for entry in getattr(parsed, "entries", []) or []:
        link = entry.get("link") or ""
        title = entry.get("title") or ""
        if not link or not title:
            continue
        published = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("pubDate")
            or entry.get("dc_date")
        )
        description = entry.get("summary") or entry.get("description") or ""
        source_name = feed_name
        # Google News nests the real publisher here.
        nested = entry.get("source")
        if isinstance(nested, dict) and nested.get("title"):
            source_name = nested["title"]
        yield RawItem(
            title=title,
            url=link,
            source=source_name,
            published_at=published,
            description=description,
            origin=origin,
        )


class _FeedLinkExtractor(HTMLParser):
    """Collect <link rel="alternate" type="...rss|atom..."> hrefs."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        ctype = a.get("type", "").lower()
        href = a.get("href", "")
        if href and "alternate" in rel and ("rss" in ctype or "atom" in ctype):
            self.hrefs.append(href)


def find_feed_links(html: str, base_url: str) -> list[str]:
    """Absolute feed URLs advertised by a page's <head>.

    Publishers move their feeds and leave the old path 404ing, so rather than
    hard-coding a guess we ask the site where its feed lives now.
    """
    parser = _FeedLinkExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML is expected
        pass
    out: list[str] = []
    for href in parser.hrefs:
        absolute = urljoin(base_url, href)
        if absolute.startswith(("http://", "https://")) and absolute not in out:
            out.append(absolute)
    return out


def site_root(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}/"
