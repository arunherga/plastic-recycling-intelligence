"""Generic RSS/Atom source for trade press and mainstream feeds.

Every feed in ``sources.rss.feeds`` is fetched on its own. A dead feed is
recorded as an error and skipped; the rest of the list still runs.
"""

from __future__ import annotations

from typing import Any

from ..models import RawItem
from .base import HttpClient, Source, SourceError, parse_feed_entries


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
            try:
                response = self.client.get(url)
                entries = list(parse_feed_entries(response.content, name, f"rss:{name}"))
                if not entries:
                    self.record_error(name, "invalid or empty feed")
                items.extend(entries[: self.max_items_per_feed])
            except SourceError as exc:
                self.record_error(name, exc)
            except Exception as exc:  # noqa: BLE001
                self.record_error(f"{name} (unexpected)", exc)
            finally:
                self.client.sleep()
        return items
