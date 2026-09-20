"""Tracking of articles already reported, so the same story is not re-run daily.

The store is a small JSON file committed alongside the reports. It is keyed by
the hash of the normalized URL, and additionally records the normalized title so
a story that reappears at a different URL is still recognised.

Retention is enforced on every save: entries older than the configured window
are dropped, and a hard entry cap keeps the file from growing without bound.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import Article


class SeenStore:
    """Load / query / update the seen-article record."""

    def __init__(self, path: str | Path, retention_days: int = 60, max_entries: int = 8000) -> None:
        self.path = Path(path)
        self.retention_days = int(retention_days)
        self.max_entries = int(max_entries)
        self.entries: dict[str, dict] = {}
        self._titles: set[str] = set()

    # -- persistence ------------------------------------------------------
    def load(self) -> "SeenStore":
        """Read the store. A missing or corrupt file is treated as empty.

        A corrupt file must never abort the daily run — the worst case is that
        a few stories are reported twice.
        """
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.entries = {k: v for k, v in raw.get("articles", {}).items() if isinstance(v, dict)}
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                self.entries = {}
        self._titles = {
            entry.get("normalized_title", "")
            for entry in self.entries.values()
            if entry.get("normalized_title")
        }
        return self

    def save(self) -> None:
        self.prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "retention_days": self.retention_days,
            "count": len(self.entries),
            "articles": self.entries,
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- queries ----------------------------------------------------------
    def has_seen(self, article: Article) -> bool:
        if article.article_id in self.entries:
            return True
        return bool(article.normalized_title) and article.normalized_title in self._titles

    def filter_new(self, articles: Iterable[Article]) -> list[Article]:
        """Return only the articles not already recorded.

        Deduplicates within the batch too, so two unseen copies of the same
        story cannot both pass.
        """
        fresh: list[Article] = []
        batch_ids: set[str] = set()
        batch_titles: set[str] = set()
        for article in articles:
            if article.article_id in batch_ids:
                continue
            if article.normalized_title and article.normalized_title in batch_titles:
                continue
            if self.has_seen(article):
                continue
            fresh.append(article)
            batch_ids.add(article.article_id)
            if article.normalized_title:
                batch_titles.add(article.normalized_title)
        return fresh

    # -- updates ----------------------------------------------------------
    def record(self, articles: Iterable[Article], when: datetime | None = None) -> None:
        stamp = (when or datetime.now(timezone.utc)).isoformat()
        for article in articles:
            if not article.article_id:
                continue
            self.entries[article.article_id] = {
                "url": article.url,
                "normalized_title": article.normalized_title,
                "first_seen": self.entries.get(article.article_id, {}).get("first_seen", stamp),
                "last_seen": stamp,
            }
            if article.normalized_title:
                self._titles.add(article.normalized_title)

    def prune(self, now: datetime | None = None) -> int:
        """Drop stale entries; return how many were removed."""
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.retention_days)
        before = len(self.entries)

        kept: dict[str, dict] = {}
        for key, entry in self.entries.items():
            stamp = entry.get("last_seen") or entry.get("first_seen") or ""
            try:
                seen_at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                if seen_at.tzinfo is None:
                    seen_at = seen_at.replace(tzinfo=timezone.utc)
            except ValueError:
                # Undated entries are kept once and stamped now, so they age out.
                entry["last_seen"] = now.isoformat()
                kept[key] = entry
                continue
            if seen_at >= cutoff:
                kept[key] = entry

        if len(kept) > self.max_entries:
            ordered = sorted(
                kept.items(),
                key=lambda kv: kv[1].get("last_seen", ""),
                reverse=True,
            )
            kept = dict(ordered[: self.max_entries])

        self.entries = kept
        self._titles = {
            e.get("normalized_title", "") for e in kept.values() if e.get("normalized_title")
        }
        return before - len(kept)
