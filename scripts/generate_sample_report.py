#!/usr/bin/env python3
"""Render a sample report from committed fixtures — no network required.

Useful for eyeballing report formatting after changing ``src/report.py``, and
for showing newcomers what the output looks like before the first scheduled run.

    python scripts/generate_sample_report.py            # print to stdout
    python scripts/generate_sample_report.py -o docs/sample-report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.classify import classify_all  # noqa: E402
from src.config import load_config  # noqa: E402
from src.deduplicate import deduplicate  # noqa: E402
from src.models import RawItem, RunStats  # noqa: E402
from src.normalize import normalize_item, passes_topic_gate  # noqa: E402
from src.opportunity import detect_all  # noqa: E402
from src.report import build_report  # noqa: E402
from src.score import score_all  # noqa: E402

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sample_items.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", help="write the report here instead of stdout")
    parser.add_argument("--date", default="2026-09-20", help="report date to stamp")
    args = parser.parse_args()

    config = load_config()
    raw = [RawItem(**item) for item in json.loads(FIXTURE.read_text(encoding="utf-8"))]

    subject = config.get("topic_gate.subject_terms", [])
    geo = config.get("topic_gate.geo_terms", [])

    articles = []
    for item in raw:
        article = normalize_item(item)
        if article and passes_topic_gate(f"{article.title} {article.description}", subject, geo):
            articles.append(article)

    stats = RunStats(collected=len(raw), after_topic_gate=len(articles))
    articles = deduplicate(
        articles,
        float(config.get("dedup.title_similarity_threshold", 0.85)),
        int(config.get("dedup.min_shared_tokens", 3)),
        config.get("dedup.preferred_domains", []),
    )
    stats.unique = len(articles)
    stats.new_since_last_run = len(articles)

    articles = classify_all(articles)
    articles = score_all(articles, config.get("scoring.rules", []))
    articles = detect_all(
        articles,
        config.get("opportunities.rules", []),
        int(config.get("opportunities.min_score", 4)),
    )

    relevant = int(config.get("scoring.thresholds.relevant", 4))
    high = int(config.get("scoring.thresholds.high_priority", 8))
    stats.relevant = sum(1 for a in articles if a.relevance_score >= relevant)
    stats.high_priority = sum(1 for a in articles if a.relevance_score >= high)
    stats.opportunities = sum(1 for a in articles if a.business_opportunity)
    stats.sources_ok = ["google_news (7 items)", "rss (2 items)", "government (1 item)"]

    content = build_report(
        articles,
        stats,
        date.fromisoformat(args.date),
        relevant_threshold=relevant,
        high_priority_threshold=high,
        section_floor=int(config.get("scoring.thresholds.section_floor", 2)),
    )

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path}")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
