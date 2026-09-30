"""Şirket Geri Alım sekmesi için güncel fiyatlar.

Geri alım verisi ayrı repodaki takipçiden gelir (kap-geri-alim-takibi). Oradaki son 1 yılda işlem
bildiren hisselerin son kapanışı Yahoo'dan toplu çekilir ve site/data/bb_quotes.json'a yazılır;
panel "Güncel / Ort." sütununu (güncel fiyat ÷ ortalama geri alım fiyatı) bununla doldurur.
Dosya en fazla saatte bir yenilenir."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from . import http
from .config import DATA
from .models import iso, now_utc, parse_iso

log = logging.getLogger(__name__)
FILE = DATA / "bb_quotes.json"
DEFAULT_SRC = "https://raw.githubusercontent.com/gptrade/kap-geri-alim-takibi/main/site/kap-buybacks.json"


def recent_tickers(rows: list[dict], days: int = 365, today: datetime | None = None) -> list[str]:
    cut = ((today or now_utc()) - timedelta(days=days)).date().isoformat()
    out = set()
    for r in rows:
        if not r.get("quantity"):
            continue
        d = r.get("transaction_date") or ""
        if not d:
            p = (r.get("publish_date") or "")[:10]          # "30.09.2026 ..."
            d = f"{p[6:10]}-{p[3:5]}-{p[0:2]}" if len(p) == 10 else ""
        t = (r.get("tickers") or "").replace(",", " ").split()
        if d >= cut and t:
            out.add(t[0].upper())
    return sorted(out)


def download(symbols: list[str]) -> dict[str, dict]:
    """Yahoo'dan son iki kapanış (toplu). Hata olursa boş döner."""
    import yfinance as yf
    if not symbols:
        return {}
    df = yf.download([f"{s}.IS" for s in symbols], period="7d", interval="1d", group_by="ticker",
                     auto_adjust=False, threads=True, progress=False)
    out = {}
    for s in symbols:
        try:
            closes = df[f"{s}.IS"]["Close"].dropna()
        except Exception:
            continue
        if closes.empty:
            continue
        last, prev = float(closes.iloc[-1]), (float(closes.iloc[-2]) if len(closes) > 1 else None)
        out[s] = {"last": round(last, 4), "date": closes.index[-1].strftime("%Y-%m-%d"),
                  "change_pct": round((last / prev - 1) * 100, 2) if prev else None}
    return out


def update(settings: dict, fetcher=download, max_age_min: int = 60) -> dict | None:
    cfg = settings.get("buybacks") or {}
    if cfg.get("quotes") is False:
        return None
    if FILE.exists():
        old = json.loads(FILE.read_text())
        if now_utc() - parse_iso(old["generated"]) < timedelta(minutes=max_age_min):
            return old
    r = http.get(cfg.get("source") or DEFAULT_SRC, timeout=30)
    if r is None:
        raise RuntimeError("geri alım verisi alınamadı")
    rows = r.json()
    syms = recent_tickers(rows)
    quotes = fetcher(syms)
    if not quotes:
        raise RuntimeError(f"{len(syms)} hisse için fiyat alınamadı")
    doc = {"generated": iso(now_utc()), "requested": len(syms), "quotes": quotes}
    FILE.write_text(json.dumps(doc, separators=(",", ":")))
    log.info("Geri alım fiyatları: %d / %d hisse", len(quotes), len(syms))
    return doc
