"""Seen-article filtering and retention."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.seen import SeenStore
from tests.conftest import make_article


def store(tmp_path, **kwargs) -> SeenStore:
    return SeenStore(tmp_path / "seen.json", **kwargs).load()


class TestFiltering:
    def test_first_run_lets_everything_through(self, tmp_path):
        s = store(tmp_path)
        articles = [
            make_article("Udupi tender", "https://example.com/a"),
            make_article("Bengaluru funding", "https://example.com/b"),
        ]
        assert len(s.filter_new(articles)) == 2

    def test_second_run_drops_what_was_already_reported(self, tmp_path):
        s = store(tmp_path)
        first = [make_article("Udupi tender", "https://example.com/a")]
        s.record(s.filter_new(first))
        s.save()

        again = store(tmp_path)
        repeat = [
            make_article("Udupi tender", "https://example.com/a"),
            make_article("New story", "https://example.com/new"),
        ]
        fresh = again.filter_new(repeat)
        assert len(fresh) == 1
        assert fresh[0].url.endswith("/new")

    def test_same_story_at_a_different_url_is_recognised(self, tmp_path):
        s = store(tmp_path)
        s.record([make_article("Udupi awards plastic waste tender", "https://thehindu.com/a")])
        s.save()

        again = store(tmp_path)
        syndicated = make_article("Udupi awards plastic waste tender", "https://deccanherald.com/b")
        assert again.filter_new([syndicated]) == []

    def test_tracking_parameters_do_not_defeat_the_filter(self, tmp_path):
        s = store(tmp_path)
        s.record([make_article("A story", "https://example.com/a")])
        s.save()
        again = store(tmp_path)
        assert again.filter_new([make_article("A story", "https://example.com/a?utm_source=x")]) == []

    def test_duplicates_within_one_batch_are_collapsed(self, tmp_path):
        s = store(tmp_path)
        batch = [
            make_article("Same headline here", "https://a.example/1"),
            make_article("Same headline here", "https://b.example/2"),
        ]
        assert len(s.filter_new(batch)) == 1


class TestPersistence:
    def test_file_is_written_in_a_readable_shape(self, tmp_path):
        s = store(tmp_path)
        s.record([make_article("Udupi tender", "https://example.com/a")])
        s.save()
        data = json.loads((tmp_path / "seen.json").read_text())
        assert data["count"] == 1
        entry = next(iter(data["articles"].values()))
        assert entry["url"] == "https://example.com/a"
        assert entry["first_seen"] and entry["last_seen"]

    def test_first_seen_is_preserved_across_reruns(self, tmp_path):
        s = store(tmp_path)
        article = make_article("Udupi tender", "https://example.com/a")
        old = datetime(2026, 9, 1, tzinfo=timezone.utc)
        s.record([article], when=old)
        s.record([article], when=datetime(2026, 9, 10, tzinfo=timezone.utc))
        entry = s.entries[article.article_id]
        assert entry["first_seen"] == old.isoformat()
        assert entry["last_seen"] != entry["first_seen"]

    def test_corrupt_file_is_treated_as_empty(self, tmp_path):
        path = tmp_path / "seen.json"
        path.write_text("{ this is not json")
        s = SeenStore(path).load()
        assert s.entries == {}
        assert len(s.filter_new([make_article("Anything", "https://example.com/a")])) == 1

    def test_missing_file_is_fine(self, tmp_path):
        s = SeenStore(tmp_path / "nested" / "seen.json").load()
        assert s.entries == {}
        s.record([make_article("A", "https://example.com/a")])
        s.save()
        assert (tmp_path / "nested" / "seen.json").exists()


class TestRetention:
    def test_entries_older_than_the_window_are_dropped(self, tmp_path):
        s = store(tmp_path, retention_days=30)
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        s.record([make_article("Old", "https://example.com/old")], when=now - timedelta(days=90))
        s.record([make_article("Recent", "https://example.com/recent")], when=now - timedelta(days=2))
        removed = s.prune(now=now)
        assert removed == 1
        assert len(s.entries) == 1

    def test_hard_cap_keeps_the_most_recent_entries(self, tmp_path):
        s = store(tmp_path, retention_days=3650, max_entries=10)
        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        for i in range(25):
            s.record(
                [make_article(f"Story {i}", f"https://example.com/{i}")],
                when=now - timedelta(minutes=i),
            )
        s.prune(now=now)
        assert len(s.entries) == 10

    def test_pruning_runs_on_every_save(self, tmp_path):
        s = store(tmp_path, retention_days=1)
        s.record(
            [make_article("Ancient", "https://example.com/ancient")],
            when=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        s.save()
        assert json.loads((tmp_path / "seen.json").read_text())["count"] == 0

    def test_an_undated_entry_is_stamped_rather_than_kept_forever(self, tmp_path):
        path = tmp_path / "seen.json"
        path.write_text(json.dumps({"articles": {"abc": {"url": "https://example.com/x"}}}))
        s = SeenStore(path, retention_days=30).load()
        s.prune()
        assert s.entries["abc"]["last_seen"]
