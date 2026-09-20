"""URL and title normalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models import RawItem
from src.normalize import (
    article_id,
    detect_locations,
    domain_of,
    normalize_item,
    normalize_title,
    normalize_url,
    parse_date,
    passes_topic_gate,
    strip_html,
    within_window,
)


class TestNormalizeUrl:
    def test_strips_utm_and_other_tracking_parameters(self):
        url = "https://example.com/story?utm_source=x&utm_medium=y&utm_campaign=z&id=42&fbclid=abc"
        assert normalize_url(url) == "https://example.com/story?id=42"

    def test_drops_fragment_www_and_trailing_slash(self):
        assert normalize_url("http://www.Example.COM/news/story/#section") == "https://example.com/news/story"

    def test_sorts_remaining_query_parameters(self):
        a = normalize_url("https://example.com/s?b=2&a=1")
        b = normalize_url("https://example.com/s?a=1&b=2")
        assert a == b

    def test_two_tracked_variants_of_one_story_collapse(self):
        a = normalize_url("https://www.thehindu.com/x/article1.ece?utm_source=twitter")
        b = normalize_url("http://thehindu.com/x/article1.ece#comments")
        assert a == b

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_is_safe(self, value):
        assert normalize_url(value or "") == ""

    def test_non_http_scheme_is_left_alone(self):
        assert normalize_url("mailto:someone@example.com") == "mailto:someone@example.com"

    def test_keeps_meaningful_path_case(self):
        assert normalize_url("https://example.com/News/Story") == "https://example.com/News/Story"


class TestNormalizeTitle:
    def test_removes_publisher_suffix(self):
        assert normalize_title("Udupi plant opens - The Hindu") == normalize_title("Udupi plant opens")

    def test_removes_stopwords_and_punctuation(self):
        assert normalize_title("The new plant, in Udupi!") == "plant udupi"

    def test_is_case_and_accent_insensitive(self):
        assert normalize_title("Bengaluru Recycler") == normalize_title("bengalūru recycler")

    def test_empty_title(self):
        assert normalize_title("") == ""


class TestHelpers:
    def test_strip_html_removes_markup_and_entities(self):
        assert strip_html("<p>Plastic &amp; waste</p>") == "Plastic & waste"

    def test_domain_of_drops_www(self):
        assert domain_of("https://www.deccanherald.com/a/b") == "deccanherald.com"

    def test_article_id_is_stable_across_tracking_variants(self):
        a = article_id("https://example.com/x?utm_source=a")
        b = article_id("https://www.example.com/x")
        assert a == b and len(a) == 16

    def test_parse_date_returns_utc(self):
        parsed = parse_date("Fri, 19 Sep 2026 06:30:00 +0530")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_parse_date_handles_junk(self):
        assert parse_date("not a date at all") is None
        assert parse_date(None) is None


class TestWindow:
    def test_recent_item_is_inside_window(self):
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        assert within_window(now - timedelta(hours=10), 48, now=now)

    def test_old_item_is_outside_window(self):
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        assert not within_window(now - timedelta(days=9), 48, now=now)

    def test_undated_item_follows_the_flag(self):
        assert within_window(None, 48, include_undated=True)
        assert not within_window(None, 48, include_undated=False)


class TestTopicGate:
    SUBJECT = ["plastic", "recycl", "polymer"]
    GEO = ["india", "karnataka"]

    def test_needs_both_subject_and_geography(self):
        assert passes_topic_gate("Plastic recycling plant in Karnataka", self.SUBJECT, self.GEO)
        assert not passes_topic_gate("Plastic recycling plant in Ohio", self.SUBJECT, self.GEO)
        assert not passes_topic_gate("Karnataka cricket final", self.SUBJECT, self.GEO)


class TestNormalizeItem:
    def test_builds_a_complete_article(self):
        item = RawItem(
            title="Udupi unit to make recycled HDPE granules",
            url="https://www.thehindu.com/a/b.ece?utm_source=x",
            source="The Hindu",
            published_at="2026-09-19T06:30:00+05:30",
            description="<p>The Karnataka plant will supply granules.</p>",
        )
        article = normalize_item(item)
        assert article is not None
        assert article.url == "https://thehindu.com/a/b.ece"
        assert "<p>" not in article.description
        assert "Udupi" in article.location and "Karnataka" in article.location
        assert "hdpe" in article.keywords
        assert article.article_id

    def test_rejects_items_without_a_title_or_url(self):
        assert normalize_item(RawItem(title="", url="https://example.com/x")) is None
        assert normalize_item(RawItem(title="Something", url="")) is None


class TestLocations:
    def test_specific_location_suppresses_generic_india(self):
        assert detect_locations("A plant in Udupi, India") == ["Udupi"]

    def test_falls_back_to_national(self):
        assert detect_locations("India tightens EPR rules") == ["India (national)"]

    def test_no_location(self):
        assert detect_locations("A recycling plant somewhere") == []


class TestForeignStories:
    """Real headlines from the 2026-06-22..2026-09-20 backfill.

    Google answers India-scoped queries with foreign stories, and its RSS
    descriptions end in the publisher's name — so "The Times of India" was the
    only reason a story about Costa Rica looked Indian, and it scored 8.
    """

    MARKERS = ["costa rica", "costa rican", "kenya", "rotterdam", "europe", "iowa", "massachusetts"]

    def test_the_costa_rica_story_is_rejected(self):
        from src.normalize import is_foreign_story

        title = "A Costa Rican mother saved for 9 years to buy land, then built her home with 7 tonnes of plastic"
        assert is_foreign_story(title, self.MARKERS) is True

    def test_a_foreign_story_naming_an_indian_place_is_kept(self):
        from src.normalize import is_foreign_story

        title = "EU waste proposal would ban India from importing bloc's metal scrap"
        assert is_foreign_story(title, ["europe", "eu"]) is False

    def test_an_indian_story_is_never_foreign(self):
        from src.normalize import is_foreign_story

        title = "Mangaluru: Karnataka's first RDF pellet manufacturing unit launched at Kemral"
        assert is_foreign_story(title, self.MARKERS) is False

    def test_no_markers_configured_rejects_nothing(self):
        from src.normalize import is_foreign_story

        assert is_foreign_story("Anything at all in Kenya", []) is False

    def test_the_gate_applies_the_foreign_test_to_the_headline_only(self):
        subject, geo = ["plastic"], ["india"]
        title = "A Costa Rican mother built her home with plastic"
        # "India" appears only in the publisher tail of the description.
        text = f"{title} The Times of India"
        assert passes_topic_gate(text, subject, geo) is True
        assert passes_topic_gate(text, subject, geo, title=title, foreign_markers=self.MARKERS) is False

    def test_an_indian_story_still_passes_the_gate(self):
        title = "Mangaluru gets Karnataka's first RDF pellet unit"
        assert passes_topic_gate(
            f"{title} plastic waste", ["plastic"], ["karnataka"],
            title=title, foreign_markers=self.MARKERS,
        ) is True
