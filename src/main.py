"""Pipeline entry point.

    sources -> collect -> normalize -> topic gate -> window filter
            -> deduplicate -> seen filter -> classify -> score
            -> opportunity detection -> (optional AI) -> report

Run locally with ``python -m src.main``. Every stage is a plain function from
its own module, so any one of them can be replaced without touching this file.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .backfill import build_windows, preamble
from .classify import classify_all
from .config import Config, load_config
from .deduplicate import deduplicate
from .models import Article, RunStats
from .normalize import normalize_item, parse_date, passes_topic_gate, within_window
from .opportunity import detect_all
from .report import build_report, write_report
from .resolve import resolve_article_urls
from .score import score_all
from .seen import SeenStore
from .sources import build_sources, collect
from .sources.base import HttpClient
from .sources.google_news import GoogleNewsSource

LOG = logging.getLogger("plastic_recycling_intelligence")


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def prune_daily_files(directory: Path, retention_days: int, now: datetime | None = None) -> int:
    """Delete day files older than the retention window. Returns count removed."""
    if not directory.exists() or retention_days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=retention_days)).date()
    removed = 0
    for path in directory.glob("*.json"):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def run(
    config: Config,
    report_date: date | None = None,
    dry_run: bool = False,
    backfill_days: int = 0,
    slice_days: int = 0,
) -> int:
    """Execute one cycle. Returns the number of reported articles.

    With ``backfill_days`` set this becomes a historical survey instead of a
    daily run: only the search source is consulted (nothing else has an
    archive), each query is asked once per slice of time, and the output goes
    to a separate backfill report so the daily series stays untouched.
    """
    report_date = report_date or datetime.now(timezone.utc).date()
    stats = RunStats()
    backfill = backfill_days > 0
    windows = []
    if backfill:
        slice_days = slice_days or int(config.get("backfill.slice_days", 30))
        windows = build_windows(backfill_days, slice_days, report_date)
        LOG.info(
            "backfill over %d days in %d slice(s) of %d days; %d queries = %d requests",
            backfill_days, len(windows), slice_days, len(config.queries),
            len(windows) * len(config.queries),
        )

    # -- 1. collect -------------------------------------------------------
    delay = float(config.get("app.request_delay_seconds", 1.0))
    if backfill:
        delay = float(config.get("backfill.request_delay_seconds", delay))
    client = HttpClient(
        user_agent=config.user_agent,
        timeout=config.http_timeout,
        retries=int(config.get("app.http_retries", 2)),
        delay=delay,
    )
    if backfill:
        # RSS and government pages carry days of history, not years. Asking
        # them during a backfill would add today's news to a survey of 2024.
        sources = [
            GoogleNewsSource(
                config.source_config("google_news"),
                client,
                config.queries,
                int(config.get("backfill.max_items_per_slice", 100)),
                windows,
            )
        ]
    else:
        sources = build_sources(config, client)
    LOG.info("collecting from %d enabled source(s)", len(sources))
    item_cap = int(
        config.get("backfill.max_items_total", 20000)
        if backfill
        else config.get("collection.max_items_total", 600)
    )
    raw_items, errors, notes, ok = collect(sources, item_cap)
    stats.collected = len(raw_items)
    stats.source_errors = errors
    stats.source_notes = notes
    stats.sources_ok = ok
    LOG.info("collected %d raw items (%d source issues)", len(raw_items), len(errors))

    # -- 2. normalize + gate ---------------------------------------------
    subject_terms = config.get("topic_gate.subject_terms", []) or []
    geo_terms = config.get("topic_gate.geo_terms", []) or []
    lookback = int(config.get("collection.lookback_hours", 48))
    gov_lookback = int(config.get("sources.government.lookback_hours", lookback))
    query_lookback = int(config.get("collection.lookback_hours_news_queries", lookback))
    if backfill:
        # The slices already bound the period; the local filter must not undo it.
        lookback = query_lookback = gov_lookback = backfill_days * 24 + 24
    include_undated = bool(config.get("collection.include_undated", True))

    articles: list[Article] = []
    for item in raw_items:
        article = normalize_item(item)
        if article is None:
            continue
        if not passes_topic_gate(
            f"{article.title} {article.description}", subject_terms, geo_terms
        ):
            continue
        if item.origin.startswith("government:"):
            window = gov_lookback
        elif item.origin.startswith(("google_news:", "bing_news:")):
            window = query_lookback
        else:
            window = lookback
        if not within_window(parse_date(article.published_at), window, include_undated):
            continue
        articles.append(article)

    stats.after_topic_gate = len(articles)
    LOG.info("%d items passed the topic gate and collection window", len(articles))

    # -- 3. deduplicate ---------------------------------------------------
    articles = deduplicate(
        articles,
        title_similarity_threshold=float(config.get("dedup.title_similarity_threshold", 0.85)),
        min_shared_tokens=int(config.get("dedup.min_shared_tokens", 3)),
        preferred_domains=config.get("dedup.preferred_domains", []) or [],
    )
    stats.unique = len(articles)
    LOG.info("%d unique articles after deduplication", len(articles))

    # -- 4. drop what we already reported ---------------------------------
    store = SeenStore(
        config.path(str(config.get("storage.seen_articles_path", "data/seen_articles.json"))),
        retention_days=int(config.get("storage.seen_retention_days", 60)),
        max_entries=int(config.get("storage.seen_max_entries", 8000)),
    ).load()
    articles = store.filter_new(articles)
    stats.new_since_last_run = len(articles)
    LOG.info("%d articles are new since the last run", len(articles))

    # -- 5. classify, score, detect opportunities -------------------------
    articles = classify_all(articles)
    articles = score_all(articles, config.get("scoring.rules", []) or [])
    articles = detect_all(
        articles,
        config.get("opportunities.rules", []) or [],
        int(config.get("opportunities.min_score", 4)),
    )

    # Aggregator links are resolved only for articles that can reach the
    # report, so the cost stays at a few dozen requests rather than hundreds.
    section_floor = int(config.get("scoring.thresholds.section_floor", 2))
    if bool(config.get("collection.resolve_redirect_urls", True)):
        resolvable = [a for a in articles if a.relevance_score >= section_floor]
        LOG.info("resolving publisher URLs for %d article(s)", len(resolvable))
        _, resolved_n, attempted_n = resolve_article_urls(
            resolvable, client, int(config.get("collection.max_resolve", 40))
        )
        if attempted_n:
            stats.source_notes.append(
                f"url resolution: {resolved_n} of {attempted_n} aggregator links "
                "resolved to the publisher's own address"
            )

    relevant_threshold = int(config.get("scoring.thresholds.relevant", 4))
    high_threshold = int(config.get("scoring.thresholds.high_priority", 8))
    stats.relevant = sum(1 for a in articles if a.relevance_score >= relevant_threshold)
    stats.high_priority = sum(1 for a in articles if a.relevance_score >= high_threshold)
    stats.opportunities = sum(1 for a in articles if a.business_opportunity)
    LOG.info(
        "%d relevant, %d high-priority, %d opportunities",
        stats.relevant, stats.high_priority, stats.opportunities,
    )

    # -- 6. optional AI enrichment (no-op when disabled) ------------------
    from .ai import build_summarizer  # local import keeps AI fully optional

    summarizer = build_summarizer(config.get("ai", {}) or {})
    if summarizer.enabled:
        LOG.info("AI enrichment enabled; summarising top articles only")
        articles = summarizer.summarize(articles)

    # -- 7. report --------------------------------------------------------
    scope = "backfill" if backfill else "report"
    content = build_report(
        articles,
        stats,
        report_date=report_date,
        max_top_opportunities=int(config.get(f"{scope}.max_top_opportunities", 10)),
        max_items_per_section=int(config.get(f"{scope}.max_items_per_section", 12)),
        max_investigate_items=int(config.get(f"{scope}.max_investigate_items", 10)),
        relevant_threshold=relevant_threshold,
        high_priority_threshold=high_threshold,
        section_floor=section_floor,
    )
    if backfill:
        content = preamble(backfill_days, windows, len(config.queries)) + content

    if dry_run:
        LOG.info("dry run: report not written, seen store not updated")
        print(content)
        return len(articles)

    if backfill:
        directory = config.path(str(config.get("backfill.output_dir", "reports/backfill")))
        directory.mkdir(parents=True, exist_ok=True)
        oldest = windows[-1].start.isoformat() if windows else report_date.isoformat()
        report_path = directory / f"{oldest}_to_{report_date.isoformat()}.md"
        report_path.write_text(content, encoding="utf-8")
    else:
        report_path = write_report(
            content, config.path(str(config.get("report.output_dir", "reports"))), report_date
        )
    LOG.info("wrote %s", report_path)

    # -- 8. persist normalized data and the seen record -------------------
    if bool(config.get("report.write_daily_json", True)):
        daily_dir = config.path(
            str(
                config.get("backfill.data_dir", "data/backfill")
                if backfill
                else config.get("report.daily_json_dir", "data/daily")
            )
        )
        daily_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": report_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats.to_dict(),
            "articles": [a.to_dict() for a in articles],
        }
        stem = (
            f"{windows[-1].start.isoformat()}_to_{report_date.isoformat()}"
            if backfill and windows
            else report_date.isoformat()
        )
        daily_path = daily_dir / f"{stem}.json"
        daily_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        removed = (
            0
            if backfill
            else prune_daily_files(
                daily_dir, int(config.get("storage.daily_json_retention_days", 120))
            )
        )
        LOG.info("wrote %s (pruned %d old day files)", daily_path, removed)

    if backfill and not bool(config.get("backfill.update_seen", True)):
        LOG.info("backfill: leaving the seen-article store untouched")
    else:
        store.record(articles)
        store.save()
    LOG.info("seen store now holds %d entries", len(store.entries))

    return len(articles)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily plastic-recycling intelligence agent for India."
    )
    parser.add_argument("--config", help="path to config.yaml", default=None)
    parser.add_argument("--date", help="report date as YYYY-MM-DD (default: today, UTC)", default=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the report instead of writing files or updating the seen store",
    )
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=0,
        help="survey this many days of history instead of running the daily cycle "
             "(e.g. 730 for two years); search source only",
    )
    parser.add_argument(
        "--slice-days",
        type=int,
        default=0,
        help="size of each backfill time slice in days (default from config)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)
    config = load_config(args.config)
    report_date = date.fromisoformat(args.date) if args.date else None

    try:
        run(
            config,
            report_date=report_date,
            dry_run=args.dry_run,
            backfill_days=max(0, args.backfill_days),
            slice_days=max(0, args.slice_days),
        )
    except Exception:  # noqa: BLE001
        LOG.exception("run failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
