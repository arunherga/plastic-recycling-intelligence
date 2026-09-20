"""Historical backfill support.

A daily agent looks at the last day or two. A backfill answers a different
question: *what has happened in this market over the last two years?*

The honest constraint is that almost nothing in the free-source layer has an
archive. An RSS feed carries whatever is on its current page — twenty or fifty
items, days to weeks of history, never years. The one source with any reach
backwards is Google News search, and it only goes back if you ask one slice of
time at a time: a single query returns roughly a hundred results however wide
the window, so "two years" asked in one request returns two years' worth of
*the hundred most relevant* items, not two years of coverage.

So a backfill walks the period in slices, issuing one query per slice, and
stitches the results together. Twenty-eight queries over twenty-four monthly
slices is 672 requests — which is why this runs on demand and never on the
daily schedule.

What comes back is genuinely historical but not complete, and it is weighted
towards what Google indexed and ranked. It is a survey, not an archive, and
the report says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Window:
    """A half-open slice of time, ``start`` inclusive to ``end`` exclusive."""

    start: date
    end: date

    @property
    def label(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"

    def as_query_suffix(self) -> str:
        """Google News date operators for this slice.

        ``after:`` and ``before:`` are what give a search-based source any
        historical reach; ``when:`` only ever looks backwards from today.
        """
        return f"after:{self.start.isoformat()} before:{self.end.isoformat()}"


def build_windows(days: int, slice_days: int = 30, today: date | None = None) -> list[Window]:
    """Split the last ``days`` days into slices, most recent first.

    The final slice is truncated rather than extended, so a backfill never
    reaches further back than it was asked to.
    """
    if days <= 0:
        return []
    slice_days = max(1, int(slice_days))
    today = today or date.today()
    earliest = today - timedelta(days=days)

    windows: list[Window] = []
    end = today + timedelta(days=1)  # include anything published today
    while end > earliest:
        start = max(end - timedelta(days=slice_days), earliest)
        windows.append(Window(start, end))
        end = start
    return windows


def preamble(days: int, windows: list[Window], queries: int) -> str:
    """The caveat block that opens a backfill report.

    A reader must not mistake a survey for an archive, so the limits are
    stated at the top rather than buried in a footnote.
    """
    span = ""
    if windows:
        span = f" ({windows[-1].start.isoformat()} to {windows[0].end.isoformat()})"
    return (
        f"> **Historical survey, not a complete archive.**\n"
        f">\n"
        f"> This is a backfill over the last {days} days{span}, assembled by running "
        f"{queries} queries across {len(windows)} time slices of Google News search.\n"
        f">\n"
        f"> Coverage is necessarily partial. RSS and government sources have no "
        f"archive — they carry days of history, not years — so they contribute "
        f"nothing here. Google News returns a bounded number of results per query, "
        f"ranks by its own relevance rather than completeness, and drops articles "
        f"whose publishers have since removed them. Older months will look thinner "
        f"than recent ones, and that reflects the index, not the market.\n"
        f">\n"
        f"> Treat absence of a story as unproven, not as evidence it did not happen.\n\n"
    )
