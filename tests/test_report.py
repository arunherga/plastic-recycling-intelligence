"""Report rendering and the offline end-to-end pipeline."""

from __future__ import annotations

from datetime import date

from src.classify import classify_all
from src.deduplicate import deduplicate
from src.models import RunStats
from src.opportunity import detect_all
from src.report import build_report, why_it_matters, write_report
from src.score import score_all
from src.normalize import passes_topic_gate

REQUIRED_HEADINGS = [
    "## Executive Summary",
    "## Top Opportunities",
    "## Major Industry Developments",
    "## Buyers & Market Demand",
    "## Regulation & EPR",
    "## Tenders & Contracts",
    "## Technology & Machinery",
    "## Karnataka / Coastal Karnataka Watch",
    "## Articles Worth Investigating",
]


def pipeline(articles, config):
    kept = [
        a for a in articles
        if passes_topic_gate(
            f"{a.title} {a.description}",
            config.get("topic_gate.subject_terms"),
            config.get("topic_gate.geo_terms"),
        )
    ]
    kept = deduplicate(kept, preferred_domains=config.get("dedup.preferred_domains"))
    kept = classify_all(kept)
    kept = score_all(kept, config.get("scoring.rules"))
    return detect_all(kept, config.get("opportunities.rules"), 4)


class TestStructure:
    def test_every_required_section_is_present(self):
        content = build_report([], RunStats(), date(2026, 9, 20))
        for heading in REQUIRED_HEADINGS:
            assert heading in content

    def test_header_carries_the_title_and_date(self):
        content = build_report([], RunStats(), date(2026, 9, 20))
        assert content.startswith("# India Plastic Recycling Intelligence")
        assert "**Date:** 2026-09-20" in content

    def test_empty_run_renders_without_error(self):
        content = build_report([], RunStats(), date(2026, 9, 20))
        assert "No business opportunities cleared the threshold today." in content


class TestContent:
    def test_opportunities_carry_every_required_field(self, sample_articles, config):
        articles = pipeline(sample_articles, config)
        content = build_report(articles, RunStats(), date(2026, 9, 20))
        for label in (
            "- **Location:**",
            "- **Category:**",
            "- **Opportunity Type:**",
            "- **Relevance Score:**",
            "- **Why it matters:**",
            "- **Source:**",
            "- **URL:**",
        ):
            assert label in content

    def test_the_udupi_tender_reaches_the_karnataka_watch(self, sample_articles, config):
        articles = pipeline(sample_articles, config)
        content = build_report(articles, RunStats(), date(2026, 9, 20))
        watch = content.split("## Karnataka / Coastal Karnataka Watch")[1].split("##")[0]
        assert "Udupi" in watch

    def test_off_topic_items_never_reach_the_report(self, sample_articles, config):
        articles = pipeline(sample_articles, config)
        content = build_report(articles, RunStats(), date(2026, 9, 20))
        assert "cricket" not in content.lower()

    def test_summary_counts_come_from_stats(self):
        stats = RunStats(collected=70, unique=40, relevant=20, high_priority=8, opportunities=3)
        content = build_report([], stats, date(2026, 9, 20))
        assert "**Articles scanned:** 70" in content
        assert "**Unique articles after deduplication:** 40" in content
        assert "**Business opportunities flagged:** 3" in content

    def test_source_errors_are_surfaced_not_hidden(self):
        stats = RunStats(source_errors=["rss: Example Feed: HTTP timeout"])
        content = build_report([], stats, date(2026, 9, 20))
        assert "Source issues" in content
        assert "HTTP timeout" in content


class TestWhyItMatters:
    def test_explanation_is_derived_from_score_reasons(self):
        from tests.conftest import make_article

        article = make_article("Udupi tender for recycled HDPE", "https://example.com/a")
        article.score_reasons = ["Karnataka", "recycled HDPE", "buyer/procurement"]
        article.opportunity_type = ["TENDER"]
        text = why_it_matters(article)
        assert "tender" in text.lower()
        assert "karnataka" in text.lower()

    def test_ai_summary_takes_precedence_when_present(self):
        from tests.conftest import make_article

        article = make_article("Anything", "https://example.com/a")
        article.ai_summary = "A local buyer has appeared."
        assert why_it_matters(article) == "A local buyer has appeared."


class TestWriting:
    def test_report_lands_at_the_dated_path(self, tmp_path):
        path = write_report("# hello", tmp_path / "reports", date(2026, 9, 20))
        assert path.name == "2026-09-20.md"
        assert path.read_text(encoding="utf-8") == "# hello"
