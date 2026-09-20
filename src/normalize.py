"""Turn whatever a source returned into a clean, comparable ``Article``.

Two jobs matter here, because everything downstream depends on them:

* **URL normalization** — strip tracking junk so the same story fetched from
  two places collapses to one key.
* **Title normalization** — strip the publisher suffix that news aggregators
  bolt on, so headline comparison actually compares headlines.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as date_parser

from .matching import contains_any, contains_term
from .models import Article, RawItem

# Query parameters that never identify content.
TRACKING_PREFIXES = ("utm_", "pk_", "mc_", "ga_", "hsa_", "vero_", "mtm_", "matomo_")
TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "twclid", "yclid",
    "ref", "referrer", "source", "src", "cmpid", "campaign_id", "ito",
    "spm", "share", "shared", "from", "feature", "at_medium", "at_campaign",
    "guccounter", "guce_referrer", "guce_referrer_sig", "__twitter_impression",
    "smid", "partner", "cid", "ncid", "trk", "trkCampaign", "sh",
}

# Publisher suffixes appended to headlines, e.g. "... - The Hindu".
TITLE_SUFFIX_RE = re.compile(r"\s*[|\-–—]\s*[^|\-–—]{2,40}$")
WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
HTML_TAG_RE = re.compile(r"<[^>]+>")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "to", "with",
    "will", "new", "says", "said", "after", "over", "amid", "up", "down",
}


def strip_html(text: str) -> str:
    """Feeds routinely put markup in the description field."""
    if not text:
        return ""
    cleaned = HTML_TAG_RE.sub(" ", text)
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    return WHITESPACE_RE.sub(" ", cleaned).strip()


def normalize_url(url: str) -> str:
    """Return a canonical form of ``url`` suitable for use as an identity key.

    Lower-cases the host, drops ``www.``, drops the fragment, removes tracking
    parameters, sorts what remains, and trims a trailing slash. Anything that
    does not parse as an http(s) URL is returned stripped but otherwise intact
    — better a slightly noisy key than a crash mid-run.
    """
    if not url:
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if parts.scheme not in ("http", "https"):
        return url

    scheme = "https"
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"

    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_PARAMS:
            continue
        if any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        kept.append((key, value))
    query = urlencode(sorted(kept))

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, host, path, query, ""))


def domain_of(url: str) -> str:
    """Bare registrable-ish domain, used for source attribution and ranking."""
    if not url:
        return ""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def strip_descriptionless_tail(description: str, title: str) -> str:
    """Drop a "description" that is really just the headline plus a byline.

    Google News RSS does not carry a summary. Its <description> is the headline
    followed by the publisher's name, so a story from The Times of India ends
    up with the word "India" in its text and one from insightsonindia.com does
    not. Treating that as evidence of geography is how a story about Dubuque,
    Iowa passed an India-only filter. If the description is the title plus a
    short tail, there is no summary here and we say so.
    """
    if not description:
        return ""
    if description == title:
        return ""
    lowered, lowered_title = description.lower(), title.lower()
    if lowered.startswith(lowered_title):
        remainder = description[len(title):].strip(" -–—|·")
        # A real summary continues the story; a byline is a few words.
        return "" if len(remainder) < 80 else remainder
    return description


def normalize_title(title: str) -> str:
    """Collapse a headline to a comparable form.

    Unicode-folded, publisher suffix removed, punctuation dropped, stopwords
    removed, tokens sorted out of the equation only by the caller.
    """
    if not title:
        return ""
    text = unicodedata.normalize("NFKD", strip_html(title))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = TITLE_SUFFIX_RE.sub("", text)
    text = NON_ALNUM_RE.sub(" ", text.lower())
    tokens = [t for t in text.split() if t and t not in STOPWORDS]
    return " ".join(tokens)


def title_tokens(title: str) -> set[str]:
    """Significant tokens of a headline, for cheap pre-filtering in dedup."""
    return {t for t in normalize_title(title).split() if len(t) > 2}


def article_id(url: str) -> str:
    """Stable short identifier derived from the normalized URL."""
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def parse_date(value: Optional[str]) -> Optional[datetime]:
    """Best-effort date parsing; always returns UTC-aware or ``None``."""
    if not value:
        return None
    try:
        parsed = date_parser.parse(str(value))
    except (ValueError, OverflowError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def within_window(
    published: Optional[datetime],
    lookback_hours: int,
    include_undated: bool = True,
    now: Optional[datetime] = None,
) -> bool:
    """Is this item inside the collection window?"""
    if published is None:
        return include_undated
    now = now or datetime.now(timezone.utc)
    # Allow a little slack for feeds with clocks set slightly ahead.
    if published > now + timedelta(hours=6):
        return include_undated
    return published >= now - timedelta(hours=lookback_hours)


# --- locations and keywords ------------------------------------------------

LOCATION_TERMS: dict[str, tuple[str, ...]] = {
    "Udupi": ("udupi", "manipal", "kundapur", "karkala"),
    "Mangaluru": ("mangalore", "mangaluru"),
    "Dakshina Kannada": ("dakshina kannada", "coastal karnataka"),
    "Bengaluru": ("bengaluru", "bangalore", "bbmp"),
    "Karnataka": ("karnataka", "kspcb", "hubballi", "hubli", "dharwad", "mysuru", "mysore", "belagavi", "shivamogga", "tumakuru", "ballari", "kalaburagi"),
    "Kerala": ("kerala", "kochi", "cochin", "thiruvananthapuram", "kozhikode", "kollam", "thrissur", "kannur", "alappuzha", "palakkad"),
    "Goa": ("goa", "panaji", "vasco"),
    "Maharashtra": ("maharashtra", "mumbai", "pune", "nagpur", "nashik", "aurangabad"),
    "Tamil Nadu": ("tamil nadu", "chennai", "coimbatore", "tiruppur", "madurai"),
    "Telangana": ("telangana", "hyderabad"),
    "Andhra Pradesh": ("andhra pradesh", "visakhapatnam", "vijayawada"),
    "Gujarat": ("gujarat", "ahmedabad", "surat", "vapi", "jamnagar"),
    "Delhi NCR": ("delhi", "noida", "gurugram", "gurgaon", "ghaziabad", "faridabad"),
    "West Bengal": ("west bengal", "kolkata"),
    "Rajasthan": ("rajasthan", "jaipur"),
    "Uttar Pradesh": ("uttar pradesh", "lucknow", "kanpur"),
    "India (national)": ("india", "indian", "bharat", "nationwide", "pan-india"),
}

KEYWORD_TERMS: tuple[str, ...] = (
    "hdpe", "ldpe", "lldpe", "pet", "pp", "pvc", "polypropylene", "polyethylene",
    "granule", "pellet", "recyclate", "scrap", "epr", "pyrolysis",
    "chemical recycling", "mechanical recycling", "recycled content",
    "plastic waste management rules", "cpcb", "moefcc", "tender", "plant",
    "capacity", "investment", "machinery", "extrusion", "sorting", "baler",
)


def detect_locations(text: str) -> list[str]:
    """Locations mentioned, most specific first.

    ``"India (national)"`` is only reported when nothing more specific matched,
    so a Udupi story is not also filed as a generic India story.
    """
    found = [
        label
        for label, terms in LOCATION_TERMS.items()
        if label != "India (national)" and contains_any(text, terms)
    ]
    if not found and contains_any(text, LOCATION_TERMS["India (national)"]):
        found.append("India (national)")
    return found


def detect_keywords(text: str) -> list[str]:
    return [kw for kw in KEYWORD_TERMS if contains_term(text, kw)]


def passes_topic_gate(text: str, subject_terms: Iterable[str], geo_terms: Iterable[str]) -> bool:
    """Reject items that are not about our subject *and* our geography.

    Both tests use whole-word matching. With plain substring matching this gate
    was effectively open: "pp" alone admitted anything containing "approves".
    """
    return contains_any(text, subject_terms) and contains_any(text, geo_terms)


def normalize_item(item: RawItem) -> Optional[Article]:
    """Build an :class:`Article` from a :class:`RawItem`.

    Returns ``None`` for items with no usable title or URL rather than letting
    junk through — an article we cannot link to is worthless in a report.
    """
    url = normalize_url(item.url or "")
    title = strip_html(item.title or "").strip()
    if not url or not title:
        return None

    published = parse_date(item.published_at)
    description = strip_descriptionless_tail(strip_html(item.description or ""), title)

    haystack = f"{title} {description}"
    return Article(
        title=title,
        url=url,
        source=item.source or domain_of(url),
        published_at=published.isoformat() if published else "",
        description=description[:600],
        location=detect_locations(haystack),
        category=[],
        keywords=detect_keywords(haystack),
        relevance_score=0,
        article_id=article_id(url),
        normalized_title=normalize_title(title),
        origin=item.origin,
    )
