"""Bing News RSS source (optional, disabled by default).

Bing's free news RSS endpoint still answers but rate-limits hard and is
inconsistent by region, so it is off in ``config.yaml``. It is included to show
that adding a second search-style source needs no change anywhere else.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from ..models import RawItem
from .base import HttpClient, Source, SourceError, parse_feed_entries

BASE_URL = "https://www.bing.com/news/search"


class BingNewsSource(Source):
    name = "bing_news"

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
        market = str(self.config.get("market", "en-IN"))
        return f"{BASE_URL}?q={quote_plus(query)}&format=RSS&mkt={quote_plus(market)}"

    def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        for query in self.queries:
            try:
                response = self.client.get(self.build_url(query))
                entries = list(parse_feed_entries(response.content, "Bing News", f"bing_news:{query}"))
                items.extend(entries[: self.max_items_per_query])
            except SourceError as exc:
                self.record_error(f"query '{query}'", exc)
            except Exception as exc:  # noqa: BLE001
                self.record_error(f"query '{query}' (unexpected)", exc)
            finally:
                self.client.sleep()
        return items
