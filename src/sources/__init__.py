"""Source registry.

Adding a source — including a paid API later — means writing one module here
and adding an entry to ``SOURCE_REGISTRY`` plus a block in ``config.yaml``.
Nothing downstream of collection needs to change, because every source speaks
the same ``RawItem`` language.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..config import Config
from ..models import RawItem
from .base import HttpClient, Source, SourceError
from .bing_news import BingNewsSource
from .google_news import GoogleNewsSource
from .government import GovernmentSource
from .rss import RSSSource

LOG = logging.getLogger(__name__)

# Sources that consume the configured search queries.
QUERY_SOURCES = {"google_news", "bing_news"}

SOURCE_REGISTRY: dict[str, Callable[..., Source]] = {
    "google_news": GoogleNewsSource,
    "bing_news": BingNewsSource,
    "rss": RSSSource,
    "government": GovernmentSource,
}

__all__ = [
    "HttpClient",
    "Source",
    "SourceError",
    "SOURCE_REGISTRY",
    "build_sources",
    "collect",
]


def build_sources(config: Config, client: HttpClient | None = None) -> list[Source]:
    """Instantiate every enabled source declared in configuration."""
    client = client or HttpClient(
        user_agent=config.user_agent,
        timeout=config.http_timeout,
        retries=int(config.get("app.http_retries", 2)),
        delay=float(config.get("app.request_delay_seconds", 1.0)),
    )
    max_per_query = int(config.get("collection.max_items_per_query", 30))

    sources: list[Source] = []
    for name, factory in SOURCE_REGISTRY.items():
        if not config.source_enabled(name):
            LOG.info("source %s disabled in config", name)
            continue
        source_cfg: dict[str, Any] = config.source_config(name)
        if name in QUERY_SOURCES:
            sources.append(factory(source_cfg, client, config.queries, max_per_query))
        else:
            sources.append(factory(source_cfg, client, max_per_query))
    return sources


def collect(sources: list[Source], max_items_total: int = 600) -> tuple[list[RawItem], list[str], list[str]]:
    """Run every source, isolating failures.

    Returns ``(items, errors, sources_ok)``. A source that raises is logged and
    skipped; the run continues with whatever the others produced.
    """
    items: list[RawItem] = []
    errors: list[str] = []
    ok: list[str] = []

    for source in sources:
        try:
            fetched = source.fetch()
            items.extend(fetched)
            errors.extend(source.errors)
            ok.append(f"{source.name} ({len(fetched)} items)")
            LOG.info("source %s returned %d items", source.name, len(fetched))
        except Exception as exc:  # noqa: BLE001 - total isolation is the point
            message = f"{source.name}: source unavailable: {exc}"
            errors.append(message)
            LOG.error(message)

    if len(items) > max_items_total:
        LOG.info("truncating %d collected items to %d", len(items), max_items_total)
        items = items[:max_items_total]
    return items, errors, ok
