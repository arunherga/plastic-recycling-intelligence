"""Rule-based classification."""

from __future__ import annotations

import pytest

from src.classify import CATEGORIES, KeywordClassifier, classify_all
from tests.conftest import make_article

CLASSIFIER = KeywordClassifier()


def labels(title: str, description: str = "") -> list[str]:
    return CLASSIFIER.classify(make_article(title, "https://example.com/x", description))


class TestSingleSignals:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Company to set up a plastic recycling plant in Udupi", "NEW_PLANT"),
            ("Recycler announces capacity expansion of 20,000 tonnes per annum", "CAPACITY_EXPANSION"),
            ("BBMP floats e-tender for dry waste processing", "TENDER"),
            ("FMCG firm starts procurement of recycled HDPE granules", "BUYER"),
            ("Ministry issues gazette notification amending waste rules", "REGULATION"),
            ("Brands miss extended producer responsibility targets", "EPR"),
            ("Recycled PP prices rise Rs 4 per kg", "PRICE"),
            ("Startup raises Series B funding for recycling", "INVESTMENT"),
            ("New pyrolysis technology for mixed plastic waste", "TECHNOLOGY"),
            ("Machinery maker launches washing line for PET flakes", "MACHINERY"),
            ("Recycled polymer demand forecast to grow", "MARKET"),
        ],
    )
    def test_expected_label_is_present(self, title, expected):
        assert expected in labels(title)


class TestMultiLabel:
    def test_one_article_can_carry_several_categories(self):
        result = labels(
            "Udupi civic body floats tender as company sets up new recycling plant",
            "The investment will add capacity for recycled HDPE granules.",
        )
        assert {"TENDER", "NEW_PLANT", "INVESTMENT"} <= set(result)

    def test_municipal_contract_counts_as_tender(self):
        assert "TENDER" in labels(
            "Mangaluru civic body signs waste-management contract for dry waste"
        )


class TestFallback:
    def test_unmatched_article_is_other(self):
        assert labels("A quiet day by the sea") == ["OTHER"]

    def test_every_label_is_in_the_vocabulary(self, sample_articles):
        for article in classify_all(sample_articles):
            assert article.category
            assert set(article.category) <= set(CATEGORIES)


class TestReplaceability:
    def test_a_custom_classifier_can_be_substituted(self):
        class AlwaysTender:
            def classify(self, article):
                return ["TENDER"]

        articles = classify_all([make_article("Anything", "https://example.com/a")], AlwaysTender())
        assert articles[0].category == ["TENDER"]
