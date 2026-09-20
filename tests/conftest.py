"""Shared test fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.config import load_config  # noqa: E402
from src.models import Article, RawItem  # noqa: E402
from src.normalize import normalize_item  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "sample_items.json"


@pytest.fixture(scope="session")
def config():
    return load_config(REPO_ROOT / "config.yaml")


@pytest.fixture
def raw_items() -> list[RawItem]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [RawItem(**item) for item in data]


@pytest.fixture
def sample_articles(raw_items) -> list[Article]:
    return [a for a in (normalize_item(i) for i in raw_items) if a is not None]


def make_article(title: str, url: str, description: str = "", **kwargs) -> Article:
    """Build a fully normalized Article from loose parts, for focused tests."""
    article = normalize_item(RawItem(title=title, url=url, description=description))
    assert article is not None
    for key, value in kwargs.items():
        setattr(article, key, value)
    return article
