"""Relevance scoring and opportunity detection."""

from __future__ import annotations

from src.opportunity import detect_all, detect_opportunity
from src.score import score_all, score_article
from tests.conftest import make_article

RULES = [
    {"reason": "Karnataka", "points": 3, "terms": ["karnataka"]},
    {"reason": "Udupi / Mangaluru / Dakshina Kannada", "points": 3, "terms": ["udupi", "mangaluru"]},
    {"reason": "Target polymers (HDPE / PP / LDPE / PET)", "points": 3, "terms": ["hdpe"]},
    {"reason": "Buyer / procurement / supplier requirement", "points": 4, "terms": ["procurement"]},
    {"reason": "Tender", "points": 4, "terms": ["tender"]},
]


class TestScoring:
    def test_score_is_the_sum_of_matched_rules(self):
        article = make_article(
            "Udupi tender for recycled HDPE procurement in Karnataka",
            "https://example.com/a",
        )
        score_article(article, RULES)
        assert article.relevance_score == 17

    def test_reasons_are_recorded_and_explain_the_score(self):
        article = make_article("Karnataka buyer issues recycled HDPE procurement notice", "https://example.com/a")
        score_article(article, RULES)
        assert "Karnataka" in article.score_reasons
        assert "Target polymers (HDPE / PP / LDPE / PET)" in article.score_reasons
        assert "Buyer / procurement / supplier requirement" in article.score_reasons
        assert article.relevance_score == 10

    def test_worked_example_from_the_spec(self):
        article = make_article("Karnataka firm seeks recycled HDPE for procurement", "https://example.com/a")
        score_article(article, RULES)
        assert article.relevance_score == 10
        assert article.score_reasons == [
            "Karnataka",
            "Target polymers (HDPE / PP / LDPE / PET)",
            "Buyer / procurement / supplier requirement",
        ]

    def test_a_rule_fires_at_most_once(self):
        repeated = make_article("Karnataka Karnataka Karnataka recycling", "https://example.com/a")
        once = make_article("Karnataka recycling", "https://example.com/b")
        score_article(repeated, RULES)
        score_article(once, RULES)
        assert repeated.relevance_score == once.relevance_score == 3

    def test_irrelevant_article_scores_zero(self):
        article = make_article("A cricket match report", "https://example.com/a")
        score_article(article, RULES)
        assert article.relevance_score == 0
        assert article.score_reasons == []

    def test_description_contributes_to_the_score(self):
        article = make_article("A recycler expands", "https://example.com/a", "The Karnataka plant grows.")
        score_article(article, RULES)
        assert "Karnataka" in article.score_reasons

    def test_wide_syndication_adds_a_capped_bonus(self):
        article = make_article("Karnataka recycling news", "https://example.com/a")
        article.duplicate_count = 5
        score_article(article, RULES)
        assert article.relevance_score == 4
        assert any("Widely reported" in r for r in article.score_reasons)

    def test_score_all_returns_highest_first(self):
        low = make_article("Recycling somewhere", "https://example.com/low")
        high = make_article("Udupi tender for HDPE procurement in Karnataka", "https://example.com/high")
        result = score_all([low, high], RULES)
        assert result[0].url.endswith("high")
        assert result[0].relevance_score > result[1].relevance_score


class TestRealConfigRules:
    def test_coastal_karnataka_buyer_outranks_generic_national_news(self, config):
        rules = config.get("scoring.rules")
        local = make_article(
            "Udupi buyer seeks recycled HDPE granules",
            "https://example.com/local",
            "A Karnataka packaging firm has begun procurement of recycled granules.",
        )
        national = make_article(
            "India plastic waste generation rises",
            "https://example.com/national",
            "A report notes higher waste volumes.",
        )
        score_article(local, rules)
        score_article(national, rules)
        assert local.relevance_score > national.relevance_score
        assert local.relevance_score >= int(config.get("scoring.thresholds.high_priority"))


class TestOpportunityDetection:
    def test_tender_is_flagged(self):
        article = make_article("Udupi floats tender for plastic waste processing", "https://example.com/a")
        article.relevance_score = 9
        detect_opportunity(article)
        assert article.business_opportunity is True
        assert "TENDER" in article.opportunity_type

    def test_buyer_is_flagged(self):
        article = make_article("FMCG firm starts procurement of recycled HDPE", "https://example.com/a")
        article.relevance_score = 11
        detect_opportunity(article)
        assert "BUYER" in article.opportunity_type

    def test_multiple_opportunity_types_are_allowed(self):
        article = make_article(
            "Packaging firm seeks partner for recycled content procurement",
            "https://example.com/a",
        )
        article.relevance_score = 10
        detect_opportunity(article)
        assert {"BUYER", "PARTNERSHIP", "MARKET_DEMAND"} <= set(article.opportunity_type)

    def test_low_scoring_article_is_not_an_opportunity(self):
        article = make_article("Someone mentions a partner in passing", "https://example.com/a")
        article.relevance_score = 1
        detect_opportunity(article)
        assert article.business_opportunity is False
        assert article.opportunity_type == []

    def test_tender_category_alone_implies_an_opportunity(self):
        article = make_article("Civic body invites bids for waste processing", "https://example.com/a")
        article.relevance_score = 6
        article.category = ["TENDER"]
        detect_opportunity(article, rules=[], min_score=4)
        assert article.business_opportunity is True
        assert article.opportunity_type == ["TENDER"]

    def test_detect_all_processes_a_batch(self):
        articles = [make_article("Tender for recycled PP", "https://example.com/a")]
        articles[0].relevance_score = 8
        assert detect_all(articles)[0].business_opportunity is True


class TestEnforcementIsNotAnOpportunity:
    """From the first backfill: a penalty was read as a procurement signal."""

    def test_a_fine_for_buying_waste_is_not_a_buyer_lead(self):
        article = make_article(
            "Ahmedabad Civic Body Fines Scrap Dealer Rs 1 Lakh For Buying Plastic Waste From Garbage",
            "https://example.com/a",
        )
        article.relevance_score = 10
        detect_opportunity(article)
        assert "BUYER" not in article.opportunity_type
        assert article.business_opportunity is False

    def test_a_genuine_procurement_story_is_still_flagged(self):
        article = make_article(
            "FMCG major begins procurement of recycled HDPE granules", "https://example.com/b"
        )
        article.relevance_score = 10
        detect_opportunity(article)
        assert "BUYER" in article.opportunity_type

    def test_a_tender_survives_enforcement_language(self):
        # An authority that fines polluters may also float a tender; the tender
        # is still worth chasing.
        article = make_article(
            "After crackdown on violations, civic body floats tender for plastic waste processing",
            "https://example.com/c",
        )
        article.relevance_score = 9
        detect_opportunity(article)
        assert "TENDER" in article.opportunity_type
        assert article.business_opportunity is True

    def test_suppression_terms_are_configurable(self):
        # With suppression switched off the commercial label comes back.
        title = "Firm raided during procurement of plastic scrap"
        suppressed = make_article(title, "https://example.com/d")
        suppressed.relevance_score = 9
        detect_opportunity(suppressed)
        assert "BUYER" not in suppressed.opportunity_type

        allowed = make_article(title, "https://example.com/e")
        allowed.relevance_score = 9
        detect_opportunity(allowed, suppress_terms=[], suppress_types=[])
        assert "BUYER" in allowed.opportunity_type
