"""Word-boundary term matching.

These cases are not hypothetical. Every headline marked as a false positive
below actually appeared in the report generated on 2026-09-20, when matching
was a plain substring test: "pp" matched *app*roves, "ps" matched to*ps*,
"pet" matched com*pet*ition and "epr" matched b*egr*un. Railway, highway and
pharmaceutical stories were filed as plastics-recycling intelligence.
"""

from __future__ import annotations

import pytest

from src.matching import contains_any, contains_term, count_matches, matched_terms

# Real headlines from the 2026-09-20 run that must NOT match plastics terms.
REAL_FALSE_POSITIVES = [
    ("Indian Railways approves construction of a four-lane road overbridge", "pp"),
    ("Karnataka ranks third in electric mobility index, tops charging readiness", "ps"),
    ("Mumbai-Goa Highway cost jumps 48% to Rs 16,909 crore: One package up 126%", "ps"),
    ("ENTOD Pharmaceuticals secures patent for its insulin eye drop", "pp"),
    ("Potential US tariffs threaten India's textile, apparel exports", "pet"),
    ("ICAI prepares reforms for creating larger accounting firm networks", "pet"),
    ("Himanta Sarma says ADB talks have begun for high-speed rail network", "epr"),
    ("Nambike Nakshe 2.0 launched in Bengaluru, building approvals automated", "pp"),
    ("Bengaluru passengers welcome government move against advance tipping", "pp"),
    ("Urban local bodies across Bangalore", "ban"),
]

# Genuine matches that must survive the stricter matching.
REAL_TRUE_POSITIVES = [
    ("India PET Weekly: Prices Rise Further on Higher Feedstock Costs", "pet"),
    ("Recycled PP granule prices firm up in western India", "pp"),
    ("EPR targets tightened for brand owners", "epr"),
    ("Government may ban single-use plastic items", "ban"),
    ("A new HDPE recycling line in Udupi", "hdpe"),
]


class TestFalsePositives:
    @pytest.mark.parametrize("headline,term", REAL_FALSE_POSITIVES)
    def test_substring_inside_a_word_does_not_match(self, headline, term):
        assert contains_term(headline, term) is False

    def test_the_whole_junk_set_fails_the_plastics_vocabulary(self):
        vocabulary = ["pp", "ps", "pet", "epr", "hdpe", "ldpe", "plastic", "polymer"]
        for headline, _ in REAL_FALSE_POSITIVES:
            assert not contains_any(headline, vocabulary), headline


class TestTruePositives:
    @pytest.mark.parametrize("headline,term", REAL_TRUE_POSITIVES)
    def test_real_mentions_still_match(self, headline, term):
        assert contains_term(headline, term) is True


class TestPhrases:
    def test_multi_word_phrases_match(self):
        assert contains_term("The Plastic Waste Management Rules were amended", "plastic waste management rules")

    def test_separators_are_interchangeable(self):
        for spelling in ("off-take", "off take", "off_take"):
            assert contains_term(f"signed an {spelling} agreement", "off-take")

    def test_phrase_must_be_contiguous(self):
        assert not contains_term("plastic is a kind of waste", "plastic waste")


class TestCaseAndPunctuation:
    def test_matching_is_case_insensitive(self):
        assert contains_term("RECYCLED hdpe GRANULES", "Recycled HDPE")

    def test_punctuation_next_to_a_term_is_fine(self):
        assert contains_term("grades: HDPE, PP, and LDPE.", "pp")

    def test_digits_adjacent_do_not_match(self):
        assert not contains_term("model PP2000 extruder", "pp")


class TestHelpers:
    def test_matched_terms_preserves_order(self):
        assert matched_terms("HDPE and PP granules", ["pp", "hdpe", "ldpe"]) == ["pp", "hdpe"]

    def test_count_matches(self):
        assert count_matches("HDPE and PP granules", ["pp", "hdpe", "ldpe"]) == 2

    def test_empty_inputs_are_safe(self):
        assert contains_term("", "pp") is False
        assert contains_term("anything", "") is False
        assert contains_any("anything", []) is False
        assert contains_term("anything", "   ") is False
