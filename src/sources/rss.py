"""Generic RSS/Atom source for trade press and mainstream feeds.

Every feed in ``sources.rss.feeds`` is fetched on its own. A dead feed is
recorded as an error and skipped; the rest of the list still runs.
"""

from __future__ import annotations

from typing import Any

from ..models import RawItem
from .base import (
    HttpClient,
    Source,
    SourceError,
    find_feed_links,
    parse_feed_entries,
    site_root,
)


class RSSSource(Source):
    name = "rss"

    def __init__(self, config: dict[str, Any], client: HttpClient, max_items_per_feed: int = 30) -> None:
        super().__init__(config, client)
        self.feeds = list(config.get("feeds", []) or [])
        self.max_items_per_feed = max_items_per_feed

    def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        for feed in self.feeds:
            name = str(feed.get("name") or feed.get("url", "unnamed feed"))
            url = feed.get("url")
            if not url:
                self.record_error(name, "feed entry has no url")
                continue
            entries = self._fetch_feed(name, url)
            if entries is None and feed.get("discover", True):
                # The configured path is gone or blocked — ask the site where
                # its feed lives now rather than guessing a new URL.
                entries = self._rediscover(name, url)
            if entries:
                items.extend(entries[: self.max_items_per_feed])
            self.client.sleep()
        return items

    def _fetch_feed(self, name: str, url: str) -> list[RawItem] | None:
        """Fetch one feed. Returns None when it could not be used at all."""
        try:
            response = self.client.get(url)
        except SourceError as exc:
            self.record_error(name, exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self.record_error(f"{name} (unexpected)", exc)
            return None
        try:
            entries = list(parse_feed_entries(response.content, name, f"rss:{name}"))
        except Exception as exc:  # noqa: BLE001
            self.record_error(f"{name} (parse failure)", exc)
            return None
        if not entries:
            self.record_error(name, "invalid or empty feed")
            return None
        return entries

    def _rediscover(self, name: str, url: str) -> list[RawItem] | None:
        root = site_root(url)
        if not root:
            return None
        try:
            page = self.client.get(root)
        except Exception as exc:  # noqa: BLE001
            self.record_note(name, f"feed discovery failed ({exc})")
            return None
        candidates = [c for c in find_feed_links(page.text, root) if c != url]
        for candidate in candidates[:3]:
            entries = self._fetch_feed(f"{name} (discovered)", candidate)
            if entries:
                self.record_note(name, f"configured feed unusable; using {candidate}")
                return entries
        if not candidates:
            self.record_note(name, "no alternate feed advertised by the site")
        return None
