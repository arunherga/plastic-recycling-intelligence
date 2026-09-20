"""Historical backfill: time slicing and what a survey is allowed to ask."""

from __future__ import annotations

from datetime import date

import pytest

from src.backfill import Window, build_windows, preamble
from src.sources.base import HttpClient
from src.sources.google_news import GoogleNewsSource

TODAY = date(2026, 9, 20)

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Recycler expands HDPE capacity in Karnataka</title>
<link>https://news.google.com/rss/articles/CBMiTEST</link>
<pubDate>Fri, 19 Sep 2026 06:30:00 +0530</pubDate></item>
</channel></rss>"""


class RecordingClient(HttpClient):
    """Captures every URL requested so slicing can be asserted."""

    def __init__(self, empty: bool = False) -> None:
        super().__init__(delay=0)
        self.urls: list[str] = []
        self.empty = empty

    def get(self, url, **kwargs):
        self.urls.append(url)

        class R:
            content = b'<?xml version="1.0"?><rss><channel></channel></rss>' if self.empty else FEED

        return R()

    def sleep(self):
        return None


class TestWindows:
    def test_two_years_splits_into_monthly_slices(self):
        windows = build_windows(730, 30, TODAY)
        assert len(windows) == 25
        assert windows[0].end > windows[0].start

    def test_slices_are_contiguous_with_no_gaps_or_overlap(self):
        windows = build_windows(365, 30, TODAY)
        for newer, older in zip(windows, windows[1:]):
            assert newer.start == older.end

    def test_the_survey_never_reaches_further_back_than_asked(self):
        windows = build_windows(100, 30, TODAY)
        assert windows[-1].start == date(2026, 6, 12)
        assert (TODAY - windows[-1].start).days == 100

    def test_most_recent_slice_comes_first(self):
        windows = build_windows(90, 30, TODAY)
        assert windows[0].start > windows[-1].start

    def test_todays_news_is_included(self):
        assert build_windows(30, 30, TODAY)[0].end > TODAY

    @pytest.mark.parametrize("days", [0, -1, -400])
    def test_a_non_positive_period_produces_no_slices(self, days):
        assert build_windows(days, 30, TODAY) == []

    def test_a_silly_slice_size_is_clamped_to_one_day(self):
        # 10 days back plus today itself is 11 single-day slices.
        windows = build_windows(10, 0, TODAY)
        assert len(windows) == 11
        assert all((w.end - w.start).days == 1 for w in windows)

    def test_query_suffix_uses_date_operators(self):
        window = Window(date(2025, 1, 1), date(2025, 2, 1))
        assert window.as_query_suffix() == "after:2025-01-01 before:2025-02-01"


class TestWindowedFetching:
    def test_one_request_per_query_per_slice(self):
        client = RecordingClient()
        windows = build_windows(90, 30, TODAY)
        source = GoogleNewsSource({}, client, ["query a", "query b"], 100, windows)
        source.fetch()
        assert len(client.urls) == len(windows) * 2

    def test_every_request_carries_its_slice_dates(self):
        client = RecordingClient()
        windows = build_windows(60, 30, TODAY)
        GoogleNewsSource({}, client, ["plastic recycling India"], 100, windows).fetch()
        assert all("after%3A" in u and "before%3A" in u for u in client.urls)

    def test_the_rolling_when_operator_is_not_used_in_a_backfill(self):
        client = RecordingClient()
        windows = build_windows(60, 30, TODAY)
        GoogleNewsSource({"when": "7d"}, client, ["q"], 100, windows).fetch()
        assert not any("when%3A" in u for u in client.urls)

    def test_daily_mode_still_uses_the_rolling_window(self):
        client = RecordingClient()
        GoogleNewsSource({"when": "7d"}, client, ["q"]).fetch()
        assert len(client.urls) == 1
        assert "when%3A7d" in client.urls[0]

    def test_each_slice_reports_how_much_it_found(self):
        source = GoogleNewsSource({}, RecordingClient(), ["q"], 100, build_windows(60, 30, TODAY))
        source.fetch()
        assert any("slice" in note and "items" in note for note in source.notes)

    def test_a_completely_empty_backfill_is_flagged_as_a_failure(self):
        # If every slice is empty the date operators were probably ignored,
        # which would otherwise look like "there was simply no news for 2 years".
        source = GoogleNewsSource(
            {}, RecordingClient(empty=True), ["q"], 100, build_windows(60, 30, TODAY)
        )
        source.fetch()
        assert any("date filtering may not be applied" in e for e in source.errors)


class TestPreamble:
    def test_it_states_the_limits_up_front(self):
        text = preamble(730, build_windows(730, 30, TODAY), 28)
        assert "not a complete archive" in text
        assert "730 days" in text
        assert "no archive" in text

    def test_it_names_the_period_covered(self):
        windows = build_windows(365, 30, TODAY)
        assert windows[-1].start.isoformat() in preamble(365, windows, 28)
