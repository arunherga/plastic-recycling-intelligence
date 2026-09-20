"""Official and regulatory sources: PIB, CPCB, MoEFCC.

These matter disproportionately — an EPR amendment or a CPCB notification moves
the market more than a dozen trade stories — but the sites are inconsistent:
PIB publishes RSS, CPCB and MoEFCC only publish HTML listing pages.

Two strategies are supported per entry via ``kind``:

``rss``
    Parsed with the shared feed parser.
``html``
    Anchor tags are extracted with the standard library and filtered to links
    whose visible text looks plastics/waste related. No scraping framework, no
    heavy dependency, and no storing of the raw page.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from ..models import RawItem
from .base import HttpClient, Source, SourceError, parse_feed_entries

# A government link is only interesting if its text mentions our subject.
RELEVANT_TERMS = (
    "plastic", "waste", "recycl", "epr", "extended producer", "polymer",
    "circular", "swachh", "packaging", "scrap", "pollution", "solid waste",
)


class _LinkExtractor(HTMLParser):
    """Collect (href, text) pairs. Intentionally forgiving of broken markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            if text:
                self.links.append((self._href, text))
            self._href = None
            self._text = []


def extract_relevant_links(html: str, base_url: str, limit: int = 40) -> list[tuple[str, str]]:
    """Absolute (url, text) pairs whose text looks plastics/waste related."""
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML is expected, not fatal
        pass

    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for href, text in parser.links:
        if len(text) < 20:
            continue
        lowered = text.lower()
        if not any(term in lowered for term in RELEVANT_TERMS):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")) or absolute in seen:
            continue
        seen.add(absolute)
        results.append((absolute, text))
        if len(results) >= limit:
            break
    return results


class GovernmentSource(Source):
    name = "government"

    def __init__(self, config: dict[str, Any], client: HttpClient, max_items_per_feed: int = 30) -> None:
        super().__init__(config, client)
        self.feeds = list(config.get("feeds", []) or [])
        self.max_items_per_feed = max_items_per_feed

    def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        for feed in self.feeds:
            name = str(feed.get("name") or feed.get("url", "unnamed source"))
            url = feed.get("url")
            kind = str(feed.get("kind", "rss")).lower()
            if not url:
                self.record_error(name, "entry has no url")
                continue
            try:
                response = self.client.get(url)
                if kind == "html":
                    links = extract_relevant_links(response.text, url, self.max_items_per_feed)
                    if not links:
                        self.record_error(name, "no relevant links found on page")
                    for link, text in links:
                        items.append(
                            RawItem(
                                title=text,
                                url=link,
                                source=name,
                                # These pages rarely carry a machine-readable date.
                                published_at=None,
                                description="",
                                origin=f"government:{name}",
                            )
                        )
                else:
                    entries = list(parse_feed_entries(response.content, name, f"government:{name}"))
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
