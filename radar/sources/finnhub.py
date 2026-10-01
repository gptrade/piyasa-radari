"""Finnhub: ABD şirket haberleri (ücretsiz plan).

Ücretsiz planda şirket haberi yalnızca Kuzey Amerika şirketleri için var; dakikada 60 istek sınırı.
Finnhub'ın haber duygu skoru ücretli planda olduğu için burada yalnız haber kaynağı olarak kullanılır;
değerlendirmeyi AI yapar. Her ABD hissesi için tek istek, `interval_min` dakikada bir.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from .. import http
from ..models import UTC, Item, iso, make_id, now_utc
from . import Context
from .tr_official import due

log = logging.getLogger("radar.finnhub")

API = "https://finnhub.io/api/v1"
ENVS = ("FINNHUB_API_KEY", "FINNHUB_TOKEN", "FINNHUB_KEY", "FINNHUB_API_TOKEN")


def token() -> str | None:
    return next((os.environ[k] for k in ENVS if os.environ.get(k)), None)


def to_items(rows: list, st, since) -> list[Item]:
    out = []
    for a in rows or []:
        try:
            pub = datetime.fromtimestamp(int(a["datetime"]), UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if since and pub < since:
            continue
        title, url = (a.get("headline") or "").strip(), a.get("url") or ""
        if not title or not url:
            continue
        src = (a.get("source") or "Finnhub").strip()
        out.append(Item(
            id=make_id("fh", str(a.get("id") or url)), source=f"{src} · Finnhub", source_type="news", market="US",
            title=title, summary=a.get("summary") or "", url=url, published=iso(pub), tickers=[st.symbol], lang="en",
        ))
    return out


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("finnhub")
    key = token()
    if not cfg.get("enabled", True) or not key or not due("finnhub", cfg.get("interval_min", 30)):
        return []
    since = max(ctx.since, now_utc() - timedelta(hours=int(cfg.get("lookback_hours", 24))))
    to = now_utc().date()
    out: list[Item] = []
    per = int(cfg.get("per_symbol", 8))
    for st in ctx.market("US"):
        r = http.get(f"{API}/company-news", params={"symbol": st.symbol, "from": (to - timedelta(days=1)).isoformat(),
                                                     "to": to.isoformat(), "token": key}, timeout=30, retries=1)
        if r is None:
            continue
        try:
            rows = r.json()
        except ValueError:
            http.note_failure(API, "JSON değil")
            continue
        if isinstance(rows, dict):                      # {"error": "..."}
            http.note_failure(API, str(rows.get("error") or rows)[:60])
            continue
        got = sorted(to_items(rows, st, since), key=lambda i: i.published, reverse=True)[:per]
        out += got
    log.info("Finnhub: %d haber", len(out))
    return out
