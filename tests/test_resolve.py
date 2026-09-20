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


class TestRedirectPageParsing:
    """Google answers these links with a page, not an HTTP redirect.

    The first live attempt resolved 0 of 20 links because only the final
    response URL was inspected, and that stayed on news.google.com.
    """

    def test_destination_from_the_google_attribute(self):
        from src.resolve import _from_body

        html = '<c-wiz data-n-au="https://bangaloremirror.indiatimes.com/story-1"></c-wiz>'
        assert _from_body(html) == "https://bangaloremirror.indiatimes.com/story-1"

    def test_destination_from_a_meta_refresh(self):
        from src.resolve import _from_body

        html = '<meta http-equiv="refresh" content="0;url=https://www.indiatoday.in/a/b">'
        assert _from_body(html) == "https://www.indiatoday.in/a/b"

    def test_destination_from_a_canonical_link(self):
        from src.resolve import _from_body

        html = '<link rel="canonical" href="https://thehindu.com/a/b.ece">'
        assert _from_body(html) == "https://thehindu.com/a/b.ece"

    def test_google_infrastructure_links_are_ignored(self):
        from src.resolve import _from_body

        html = (
            '<a href="https://www.google.com/preferences">x</a>'
            '<a href="https://gstatic.com/y.js">y</a>'
            '<a href="https://businesstoday.in/real-article">z</a>'
        )
        assert _from_body(html) == "https://businesstoday.in/real-article"

    def test_a_page_with_no_destination_yields_nothing(self):
        from src.resolve import _from_body

        assert _from_body('<a href="https://news.google.com/loop">x</a>') == ""
        assert _from_body("") == ""


class TestResolutionReporting:
    def test_counts_are_returned_for_diagnostics(self):
        articles = [
            make_article("A", GOOGLE + "&i=1"),
            make_article("B", GOOGLE + "&i=2"),
            make_article("C", REAL),
        ]
        # Key on the stored URL: normalization reorders query parameters, so
        # the string passed to make_article is not what gets requested.
        client = FakeClient({articles[0].url: REAL})
        _, resolved, attempted = resolve_article_urls(articles, client)
        assert attempted == 2
        assert resolved == 1

    def test_an_unresolved_link_is_not_counted_as_resolved(self):
        article = make_article("A", GOOGLE)
        _, resolved, attempted = resolve_article_urls([article], FakeClient({GOOGLE: GOOGLE}))
        assert (resolved, attempted) == (0, 1)
        assert article.url == GOOGLE
