"""Ortak veri modeli ve yardımcılar."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

UTC = timezone.utc


@dataclass
class Item:
    source: str                 # "KAP", "SEC EDGAR", "Google News", ...
    source_type: str            # disclosure | news | social | report
    market: str                 # BIST | US
    title: str
    url: str
    published: str              # ISO-8601 UTC
    tickers: list[str] = field(default_factory=list)
    summary: str = ""
    lang: str = "en"
    extra: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    analysis: dict[str, Any] | None = None
    reaction: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.title = clean_text(self.title)
        self.summary = clean_text(self.summary)[:1200]
        if not self.id:
            self.id = make_id(self.source, self.url or self.title)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip().lower() for p in parts).encode()).hexdigest()[:16]


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(_TAG_RE.sub(" ", s))
    return _WS_RE.sub(" ", s).strip()


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
