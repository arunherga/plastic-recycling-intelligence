"""Markdown report generation.

The report is the product. Everything upstream exists so that this file can put
the right dozen items in front of someone deciding what to chase today.

Sections are driven by category and location membership, so an article can
legitimately appear in more than one place (a Karnataka tender belongs in both
"Tenders & Contracts" and the "Karnataka Watch"). Only the opportunity list is
deduplicated against itself, because that is the list people act on.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

from .models import Article, RunStats

REPORT_TITLE = "India Plastic Recycling Intelligence"

COASTAL_KARNATAKA = {"Karnataka", "Udupi", "Mangaluru", "Dakshina Kannada", "Bengaluru"}


# --- small helpers ---------------------------------------------------------

def _fmt_date(value: str) -> str:
    if not value:
        return "date not reported"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value[:10]


def _locations(article: Article) -> str:
    return ", ".join(article.location) if article.location else "India (unspecified)"


def _categories(article: Article) -> str:
    return ", ".join(article.category) if article.category else "OTHER"


def why_it_matters(article: Article) -> str:
    """One-line justification.

    Prefers an AI summary when the optional layer produced one, and otherwise
    builds a sentence out of the same score reasons that produced the number —
    so the explanation and the score can never drift apart.
    """
    if article.ai_summary:
        return article.ai_summary

    parts: list[str] = []
    if article.opportunity_type:
        parts.append("Possible " + " / ".join(t.replace("_", " ").lower() for t in article.opportunity_type) + " opening")
    if article.score_reasons:
        parts.append("scored on " + "; ".join(article.score_reasons[:4]).lower())
    if article.duplicate_count >= 2:
        parts.append(f"carried by {article.duplicate_count + 1} outlets")
    if not parts:
        return "Matched the plastics-recycling watchlist for India."
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def _bullet(article: Article) -> str:
    return (
        f"- **[{article.title}]({article.url})** — {article.source}, {_fmt_date(article.published_at)} "
        f"(score {article.relevance_score}; {_locations(article)})"
    )


def _section(heading: str, articles: Sequence[Article], empty_note: str, limit: int) -> list[str]:
    lines = [f"## {heading}", ""]
    if not articles:
        lines += [f"_{empty_note}_", ""]
        return lines
    lines += [_bullet(a) for a in articles[:limit]]
    if len(articles) > limit:
        lines.append(f"- _…and {len(articles) - limit} more in `data/daily/`._")
    lines.append("")
    return lines


def _has_category(article: Article, *categories: str) -> bool:
    return any(c in article.category for c in categories)


# --- report ----------------------------------------------------------------

def build_report(
    articles: Iterable[Article],
    stats: RunStats,
    report_date: date | None = None,
    max_top_opportunities: int = 10,
    max_items_per_section: int = 12,
    max_investigate_items: int = 10,
    relevant_threshold: int = 4,
    high_priority_threshold: int = 8,
    section_floor: int = 2,
) -> str:
    """Render the full daily Markdown report."""
    report_date = report_date or date.today()
    items = sorted(articles, key=lambda a: (-a.relevance_score, a.published_at or ""), reverse=False)
    items.sort(key=lambda a: a.relevance_score, reverse=True)

    relevant = [a for a in items if a.relevance_score >= relevant_threshold]
    opportunities = [a for a in items if a.business_opportunity]
    # Thematic sections use a lower bar than the headline "relevant" count: an
    # on-topic technology or machinery item is still worth listing even when it
    # earns no geography points.
    pool = [a for a in items if a.relevance_score >= min(section_floor, relevant_threshold)]

    lines: list[str] = [
        f"# {REPORT_TITLE}",
        "",
        f"**Date:** {report_date.isoformat()}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        f"- **Articles scanned:** {stats.collected}",
        f"- **Unique articles after deduplication:** {stats.unique}",
        f"- **New since last run:** {stats.new_since_last_run}",
        f"- **Relevant articles (score ≥ {relevant_threshold}):** {stats.relevant}",
        f"- **High-priority articles (score ≥ {high_priority_threshold}):** {stats.high_priority}",
        f"- **Business opportunities flagged:** {stats.opportunities}",
        "",
    ]

    # --- Top opportunities -------------------------------------------------
    lines += ["## Top Opportunities", ""]
    if not opportunities:
        lines += ["_No business opportunities cleared the threshold today._", ""]
    else:
        for article in opportunities[:max_top_opportunities]:
            lines += [
                f"### {article.title}",
                "",
                f"- **Location:** {_locations(article)}",
                f"- **Category:** {_categories(article)}",
                f"- **Opportunity Type:** {', '.join(article.opportunity_type)}",
                f"- **Relevance Score:** {article.relevance_score}"
                + (f" ({'; '.join(article.score_reasons)})" if article.score_reasons else ""),
                f"- **Why it matters:** {why_it_matters(article)}",
                f"- **Source:** {article.source}, {_fmt_date(article.published_at)}",
                f"- **URL:** {article.url}",
                "",
            ]

    # --- Thematic sections -------------------------------------------------
    lines += _section(
        "Major Industry Developments",
        [a for a in pool if _has_category(a, "NEW_PLANT", "CAPACITY_EXPANSION", "INVESTMENT", "COMPANY_NEWS")],
        "No significant plant, capacity, investment or corporate news today.",
        max_items_per_section,
    )

    lines += _section(
        "Buyers & Market Demand",
        [a for a in pool if _has_category(a, "BUYER", "SELLER", "MARKET", "PRICE")],
        "No buyer, procurement or demand signals today.",
        max_items_per_section,
    )

    lines += _section(
        "Regulation & EPR",
        [a for a in pool if _has_category(a, "REGULATION", "EPR")],
        "No regulatory or EPR developments today.",
        max_items_per_section,
    )

    lines += _section(
        "Tenders & Contracts",
        [a for a in pool if _has_category(a, "TENDER")],
        "No tenders or municipal contracts surfaced today.",
        max_items_per_section,
    )

    lines += _section(
        "Technology & Machinery",
        [a for a in pool if _has_category(a, "TECHNOLOGY", "MACHINERY")],
        "No notable technology or machinery news today.",
        max_items_per_section,
    )

    lines += _section(
        "Karnataka / Coastal Karnataka Watch",
        [a for a in items if COASTAL_KARNATAKA & set(a.location)],
        "Nothing specific to Karnataka or the coastal belt today.",
        max_items_per_section,
    )

    # --- Worth investigating ----------------------------------------------
    # Items that scored meaningfully but landed in no thematic section, plus
    # anything with strong local signal that the rules could not categorise.
    covered_categories = {
        "NEW_PLANT", "CAPACITY_EXPANSION", "INVESTMENT", "COMPANY_NEWS",
        "BUYER", "SELLER", "MARKET", "PRICE", "REGULATION", "EPR",
        "TENDER", "TECHNOLOGY", "MACHINERY",
    }
    investigate = [
        a
        for a in items
        if a.relevance_score >= min(section_floor, relevant_threshold)
        and not (covered_categories & set(a.category))
    ]
    lines += _section(
        "Articles Worth Investigating",
        investigate,
        "Nothing extra flagged for manual research today.",
        max_investigate_items,
    )

    # --- Run diagnostics ---------------------------------------------------
    lines += ["## Run Diagnostics", ""]
    if stats.sources_ok:
        lines.append("**Sources completed:** " + ", ".join(stats.sources_ok))
        lines.append("")
    if stats.source_errors:
        lines += ["**Source issues (run continued regardless):**", ""]
        lines += [f"- {err}" for err in stats.source_errors[:25]]
        if len(stats.source_errors) > 25:
            lines.append(f"- _…and {len(stats.source_errors) - 25} more._")
        lines.append("")
    else:
        lines += ["_All configured sources responded without error._", ""]
    if stats.source_notes:
        lines += ["**Source notes (not failures):**", ""]
        lines += [f"- {note}" for note in stats.source_notes[:25]]
        if len(stats.source_notes) > 25:
            lines.append(f"- _…and {len(stats.source_notes) - 25} more._")
        lines.append("")

    lines += [
        "---",
        "",
        "_Generated automatically by the "
        "[plastic-recycling-intelligence](https://github.com/arunherga/plastic-recycling-intelligence) "
        "agent. Scores and categories are rule-based and explainable; verify anything before acting on it._",
        "",
    ]

    return "\n".join(lines)


def write_report(content: str, output_dir: str | Path, report_date: date | None = None) -> Path:
    report_date = report_date or date.today()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report_date.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path
