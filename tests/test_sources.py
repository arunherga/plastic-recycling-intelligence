"""Source-layer behaviour: parsing, and independent failure."""

from __future__ import annotations

import pytest
import requests

from src.sources import build_sources, collect
from src.sources.base import HttpClient, Source, SourceError, parse_feed_entries
from src.sources.google_news import GoogleNewsSource
from src.sources.government import extract_relevant_links
from src.sources.rss import RSSSource

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example</title>
<item>
  <title>Udupi recycler expands capacity</title>
  <link>https://example.com/a?utm_source=rss</link>
  <pubDate>Fri, 19 Sep 2026 06:30:00 +0530</pubDate>
  <description>The Karnataka plant will add HDPE granule capacity.</description>
</item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, content: bytes = FEED) -> None:
        self.content = content
        self.text = content.decode("utf-8", "replace")


class FailingClient(HttpClient):
    def get(self, url, **kwargs):
        raise SourceError(f"HTTP request failed for {url}: simulated timeout")

    def sleep(self):
        return None


class WorkingClient(HttpClient):
    def get(self, url, **kwargs):
        return FakeResponse()

    def sleep(self):
        return None


class TestFeedParsing:
    def test_entries_are_converted_to_raw_items(self):
        items = list(parse_feed_entries(FEED, "Example", "rss:Example"))
        assert len(items) == 1
        assert items[0].title == "Udupi recycler expands capacity"
        assert items[0].origin == "rss:Example"

    def test_malformed_feed_does_not_raise(self):
        assert list(parse_feed_entries(b"<not a feed", "Broken", "rss:Broken")) == []


class TestGoogleNews:
    def test_url_includes_locale_and_recency(self):
        source = GoogleNewsSource({"hl": "en-IN", "gl": "IN", "ceid": "IN:en", "when": "2d"}, WorkingClient())
        url = source.build_url("recycled HDPE India")
        assert "news.google.com/rss/search" in url
        assert "when%3A2d" in url
        assert "hl=en-IN" in url

    def test_each_query_is_fetched_independently(self):
        source = GoogleNewsSource({}, WorkingClient(), ["a", "b", "c"])
        assert len(source.fetch()) == 3


class TestIndependentFailure:
    def test_a_failing_feed_is_recorded_not_raised(self):
        source = RSSSource(
            {"feeds": [{"name": "Dead", "url": "https://dead.example/feed", "discover": False}]},
            FailingClient(),
        )
        assert source.fetch() == []
        assert source.errors and "simulated timeout" in source.errors[0]

    def test_one_dead_feed_does_not_stop_the_others(self):
        class MixedClient(HttpClient):
            def get(self, url, **kwargs):
                if "dead" in url:
                    raise SourceError("HTTP timeout")
                return FakeResponse()

            def sleep(self):
                return None

        source = RSSSource(
            {"feeds": [
                {"name": "Dead", "url": "https://dead.example/feed", "discover": False},
                {"name": "Alive", "url": "https://alive.example/feed"},
            ]},
            MixedClient(),
        )
        items = source.fetch()
        assert len(items) == 1
        assert len(source.errors) == 1

    def test_a_source_that_explodes_entirely_is_isolated(self):
        class Exploding(Source):
            name = "exploding"

            def fetch(self):
                raise RuntimeError("source unavailable")

        class Fine(Source):
            name = "fine"

            def fetch(self):
                return list(parse_feed_entries(FEED, "Example", "rss:Example"))

        items, errors, _notes, ok = collect([Exploding({}, WorkingClient()), Fine({}, WorkingClient())])
        assert len(items) == 1
        assert any("source unavailable" in e for e in errors)
        assert ok == ["fine (1 items)"]

    def test_feed_entry_without_a_url_is_reported(self):
        source = RSSSource({"feeds": [{"name": "No URL"}]}, WorkingClient())
        assert source.fetch() == []
        assert "no url" in source.errors[0]


class TestGovernmentHtml:
    HTML = """
    <html><body>
      <a href="/whats-new/epr-guidelines-for-plastic-packaging-2026.pdf">Revised EPR guidelines for plastic packaging</a>
      <a href="/about">About us</a>
      <a href="https://cpcb.nic.in/rules/plastic-waste-management-amendment-rules">Plastic Waste Management Amendment Rules notified</a>
      <a href="/contact">Contact</a>
    </body></html>
    """

    def test_only_relevant_links_are_extracted(self):
        links = extract_relevant_links(self.HTML, "https://cpcb.nic.in/whats-new/")
        assert len(links) == 2
        assert all(url.startswith("https://cpcb.nic.in") for url, _ in links)

    def test_relative_links_are_made_absolute(self):
        links = extract_relevant_links(self.HTML, "https://cpcb.nic.in/whats-new/")
        assert any("cpcb.nic.in/whats-new/epr-guidelines" in url for url, _ in links)

    def test_broken_markup_does_not_raise(self):
        assert extract_relevant_links("<a href=", "https://example.com") == []


class TestBuildSources:
    def test_only_enabled_sources_are_built(self, config):
        names = [s.name for s in build_sources(config, WorkingClient())]
        assert "google_news" in names
        assert "bing_news" not in names  # disabled in config.yaml

    def test_query_sources_receive_the_configured_queries(self, config):
        source = next(s for s in build_sources(config, WorkingClient()) if s.name == "google_news")
        assert len(source.queries) == len(config.queries)

    def test_total_item_cap_is_enforced(self):
        class Many(Source):
            name = "many"

            def fetch(self):
                return list(parse_feed_entries(FEED, "Example", "x")) * 50

        items, _, _, _ = collect([Many({}, WorkingClient())], max_items_total=10)
        assert len(items) == 10


class TestHttpClient:
    def test_a_descriptive_user_agent_is_sent(self, monkeypatch):
        captured = {}

        def fake_get(url, **kwargs):
            captured.update(kwargs.get("headers", {}))
            raise requests.RequestException("stop here")

        monkeypatch.setattr(requests, "get", fake_get)
        client = HttpClient(user_agent="plastic-recycling-intelligence/1.0 (+https://example)", retries=0, delay=0)
        with pytest.raises(SourceError):
            client.get("https://example.com/feed")
        assert "plastic-recycling-intelligence" in captured["User-Agent"]

    def test_failures_are_retried_then_reported(self, monkeypatch):
        calls = {"n": 0}

        def fake_get(url, **kwargs):
            calls["n"] += 1
            raise requests.RequestException("timeout")

        monkeypatch.setattr(requests, "get", fake_get)
        client = HttpClient(retries=2, delay=0)
        with pytest.raises(SourceError):
            client.get("https://example.com/feed")
        assert calls["n"] == 3


class TestFeedDiscovery:
    """A moved feed should self-heal rather than need a config edit."""

    PAGE = (
        '<html><head>'
        '<link rel="alternate" type="application/rss+xml" href="/rss/current.xml">'
        '</head><body>hello</body></html>'
    )

    def test_advertised_feeds_are_found(self):
        from src.sources.base import find_feed_links

        links = find_feed_links(self.PAGE, "https://publisher.example/")
        assert links == ["https://publisher.example/rss/current.xml"]

    def test_a_404_feed_falls_back_to_the_advertised_one(self):
        page = self.PAGE

        class MovedFeedClient(HttpClient):
            def get(self, url, **kwargs):
                if url.endswith("/old/feed"):
                    raise SourceError("404 Client Error: Not Found")
                if url == "https://publisher.example/":
                    return FakeResponse(page.encode())
                return FakeResponse()

            def sleep(self):
                return None

        source = RSSSource(
            {"feeds": [{"name": "Moved", "url": "https://publisher.example/old/feed"}]},
            MovedFeedClient(),
        )
        items = source.fetch()
        assert len(items) == 1
        assert any("using https://publisher.example/rss/current.xml" in n for n in source.notes)

    def test_discovery_can_be_switched_off_per_feed(self):
        class DeadClient(HttpClient):
            def get(self, url, **kwargs):
                raise SourceError("404 Client Error: Not Found")

            def sleep(self):
                return None

        source = RSSSource(
            {"feeds": [{"name": "Dead", "url": "https://x.example/feed", "discover": False}]},
            DeadClient(),
        )
        assert source.fetch() == []
        assert source.notes == []


class TestNotesVersusErrors:
    def test_an_empty_query_is_a_note_not_an_error(self):
        class EmptyClient(HttpClient):
            def get(self, url, **kwargs):
                return FakeResponse(b'<?xml version="1.0"?><rss><channel></channel></rss>')

            def sleep(self):
                return None

        source = GoogleNewsSource({}, EmptyClient(), ["plastic recycling Udupi"])
        source.fetch()
        assert source.errors == []
        assert source.notes and "no results" in source.notes[0]

    def test_collect_returns_notes_separately(self):
        class Quiet(Source):
            name = "quiet"

            def fetch(self):
                self.record_note("query 'x'", "no results in the collection window")
                return []

        items, errors, notes, ok = collect([Quiet({}, WorkingClient())])
        assert items == [] and errors == []
        assert len(notes) == 1
