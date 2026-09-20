"""Optional AI enrichment.

Version 1 runs entirely without this package. Nothing in the collection,
normalization, dedup, classification or scoring path imports it except through
:func:`build_summarizer`, which returns a no-op when ``ai.enabled`` is false.

When AI *is* enabled, only the highest-scoring handful of articles is sent to
the model — never the full collected set.
"""

from __future__ import annotations

from .summarizer import NullSummarizer, Summarizer, build_summarizer

__all__ = ["Summarizer", "NullSummarizer", "build_summarizer"]
