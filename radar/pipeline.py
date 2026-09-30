"""Ana akış: topla → tekilleştir → fiyatla → Claude ile değerlendir → kaydet → bildir."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import timedelta

from . import notify, prices
from .analyze import Analyzer
from .config import DATA, TickerMatcher, load_settings, load_watchlist
from .models import Item, iso, now_utc, parse_iso
from .sources import Context, feeds, kap, reports, social, spk, tcmb

log = logging.getLogger("radar")

FEED = DATA / "feed.json"
STATE = DATA / "state.json"

COLLECTORS = [
    ("KAP + Borsa İstanbul", kap.collect),
    ("SPK Bülteni", spk.collect),
    ("TCMB", tcmb.collect),
    ("SEC EDGAR", feeds.collect_sec),
    ("Google News", feeds.collect_google_news),
    ("Yahoo Finance", feeds.collect_yahoo),
    ("Basın bültenleri", feeds.collect_press_wires),
    ("TR haber RSS", feeds.collect_turkish_rss),
    ("Reddit", feeds.collect_reddit),
    ("StockTwits", social.collect_stocktwits),
    ("X", social.collect_x),
    ("Rapor kutusu", reports.collect),
]

PRIORITY = {"report": 0, "disclosure": 1, "regulator": 1, "macro": 1, "news": 2, "social": 3}


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def title_key(it: Item) -> str:
    """Aynı haberin farklı sitelerdeki kopyalarını yakalamak için kaba anahtar."""
    t = it.title.rsplit(" - ", 1)[0]          # Google News " - Kaynak" ekini at
    t = unicodedata.normalize("NFKD", t.lower())
    t = re.sub(r"[^a-z0-9 ]", "", t)
    words = [w for w in t.split() if len(w) > 2][:10]
    return ",".join(sorted(it.tickers)) + "|" + " ".join(words)


def price_context(item: Item, px: dict[str, dict]) -> str:
    parts = []
    for t in item.tickers:
        p = px.get(t)
        if p:
            parts.append(f"{t}: son {p['last']} {p['currency']}, günlük %{p.get('change_pct')}")
    return "; ".join(parts)


def run() -> dict:
    settings = load_settings()
    stocks = load_watchlist()
    matcher = TickerMatcher(stocks)
    DATA.mkdir(parents=True, exist_ok=True)

    state = _load(STATE, {})
    old = _load(FEED, {})
    feed = [] if old.get("demo") else old.get("items", [])   # örnek veriyi gerçek akışa karıştırma
    seen_ids = dict.fromkeys(state.get("seen", []))  # sıralı küme
    seen_keys = dict.fromkeys(state.get("seen_keys", []))

    lookback = timedelta(hours=int((settings.get("feed") or {}).get("lookback_hours", 48)))
    since = now_utc() - lookback
    if state.get("last_run"):
        since = max(since, parse_iso(state["last_run"]) - timedelta(hours=2))
    ctx = Context(settings=settings, stocks=stocks, matcher=matcher, since=since, seen=set(seen_ids))

    # 1) Topla
    collected: list[Item] = []
    status = []
    for name, fn in COLLECTORS:
        try:
            got = fn(ctx)
            status.append({"name": name, "ok": True, "count": len(got)})
            collected += got
        except Exception as e:
            log.exception("%s toplayıcı hatası", name)
            status.append({"name": name, "ok": False, "count": 0, "error": str(e)[:200]})

    # 2) Tekilleştir
    new: list[Item] = []
    for it in sorted(collected, key=lambda i: (PRIORITY.get(i.source_type, 9), i.published)):
        k = title_key(it)
        if it.id in seen_ids or (it.source_type in ("news", "social") and k in seen_keys):
            continue
        seen_ids[it.id] = None
        seen_keys[k] = None
        new.append(it)
    log.info("Yeni kayıt: %d / toplanan %d", len(new), len(collected))

    # 3) Fiyatlar ve makro seriler
    px = prices.update_all(stocks)
    try:
        macro = tcmb.update_macro(settings)
        status.append({"name": "TCMB EVDS", "ok": True, "count": len((macro or {}).get("series", []))})
    except Exception as e:
        log.exception("EVDS hatası")
        macro = None
        status.append({"name": "TCMB EVDS", "ok": False, "count": 0, "error": str(e)[:200]})
    watch_desc = ", ".join(f"{s.symbol} ({s.name})" for s in stocks)

    # 4) AI değerlendirme — önce rapor & bildirim, sonra en yeni haberler
    analyzer = Analyzer(settings)
    watch = {s.symbol for s in stocks}
    queue = sorted(new, key=lambda i: (PRIORITY.get(i.source_type, 9), -parse_iso(i.published).timestamp()))
    for it in queue:
        if not analyzer.can_run():
            break
        market_wide = it.source_type == "macro" and it.extra.get("tcmb") != "Başkanın Konuşmaları"
        if not (set(it.tickers) & watch) and not market_wide:
            continue
        ctx_text = price_context(it, px)
        if it.source_type == "macro" or not it.tickers:
            ctx_text = (f"Piyasa geneli haber. İzleme listesi: {watch_desc}. "
                        f"Makro: {tcmb.macro_context(macro) or 'yok'}")
        it.analysis = analyzer.assess(it, ctx_text)

    # 5) Birleştir, fiyat tepkisini güncelle, kaydet
    items = [i.to_dict() for i in new] + feed
    horizon = now_utc() - timedelta(days=3)
    for d in items:
        d.get("extra", {}).pop("full_text", None)
        if parse_iso(d["published"]) >= horizon and d.get("tickers"):
            p = px.get(d["tickers"][0])
            if p:
                d["reaction"] = prices.reaction(d["published"], p)
    items.sort(key=lambda d: d["published"], reverse=True)
    items = items[: int((settings.get("feed") or {}).get("keep_items", 600))]

    FEED.write_text(json.dumps({
        "generated": iso(now_utc()),
        "sources": status,
        "watchlist": [{"symbol": s.symbol, "name": s.name, "market": s.market} for s in stocks],
        "ai": {"model": analyzer.model, "enabled": analyzer.enabled, "used": analyzer.used},
        "items": items,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    STATE.write_text(json.dumps({
        "last_run": iso(now_utc()),
        "seen": list(seen_ids)[-8000:],
        "seen_keys": list(seen_keys)[-8000:],
    }, ensure_ascii=False), encoding="utf-8")

    # 6) Bildir
    sent = notify.send([i for i in new if i.analysis], settings.get("notify") or {})
    summary = {"collected": len(collected), "new": len(new), "analyzed": analyzer.used, "notified": sent}
    log.info("Özet: %s", summary)
    return summary
