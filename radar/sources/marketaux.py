"""Marketaux: şirket bazlı etiketlenmiş haber + Marketaux'nun kendi duygu skoru (−1…+1).

Ücretsiz plan günde 100 istek, istek başına 3 haber. Saatte bir, piyasa başına bir istek (ABD + BIST) atılır.
BIST sembolleri Marketaux'da ".IS" ekiyle (THYAO.IS). Kapsam ABD'de geniş, BIST'te zayıf.

Not: Marketaux'nun skoru sözlük tabanlıdır (ör. "hedef fiyatı düşürdü" haberini olumlu sayabilir). Bu yüzden
AI değerlendirmesinin yerine geçmez; kayıtta `extra.mx` olarak saklanır, panelde ikinci görüş olarak gösterilir
ve karnede ayrı bir "değerlendiren" olarak notlanır.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from .. import http
from ..models import Item, iso, make_id, now_utc, parse_iso
from . import Context
from .tr_official import due

log = logging.getLogger("radar.marketaux")

API = "https://api.marketaux.com/v1/news/all"
ENV = "MARKETAUX_API_TOKEN"


def mx_symbol(st) -> str:
    return f"{st.symbol}.IS" if st.market == "BIST" else st.symbol


def to_items(payload: dict, stocks: list, since) -> list[Item]:
    by_mx = {mx_symbol(s): s for s in stocks}
    out = []
    for a in payload.get("data") or []:
        try:
            pub = parse_iso(a["published_at"].replace(".000000Z", "Z"))
        except (KeyError, ValueError):
            continue
        if since and pub < since:
            continue
        mx, tickers, market = {}, [], None
        for e in a.get("entities") or []:
            st = by_mx.get(e.get("symbol"))
            if not st:
                continue
            if st.symbol not in tickers:
                tickers.append(st.symbol)
                market = market or st.market
            if e.get("sentiment_score") is not None:
                mx[st.symbol] = round(float(e["sentiment_score"]), 3)
        if not tickers:
            continue
        src = a.get("source") or "Marketaux"
        out.append(Item(
            id=make_id("mx", a.get("uuid") or a.get("url", "")), source=f"{src} · Marketaux", source_type="news",
            market=market, title=a.get("title") or "", summary=a.get("description") or a.get("snippet") or "",
            url=a.get("url") or "", published=iso(pub), tickers=tickers, lang=a.get("language") or "en",
            extra={"mx": mx} if mx else {},
        ))
    return out


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("marketaux")
    token = os.environ.get(ENV)
    if not cfg.get("enabled", True) or not token or not due("marketaux", cfg.get("interval_min", 60)):
        return []
    out: list[Item] = []
    since = max(ctx.since, now_utc() - timedelta(hours=int(cfg.get("lookback_hours", 6))))
    for market in ("US", "BIST"):
        stocks = ctx.market(market)
        if not stocks:
            continue
        params = {"symbols": ",".join(mx_symbol(s) for s in stocks), "filter_entities": "true",
                  "must_have_entities": "true", "published_after": since.strftime("%Y-%m-%dT%H:%M"),
                  "limit": int(cfg.get("limit", 3)), "api_token": token}
        if market == "US":
            params["language"] = "en"
        r = http.get(API, params=params, timeout=30, retries=1)
        if r is None:
            continue
        try:
            payload = r.json()
        except ValueError:
            http.note_failure(API, "JSON değil")
            continue
        if payload.get("error"):
            http.note_failure(API, str(payload["error"].get("code") or payload["error"])[:60])
            continue
        out += to_items(payload, stocks, since)
    log.info("Marketaux: %d haber", len(out))
    return out
