"""Alpha Vantage NEWS_SENTIMENT: ABD haberleri + hisse bazında duygu skoru (−1…+1) ve ilgililik.

Ücretsiz plan günde 25 istek (dakikada 5). Bu yüzden her turda en fazla bir istek atılır: ABD hisseleri sırayla
döner (`interval_min` dakikada bir, günde en fazla `max_per_day`). Birden çok sembol verilirse Alpha Vantage
hepsini birlikte anan haberleri döndürdüğü için istek başına tek sembol kullanılır.

Skor Marketaux gibi bir "ikinci görüş"tür: kayıtta `extra.av` olarak saklanır, AI'ın yerine geçmez ve karnede
ayrı bir değerlendirici olarak notlanır. Aynı haber başka kaynaktan geldiyse skor o kayda taşınır.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from .. import http
from ..models import UTC, Item, iso, make_id, now_utc
from . import Context
from .tr_official import _save_state, _state

log = logging.getLogger("radar.alphavantage")

API = "https://www.alphavantage.co/query"
ENVS = ("ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY")


def token() -> str | None:
    return next((os.environ[k] for k in ENVS if os.environ.get(k)), None)


def parse_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        try:
            return datetime.strptime(s, "%Y%m%dT%H%M").replace(tzinfo=UTC)
        except (TypeError, ValueError):
            return None


def to_items(payload: dict, stocks: list, since, min_rel: float = 0.3) -> list[Item]:
    by_sym = {s.symbol: s for s in stocks}
    out = []
    for a in payload.get("feed") or []:
        pub = parse_time(a.get("time_published"))
        if not pub or (since and pub < since):
            continue
        av, tickers = {}, []
        for t in a.get("ticker_sentiment") or []:
            st = by_sym.get(t.get("ticker"))
            try:
                rel, score = float(t.get("relevance_score")), float(t.get("ticker_sentiment_score"))
            except (TypeError, ValueError):
                continue
            if not st or rel < min_rel:
                continue
            tickers.append(st.symbol)
            av[st.symbol] = round(score, 3)
        if not tickers or not a.get("url"):
            continue
        out.append(Item(
            id=make_id("av", a["url"]), source=f"{a.get('source') or 'Alpha Vantage'} · Alpha Vantage",
            source_type="news", market="US", title=a.get("title") or "", summary=a.get("summary") or "",
            url=a["url"], published=iso(pub), tickers=tickers, lang="en", extra={"av": av},
        ))
    return out


def next_symbol(stocks: list, cfg: dict) -> str | None:
    """Sıradaki sembol (günlük sınır ve aralık dolmadıysa); sayaçlar source_state.json'da."""
    if not stocks:
        return None
    st = _state()
    now = now_utc()
    day = now.date().isoformat()
    cnt = st.get("alphavantage_day") or {}
    if cnt.get("date") != day:
        cnt = {"date": day, "n": 0}
    if cnt["n"] >= int(cfg.get("max_per_day", 20)):
        return None
    last = st.get("alphavantage")
    if last and now - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(minutes=float(cfg.get("interval_min", 60))):
        return None
    i = int(st.get("alphavantage_i", 0)) % len(stocks)
    st.update({"alphavantage": iso(now), "alphavantage_i": i + 1, "alphavantage_day": {"date": day, "n": cnt["n"] + 1}})
    _save_state(st)
    return stocks[i].symbol


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("alphavantage")
    key = token()
    if not cfg.get("enabled", True) or not key:
        return []
    stocks = ctx.market("US")
    sym = next_symbol(stocks, cfg)
    if not sym:
        return []
    since = max(ctx.since, now_utc() - timedelta(hours=int(cfg.get("lookback_hours", 24))))
    r = http.get(API, params={"function": "NEWS_SENTIMENT", "tickers": sym, "sort": "LATEST", "limit": 50,
                              "time_from": since.strftime("%Y%m%dT%H%M"), "apikey": key}, timeout=30, retries=1)
    if r is None:
        return []
    try:
        payload = r.json()
    except ValueError:
        http.note_failure(API, "JSON değil")
        return []
    msg = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
    if msg and not payload.get("feed"):
        http.note_failure(API, ("günlük/dakikalık sınır" if "limit" in msg.lower() else msg)[:60])
        return []
    out = to_items(payload, stocks, since, float(cfg.get("min_relevance", 0.3)))
    out = sorted(out, key=lambda i: i.published, reverse=True)[:int(cfg.get("per_request", 8))]
    log.info("Alpha Vantage (%s): %d haber", sym, len(out))
    return out
