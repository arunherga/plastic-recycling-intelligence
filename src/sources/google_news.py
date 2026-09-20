"""Google News RSS source.

Free, no key, no quota paperwork: the public ``news.google.com/rss/search``
endpoint accepts a query string and locale parameters and returns an RSS feed.
Each configured query is fetched independently — one failing query costs us
that query's results and nothing else.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

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
    ) -> None:
        super().__init__(config, client)
        self.queries = list(queries or [])
        self.max_items_per_query = max_items_per_query

    def build_url(self, query: str) -> str:
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
        items: list[RawItem] = []
        for query in self.queries:
            try:
                response = self.client.get(self.build_url(query))
                entries = list(parse_feed_entries(response.content, "Google News", f"google_news:{query}"))
                if not entries:
                    # Narrow queries ("plastic recycling Udupi") often have no
                    # news in a 48-hour window. That is a quiet day, not a fault.
                    self.record_note(f"query '{query}'", "no results in the collection window")
                items.extend(entries[: self.max_items_per_query])
            except SourceError as exc:
                self.record_error(f"query '{query}'", exc)
            except Exception as exc:  # noqa: BLE001 - a bad feed must not kill the run
                self.record_error(f"query '{query}' (unexpected)", exc)
            finally:
                self.client.sleep()
        return items
