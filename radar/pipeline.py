"""Ana akış: topla → tekilleştir → fiyatla → Claude ile değerlendir → kaydet → bildir."""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import timedelta

from . import digest, http, notify, prices
from .enrich import enrich
from .analyze import Analyzer
from .config import DATA, TickerMatcher, load_settings, load_watchlist
from .models import Item, iso, now_utc, parse_iso
from .sources import Context, feeds, kap, reports, social, spk, tcmb

log = logging.getLogger("radar")

# Toplama kuralları geriye dönük değiştiğinde artır: eski akış ve "görüldü" listesi sıfırlanır.
DATA_VERSION = 2

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
            ta = prices.ta_context(p)
            parts.append(f"{t}: son {p['last']} {p['currency']}, günlük %{p.get('change_pct')}"
                         + (f"; teknik: {ta}" if ta else ""))
    return "; ".join(parts)


def run() -> dict:
    settings = load_settings()
    stocks = load_watchlist()
    matcher = TickerMatcher(stocks)
    DATA.mkdir(parents=True, exist_ok=True)

    state = _load(STATE, {})
    if state.get("version") != DATA_VERSION:
        log.info("Veri sürümü %s → %s: akış sıfırlanıyor", state.get("version"), DATA_VERSION)
        state = {}
        FEED.unlink(missing_ok=True)
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
        n0 = len(http.FAILURES)
        try:
            got = fn(ctx)
            entry = {"name": name, "ok": True, "count": len(got)}
            fails = http.FAILURES[n0:]
            if fails:
                from collections import Counter
                c = Counter(f"{host}: {why}" for host, why in fails)
                entry["warnings"] = [f"{k} (×{v})" if v > 1 else k for k, v in c.most_common(4)]
            status.append(entry)
            collected += got
        except Exception as e:
            log.exception("%s toplayıcı hatası", name)
            status.append({"name": name, "ok": False, "count": 0, "error": str(e)[:200]})

    # 2) Tekilleştir
    new: list[Item] = []
    dup_hits: dict[str, list[str]] = {}          # tekrar eden haber → hangi kaynaklarda
    for it in sorted(collected, key=lambda i: (PRIORITY.get(i.source_type, 9), i.published)):
        k = title_key(it)
        it.extra["k"] = k
        if it.id in seen_ids:
            continue
        if it.source_type in ("news", "social") and k in seen_keys:
            dup_hits.setdefault(k, []).append(it.source.split(" · ")[0])
            seen_ids[it.id] = None
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
        k = d.get("extra", {}).get("k")
        if k in dup_hits:
            d["dups"] = d.get("dups", 0) + len(dup_hits[k])
            srcs = d.get("dup_sources", []) + [x for x in dup_hits[k] if x not in d.get("dup_sources", [])]
            d["dup_sources"] = srcs[:6]
        enrich(d)
        if parse_iso(d["published"]) >= horizon and d.get("tickers"):
            p = px.get(d["tickers"][0])
            if p:
                idx = px.get(prices.INDEXES[d.get("market", "BIST")].symbol) if d.get("market") in prices.INDEXES else None
                d["reaction"] = prices.reaction(d["published"], p, idx)
    items.sort(key=lambda d: d["published"], reverse=True)
    items = items[: int((settings.get("feed") or {}).get("keep_items", 600))]

    FEED.write_text(json.dumps({
        "generated": iso(now_utc()),
        "sources": status,
        "watchlist": [{"symbol": s.symbol, "name": s.name, "market": s.market} for s in stocks],
        "ai": analyzer.status(),
        # Sadece tanımlı olup olmadıkları (değerler asla yazılmaz)
        "secrets": {k: bool(os.environ.get(k)) for k in (
            "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SEC_USER_AGENT",
            "EVDS_API_KEY", "X_BEARER_TOKEN")},
        "items": items,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    STATE.write_text(json.dumps({
        "version": DATA_VERSION,
        "telegram_hello": state.get("telegram_hello"),
        "last_run": iso(now_utc()),
        "seen": list(seen_ids)[-8000:],
        "seen_keys": list(seen_keys)[-8000:],
    }, ensure_ascii=False), encoding="utf-8")

    # 5b) Dönemsel özet (son 2 saat; az sinyal varsa pencere genişler)
    try:
        dg = digest.update(analyzer, items, px)
        if dg is not None:
            feed_doc = json.loads(FEED.read_text(encoding="utf-8"))
            feed_doc["ai"] = analyzer.status()
            FEED.write_text(json.dumps(feed_doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    except Exception:
        log.exception("Özet hatası")

    # 6) Bildir
    state_extra: dict = {}
    tg_n0 = len(http.FAILURES)
    sent = notify.send([i for i in new if i.analysis], settings.get("notify") or {})
    summary = {"collected": len(collected), "new": len(new), "analyzed": analyzer.used, "notified": sent}
    if not state.get("telegram_hello") and notify.send_hello(summary, analyzer.status()):
        state_extra["telegram_hello"] = iso(now_utc())
    tg_fail = http.FAILURES[tg_n0:]
    tg_entry = {"name": "Telegram", "ok": not tg_fail, "count": sent}
    if tg_fail:
        tg_entry["error"] = "; ".join(f"{h}: {w}" for h, w in tg_fail)[:200]
    elif not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")):
        tg_entry["warnings"] = ["TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanımlı değil"]
    status.append(tg_entry)
    feed_doc = json.loads(FEED.read_text(encoding="utf-8"))
    feed_doc["sources"] = status
    FEED.write_text(json.dumps(feed_doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if state_extra:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        st.update(state_extra)
        STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    log.info("Özet: %s", summary)
    return summary
