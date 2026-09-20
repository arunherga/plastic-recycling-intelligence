"""Publisher-URL resolution for aggregator redirect links."""

from __future__ import annotations

from src.resolve import needs_resolution, resolve_article_urls, resolve_one
from tests.conftest import make_article

GOOGLE = "https://news.google.com/rss/articles/CBMifzFVX3lxTE1CbDdLMDFIaURmQkNIVV9D?oc=5"
REAL = "https://www.thehindu.com/news/national/karnataka/udupi-tender/article1.ece"
# What the normalizer stores: scheme forced to https, leading "www." dropped.
REAL_NORMALIZED = "https://thehindu.com/news/national/karnataka/udupi-tender/article1.ece"


class FakeResponse:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeClient:
    def __init__(self, mapping: dict[str, str] | None = None, fail: bool = False) -> None:
        self.mapping = mapping or {}
        self.fail = fail
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("timeout")
        return FakeResponse(self.mapping.get(url, url))

    def sleep(self):
        return None


class TestDetection:
    def test_aggregator_links_are_detected(self):
        assert needs_resolution(GOOGLE)
        assert needs_resolution("https://www.bing.com/news/apiclick.aspx?url=x")

    def test_publisher_links_are_left_alone(self):
        assert not needs_resolution(REAL)


class TestResolveOne:
    def test_returns_the_final_url(self):
        assert resolve_one(GOOGLE, FakeClient({GOOGLE: REAL})) == REAL

    def test_unresolved_aggregator_url_is_kept(self):
        # Landing back on the aggregator means the redirect did not complete.
        assert resolve_one(GOOGLE, FakeClient({GOOGLE: GOOGLE})) == GOOGLE

    def test_a_network_failure_keeps_the_original(self):
        assert resolve_one(GOOGLE, FakeClient(fail=True)) == GOOGLE


class TestResolveBatch:
    def test_url_source_and_id_are_updated(self):
        article = make_article("Udupi tender", GOOGLE, source="news.google.com")
        before = article.article_id
        resolve_article_urls([article], FakeClient({GOOGLE: REAL}))
        assert article.url == REAL_NORMALIZED
        assert article.article_id != before
        assert article.source == "thehindu.com"

    def test_publisher_urls_cost_no_requests(self):
        client = FakeClient()
        resolve_article_urls([make_article("Direct", REAL)], client)
        assert client.calls == 0

    def test_the_request_budget_is_respected(self):
        articles = [make_article(f"Story {i}", f"{GOOGLE}&i={i}") for i in range(10)]
        client = FakeClient()
        resolve_article_urls(articles, client, limit=3)
        assert client.calls == 3

    def test_a_named_source_is_preserved(self):
        article = make_article("Udupi tender", GOOGLE, source="The Hindu")
        resolve_article_urls([article], FakeClient({GOOGLE: REAL}))
        assert article.source == "The Hindu"
