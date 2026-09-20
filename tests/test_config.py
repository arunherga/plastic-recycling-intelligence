"""Configuration loading and the shape of the committed config.yaml."""

from __future__ import annotations

import pytest

from src.classify import CATEGORIES
from src.config import Config, load_config
from src.opportunity import OPPORTUNITY_TYPES


class TestConfigObject:
    def test_dotted_lookup(self):
        config = Config({"a": {"b": {"c": 1}}})
        assert config.get("a.b.c") == 1

    def test_missing_path_returns_the_default(self):
        config = Config({"a": {}})
        assert config.get("a.b.c", "fallback") == "fallback"
        assert config.get("nope") is None

    def test_relative_paths_resolve_against_the_repo_root(self, tmp_path):
        config = Config({}, root=tmp_path)
        assert config.path("data/seen.json") == tmp_path / "data" / "seen.json"


class TestCommittedConfig:
    def test_all_spec_queries_are_present(self, config):
        expected = {
            "plastic recycling India",
            "recycled HDPE India",
            "plastic recycling Udupi",
            "plastic recycling Mangalore",
            "plastic waste tender Karnataka",
            "CPCB plastic waste",
            "MoEFCC plastic waste",
            "plastic pyrolysis India",
        }
        assert expected <= set(config.queries)

    def test_ai_is_disabled_by_default(self, config):
        assert config.get("ai.enabled") is False

    def test_no_api_keys_are_stored_in_config(self, config):
        # Only the *name* of an env var may appear, never a key value.
        assert config.get("ai.api_key_env") == "OPENAI_API_KEY"
        assert "api_key" not in config.get("ai", {})

    def test_scoring_rules_are_well_formed(self, config):
        for rule in config.get("scoring.rules"):
            assert rule["reason"]
            assert isinstance(rule["points"], int) and rule["points"] > 0
            assert rule["terms"]

    def test_opportunity_types_use_the_documented_vocabulary(self, config):
        for rule in config.get("opportunities.rules"):
            assert rule["type"] in OPPORTUNITY_TYPES

    def test_thresholds_are_ordered_sensibly(self, config):
        floor = int(config.get("scoring.thresholds.section_floor"))
        relevant = int(config.get("scoring.thresholds.relevant"))
        high = int(config.get("scoring.thresholds.high_priority"))
        assert floor <= relevant < high

    def test_category_vocabulary_matches_the_spec(self):
        assert "NEW_PLANT" in CATEGORIES and "OTHER" in CATEGORIES
        assert len(set(CATEGORIES)) == len(CATEGORIES)

    @pytest.mark.parametrize("key", ["google_news", "rss", "government"])
    def test_core_sources_are_enabled(self, config, key):
        assert config.source_enabled(key)
