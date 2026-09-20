"""Deduplication across URL, exact title and headline similarity."""

from __future__ import annotations

from src.deduplicate import deduplicate, headline_similarity
from tests.conftest import make_article


class TestUrlDeduplication:
    def test_tracking_variants_of_one_url_collapse(self):
        a = make_article("Plant opens in Udupi", "https://thehindu.com/a.ece?utm_source=tw")
        b = make_article("Plant opens in Udupi", "https://www.thehindu.com/a.ece")
        result = deduplicate([a, b])
        assert len(result) == 1
        assert result[0].duplicate_count == 1


class TestTitleDeduplication:
    def test_identical_headline_from_two_outlets_collapses(self):
        a = make_article("Udupi to award plastic waste tender", "https://thehindu.com/a.ece")
        b = make_article("Udupi to award plastic waste tender", "https://deccanherald.com/b.html")
        assert len(deduplicate([a, b])) == 1

    def test_publisher_suffix_does_not_defeat_matching(self):
        a = make_article("Udupi to award plastic waste tender", "https://thehindu.com/a.ece")
        b = make_article("Udupi to award plastic waste tender - Deccan Herald", "https://deccanherald.com/b.html")
        assert len(deduplicate([a, b])) == 1

    def test_five_syndicated_copies_become_one(self):
        base = "Centre notifies new EPR targets for plastic packaging"
        articles = [
            make_article(base, "https://pib.gov.in/x1"),
            make_article(base + " - Mint", "https://livemint.com/x2"),
            make_article(base + " | ET", "https://economictimes.indiatimes.com/x3"),
            make_article(base, "https://example.com/x4"),
            make_article(base + " - Herald", "https://deccanherald.com/x5"),
        ]
        result = deduplicate(articles)
        assert len(result) == 1
        assert result[0].duplicate_count == 4

    def test_distinct_stories_are_kept_apart(self):
        a = make_article("Udupi to award plastic waste tender", "https://thehindu.com/a.ece")
        b = make_article("Bengaluru startup raises funds for PET recycling", "https://business-standard.com/b")
        assert len(deduplicate([a, b])) == 2


class TestSourcePreference:
    def test_preferred_domain_wins(self):
        title = "Centre notifies new EPR targets"
        low = make_article(title, "https://randomblog.example/x", description="short")
        high = make_article(title, "https://pib.gov.in/release", description="short")
        result = deduplicate([low, high], preferred_domains=["pib.gov.in", "thehindu.com"])
        assert len(result) == 1
        assert "pib.gov.in" in result[0].url

    def test_richer_entry_wins_when_domains_are_equal(self):
        title = "Recycler expands capacity in Karnataka"
        thin = make_article(title, "https://a.example/x", description="")
        rich = make_article(title, "https://b.example/y", description="A much longer description with detail.")
        result = deduplicate([thin, rich])
        assert len(result) == 1
        assert result[0].description


class TestMerging:
    def test_survivor_inherits_missing_fields_from_duplicates(self):
        title = "Udupi recycler signs supply deal"
        keeper = make_article(title, "https://pib.gov.in/x")
        other = make_article(title, "https://thehindu.com/y", description="Details about Kerala buyers.")
        other.published_at = "2026-09-19T00:00:00+00:00"
        result = deduplicate([keeper, other], preferred_domains=["pib.gov.in"])
        assert len(result) == 1
        assert result[0].description
        assert result[0].published_at
        assert "Kerala" in result[0].location


class TestSimilarity:
    def test_similarity_bounds(self):
        assert headline_similarity("abc", "abc") == 1.0
        assert headline_similarity("", "abc") == 0.0
        assert 0.0 < headline_similarity("plastic recycling plant udupi", "plastic recycling plant udupi district") < 1.0


class TestFixtureSet:
    def test_two_udupi_tender_versions_collapse(self, sample_articles):
        result = deduplicate(sample_articles, preferred_domains=["thehindu.com"])
        udupi = [a for a in result if "udupi" in a.normalized_title]
        assert len(udupi) == 1
        assert "thehindu.com" in udupi[0].url
        assert len(result) == len(sample_articles) - 1
