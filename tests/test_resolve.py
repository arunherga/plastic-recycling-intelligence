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

        html = (
            '<c-wiz data-n-au="https://bangaloremirror.indiatimes.com/bangalore/'
            'cover-story/cpcb-takes-aim-at-plastic/articleshow/123.cms"></c-wiz>'
        )
        assert _from_body(html) == (
            "https://bangaloremirror.indiatimes.com/bangalore/cover-story/"
            "cpcb-takes-aim-at-plastic/articleshow/123.cms"
        )

    def test_destination_from_a_meta_refresh(self):
        from src.resolve import _from_body

        html = (
            '<meta http-equiv="refresh" content="0;url=https://www.indiatoday.in/'
            'cities/bengaluru/story/pvr-inox-fined-plastic-use-2026">'
        )
        assert _from_body(html) == (
            "https://www.indiatoday.in/cities/bengaluru/story/pvr-inox-fined-plastic-use-2026"
        )

    def test_destination_from_a_canonical_link(self):
        from src.resolve import _from_body

        html = (
            '<link rel="canonical" href="https://thehindu.com/news/national/'
            'karnataka/hasiru-samvada-campaign/article71.ece">'
        )
        assert _from_body(html) == (
            "https://thehindu.com/news/national/karnataka/hasiru-samvada-campaign/article71.ece"
        )

    def test_google_infrastructure_links_are_ignored(self):
        from src.resolve import _from_body

        html = (
            '<a href="https://www.google.com/preferences">x</a>'
            '<a href="https://gstatic.com/y.js">y</a>'
            '<a href="https://businesstoday.in/latest/economy/story/real-article">z</a>'
        )
        assert _from_body(html) == "https://businesstoday.in/latest/economy/story/real-article"

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


FAVICON = (
    "https://lh3.googleusercontent.com/-DR60l-K8vnyi99NZovm9HlXyZwQ85GMDxiwJ"
    "WzoasZYCUrPuUM_P_4Rb7ei03j-0nRs0c4F=w16"
)


class TestResolvedUrlMustLookLikeAnArticle:
    """From the 2026-06-22 backfill: all forty "resolved" links were this one
    16-pixel Google News favicon. The host filter matched "google.<tld>" and
    lh3.googleusercontent.com slipped past it, so the body parse settled on the
    first image on the page.
    """

    def test_the_favicon_that_broke_the_backfill_is_rejected(self):
        from src.resolve import looks_like_article

        assert looks_like_article(FAVICON) is False

    def test_any_google_host_is_rejected(self):
        from src.resolve import looks_like_article

        for url in (
            "https://lh3.googleusercontent.com/a/b/c/image",
            "https://www.google.com/preferences/something",
            "https://gstatic.com/assets/icon.svg",
            "https://ggpht.com/x/y/z/thumbnail",
        ):
            assert looks_like_article(url) is False, url

    def test_assets_are_rejected_whatever_the_host(self):
        from src.resolve import looks_like_article

        for url in (
            "https://cdn.publisher.example/assets/logo.png",
            "https://publisher.example/static/app.js",
            "https://publisher.example/styles/main.css",
            "https://publisher.example/feed/index.xml",
        ):
            assert looks_like_article(url) is False, url

    def test_share_widgets_are_rejected(self):
        from src.resolve import looks_like_article

        for url in (
            "https://twitter.com/intent/tweet?url=x",
            "https://www.facebook.com/sharer/sharer.php",
            "https://api.whatsapp.com/send?text=story",
        ):
            assert looks_like_article(url) is False, url

    def test_a_bare_homepage_is_not_an_article(self):
        from src.resolve import looks_like_article

        assert looks_like_article("https://publisher.example/") is False
        assert looks_like_article("https://publisher.example") is False

    def test_a_real_article_url_is_accepted(self):
        from src.resolve import looks_like_article

        for url in (
            "https://www.thehindu.com/news/national/karnataka/udupi-tender/article1.ece",
            "https://bangaloremirror.indiatimes.com/bangalore/cover-story/cpcb/articleshow/1.cms",
            "https://moef.gov.in/uploads/2026/epr-amendment.pdf",
        ):
            assert looks_like_article(url) is True, url

    def test_an_image_url_in_the_page_is_not_used_as_the_destination(self):
        from src.resolve import _from_body

        html = f'<a href="{FAVICON}">icon</a><a href="https://publisher.example/news/real-story">go</a>'
        assert _from_body(html) == "https://publisher.example/news/real-story"

    def test_a_page_offering_only_assets_yields_nothing(self):
        from src.resolve import _from_body

        assert _from_body(f'<a href="{FAVICON}">icon</a>') == ""

    def test_an_unusable_link_keeps_its_original_url(self):
        article = make_article("A story", GOOGLE)
        _, resolved, attempted = resolve_article_urls([article], FakeClient({GOOGLE: FAVICON}))
        assert (resolved, attempted) == (0, 1)
        assert article.url == GOOGLE


class TestRepeatedResolutionTarget:
    """Forty articles resolving to one URL is a parse failure, not forty scoops."""

    def test_only_the_first_article_takes_a_shared_target(self):
        target = "https://publisher.example/news/some-story"
        articles = [make_article(f"Story {i}", f"{GOOGLE}&i={i}") for i in range(4)]
        mapping = {a.url: target for a in articles}
        _, resolved, attempted = resolve_article_urls(articles, FakeClient(mapping))
        assert attempted == 4
        assert resolved == 1
        assert sum(1 for a in articles if a.url == target) == 1

    def test_the_others_keep_links_that_still_work(self):
        target = "https://publisher.example/news/some-story"
        articles = [make_article(f"Story {i}", f"{GOOGLE}&i={i}") for i in range(3)]
        resolve_article_urls(articles, FakeClient({a.url: target for a in articles}))
        assert all("news.google.com" in a.url for a in articles[1:])
