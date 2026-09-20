"""Google News RSS source.

Free, no key, no quota paperwork: the public ``news.google.com/rss/search``
endpoint accepts a query string and locale parameters and returns an RSS feed.
Each configured query is fetched independently — one failing query costs us
that query's results and nothing else.
"""

from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import quote_plus

from ..backfill import Window
from ..models import RawItem
from .base import HttpClient, Source, SourceError, parse_feed_entries

BASE_URL = "https://news.google.com/rss/search"


class GoogleNewsSource(Source):
    name = "google_news"

    def __init__(
        self,
        config: dict[str, Any],
        client: HttpClient,
        queries: list[str] | None = None,
        max_items_per_query: int = 30,
        windows: Sequence[Window] | None = None,
    ) -> None:
        super().__init__(config, client)
        self.queries = list(queries or [])
        self.max_items_per_query = max_items_per_query
        # When set, each query is asked once per slice of time instead of once
        # against a rolling recent window. This is what gives a backfill any
        # reach into the past; see src/backfill.py.
        self.windows = list(windows or [])

    def build_url(self, query: str, window: Window | None = None) -> str:
        if window is not None:
            full_query = f"{query} {window.as_query_suffix()}"
        else:
            when = self.config.get("when")
            full_query = f"{query} when:{when}" if when else query
        params = (
            f"q={quote_plus(full_query)}"
            f"&hl={quote_plus(str(self.config.get('hl', 'en-IN')))}"
            f"&gl={quote_plus(str(self.config.get('gl', 'IN')))}"
            f"&ceid={quote_plus(str(self.config.get('ceid', 'IN:en')))}"
        )
        return f"{BASE_URL}?{params}"

    def fetch(self) -> list[RawItem]:
        if self.windows:
            return self._fetch_windowed()
        items: list[RawItem] = []
        for query in self.queries:
            items.extend(self._fetch_one(query))
        return items

    def _fetch_windowed(self) -> list[RawItem]:
        """One request per query per time slice, for historical backfills."""
        items: list[RawItem] = []
        empty_slices = 0
        for window in self.windows:
            before = len(items)
            for query in self.queries:
                items.extend(self._fetch_one(query, window, quiet=True))
            gained = len(items) - before
            if gained == 0:
                empty_slices += 1
            self.record_note(f"slice {window.label}", f"{gained} items")
        if empty_slices == len(self.windows) and self.windows:
            # Every slice empty usually means the date operators were ignored
            # or the queries are too narrow — worth flagging loudly.
            self.record_error(
                "backfill", "every time slice returned nothing; date filtering may not be applied"
            )
        return items

    def _fetch_one(self, query: str, window: Window | None = None, quiet: bool = False) -> list[RawItem]:
        label = f"query '{query}'" + (f" [{window.label}]" if window else "")
        try:
            response = self.client.get(self.build_url(query, window))
            entries = list(
                parse_feed_entries(response.content, "Google News", f"google_news:{query}")
            )
            if not entries and not quiet:
                # Narrow queries ("plastic recycling Udupi") often have no news
                # in a 48-hour window. That is a quiet day, not a fault.
                self.record_note(label, "no results in the collection window")
            return entries[: self.max_items_per_query]
        except SourceError as exc:
            self.record_error(label, exc)
        except Exception as exc:  # noqa: BLE001 - a bad feed must not kill the run
            self.record_error(f"{label} (unexpected)", exc)
        finally:
            self.client.sleep()
        return []
