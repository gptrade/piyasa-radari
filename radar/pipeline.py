"""Ana akış: topla → tekilleştir → fiyatla → Claude ile değerlendir → kaydet → bildir."""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta

from . import digest, http, notify, prices
from .enrich import enrich
from .analyze import Analyzer
from .config import DATA, TickerMatcher, load_settings, load_watchlist
from .models import UTC, Item, iso, now_utc, parse_iso
from . import anomaly, bb_quotes, bist_data, calendar_events, scorecard
from .sources import Context, feeds, finnhub, kap, marketaux, reports, social, spk, tcmb, tr_official, vendors

log = logging.getLogger("radar")

# Toplama kuralları geriye dönük değiştiğinde artır: eski akış ve "görüldü" listesi sıfırlanır.
DATA_VERSION = 2

FEED = DATA / "feed.json"
STATE = DATA / "state.json"

COLLECTORS = [
    ("KAP + Borsa İstanbul", kap.collect),
    ("SPK Bülteni", spk.collect),
    ("TCMB", tcmb.collect),
    ("TÜİK", tr_official.collect_tuik),
    ("BDDK", tr_official.collect_bddk),
    ("Resmi Gazete", tr_official.collect_resmi_gazete),
    ("Borsa İstanbul duyuruları", tr_official.collect_bist_announcements),
    ("SPK duyuruları", tr_official.collect_spk_press),
    ("Hazine (haber)", tr_official.collect_hazine),
    ("SEC EDGAR", feeds.collect_sec),
    ("Google News", feeds.collect_google_news),
    ("Yahoo Finance", feeds.collect_yahoo),
    ("Marketaux", marketaux.collect),
    ("Finnhub", finnhub.collect),
    ("Basın bültenleri", feeds.collect_press_wires),
    ("TR haber RSS", feeds.collect_turkish_rss),
    ("Reddit", feeds.collect_reddit),
    ("StockTwits", social.collect_stocktwits),
    ("X", social.collect_x),
    ("Rapor kutusu", reports.collect),
    ("Matriks", vendors.collect_matriks),
    ("Foreks", vendors.collect_foreks),
]

SECOND_OPINIONS = ("mx", "av")   # extra içindeki dış duygu skorları: Marketaux, Alpha Vantage

PRIORITY = {"report": 0, "disclosure": 1, "regulator": 1, "macro": 1, "news": 2, "social": 3, "technical": 4}


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


def earnings_items(stocks, px: dict, days_ahead: int) -> list[Item]:
    from datetime import date
    from .models import make_id
    out = []
    today = now_utc().date()
    for st in stocks:
        ne = (px.get(st.symbol) or {}).get("next_earnings")
        if not ne:
            continue
        d = date.fromisoformat(ne["date"])
        if not (0 <= (d - today).days <= days_ahead):
            continue
        est = f" · EPS beklentisi {ne['eps_est']}" if ne.get("eps_est") is not None else ""
        gun = d.strftime("%d.%m.%Y")
        out.append(Item(
            id=make_id("earn", st.symbol, ne["date"]), source="Kazanç takvimi", source_type="news",
            market=st.market, title=f"{st.symbol} bilançosu {gun} tarihinde bekleniyor{est}",
            summary=f"{st.name} için bir sonraki finansal sonuç açıklaması {gun}.{est}",
            url=f"https://finance.yahoo.com/quote/{st.yahoo}/", published=iso(now_utc()),
            tickers=[st.symbol], lang="tr", extra={"earnings_date": ne["date"], "no_ai": True,
                                                   "eps_est": ne.get("eps_est")},
        ))
    return out


# Anahtarı olmadan çalışmayan kaynaklar: tanımlı değilse "kapalı" gösterilir (hata sayılmaz)
NEEDS_KEY = {"X": "X_BEARER_TOKEN", "TCMB EVDS": "EVDS_API_KEY", "Matriks": "MATRIKS_API_KEY", "Foreks": "FOREKS_USERNAME",
             "Marketaux": "MARKETAUX_API_TOKEN", "Finnhub": "FINNHUB_API_KEY"}


def source_health(status: list[dict], prev: dict, now: str | None = None) -> dict:
    """Her kaynak için son başarılı çekim ve son veri gelen zamanı günceller; status girdilerine yazar.
    Dönen sözlük state.json'da saklanır (tur başına sayılar sıfırlansa da geçmiş kaybolmaz)."""
    now = now or iso(now_utc())
    out = {}
    for e in status:
        h = dict(prev.get(e["name"]) or {})
        key = NEEDS_KEY.get(e["name"])
        if key and not os.environ.get(key):
            e["disabled"] = f"{key} tanımlı değil"
        elif e.get("ok") and not (e.get("warnings") and not e.get("count")):
            h["last_ok"] = now
        if e.get("ok") and e.get("count"):
            h["last_data"] = now
        e.update({k: v for k, v in h.items() if v})
        out[e["name"]] = h
    return out


def technical_items(stocks: list, px: dict) -> list[Item]:
    """Fiyat dosyasındaki teknik olaylardan akış kaydı üretir. Kimlik hisse + olay türü + bar tarihinden
    türetilir; aynı gün aynı olay ikinci kez gelmez (seen_ids)."""
    out = []
    for st in stocks:
        p = px.get(st.symbol) or {}
        for ev in p.get("events") or []:
            url = f"https://www.tradingview.com/chart/?symbol={st.tv}#teknik-{ev['key']}-{ev['bar']}"
            sent = {1: "bullish", -1: "bearish"}.get(ev["dir"], "neutral")
            out.append(Item(
                source="Teknik analiz", source_type="technical", market=st.market,
                title=f"{st.symbol}: {ev['title']}", url=url, published=iso(now_utc()), tickers=[st.symbol],
                summary=ev["what"], lang="tr",
                extra={"no_ai": True, "tech": ev["key"], "bar": ev["bar"], "live": ev.get("live", False)},
                analysis={"sentiment": sent, "confidence": ev["confidence"], "materiality": ev["materiality"],
                          "horizon": "days", "category": "Teknik", "event_label": ev.get("label") or ev["title"],
                          "headline_tr": ev["title"], "what": ev["what"], "why": ev["why"], "risk": ev["risk"],
                          "summary": "", "affected_tickers": [st.symbol], "provider": "kural (teknik)"},
            ))
    return out


GRADE_DIR = (("strong buy", 1), ("outperform", 1), ("overweight", 1), ("buy", 1), ("accumulate", 1),
             ("positive", 1), ("add", 1), ("strong sell", -1), ("underperform", -1), ("underweight", -1),
             ("sell", -1), ("reduce", -1), ("negative", -1))


def grade_dir(grade: str) -> int:
    g = (grade or "").lower()
    return next((d for k, d in GRADE_DIR if k in g), 0)


def analyst_items(stocks: list, px: dict, max_age_days: int = 3) -> list[Item]:
    """Yahoo analist not değişikliklerinden akış kaydı (kural tabanlı, AI kotası harcamaz)."""
    from datetime import date
    from .models import make_id
    out = []
    today = now_utc().date()
    for st in stocks:
        p = px.get(st.symbol) or {}
        cur = p.get("currency") or ""
        for c in ((p.get("analyst") or {}).get("changes") or []):
            try:
                d = date.fromisoformat(c["date"])
            except (KeyError, ValueError):
                continue
            if (today - d).days > max_age_days or not c.get("firm"):
                continue
            act = c.get("action") or ""
            if act == "up":
                sdir = 1
            elif act == "down":
                sdir = -1
            elif act == "init":
                sdir = grade_dir(c.get("to"))
            else:
                sdir = 0
            pt = c.get("pt")
            ptp = c.get("pt_prev")
            if pt and ptp and act in ("main", "reit") and abs(pt / ptp - 1) >= 0.03:
                sdir = 1 if pt > ptp else -1                     # not aynı, hedef fiyat belirgin değişti
            verb = prices.ACTION_TR.get(act, "güncelledi")
            grade = f"{c['from']} → {c['to']}" if c.get("from") and act in ("up", "down") else (c.get("to") or "")
            pt_txt = ""
            if pt:
                pt_txt = f"; hedef {pt:g} {cur}" + (f" (önce {ptp:g})" if ptp and ptp != pt else "")
            last = p.get("last")
            upside = f", son fiyata göre %{(pt / last - 1) * 100:+.0f}" if pt and last else ""
            when = "" if d >= today else f" ({d.strftime('%d.%m')})"
            title = f"{c['firm']}, {st.symbol} notunu {verb}{when}: {grade}{pt_txt}".replace(": ;", ":")
            label = {"up": "Not artırımı", "down": "Not indirimi", "init": "Kapsama başladı"}.get(act, "Analist notu")
            if act in ("main", "reit") and sdir:
                label = "Hedef yükseltildi" if sdir > 0 else "Hedef düşürüldü"
            what = f"{c['firm']} notu {grade or 'aynı'}{pt_txt}{upside}"
            out.append(Item(
                id=make_id("anl", st.symbol, c["firm"], c["date"], c.get("to") or "", str(pt or "")),
                source="Yahoo Finance · Analist", source_type="news", market=st.market, title=title,
                summary=what, url=f"https://finance.yahoo.com/quote/{st.yahoo}/analysis/",
                # Akış en yeni N kaydı tuttuğu için eski tarihli not kesilip kaybolmasın: bulunduğu an
                published=iso(now_utc()),
                tickers=[st.symbol], lang="tr",
                extra={"no_ai": True, "analyst": act or "note", "firm": c["firm"], "pt": pt, "grade_date": c["date"]},
                analysis={"sentiment": {1: "bullish", -1: "bearish"}.get(sdir, "neutral"),
                          "confidence": 70 if act in ("up", "down") else 60,
                          "materiality": "medium" if sdir else "low", "horizon": "weeks", "category": "Analist",
                          "event_label": label, "headline_tr": title, "what": what,
                          "why": "Aracı kurum görüş değişiklikleri kısa vadede fiyatı etkileyebilir; tek kurumun görüşü, "
                                 "konsensüsle birlikte değerlendirilmeli.",
                          "risk": "Analist notları geriden gelebilir; hedef fiyatlar sık revize edilir.",
                          "summary": "", "affected_tickers": [st.symbol], "provider": "kural (analist)"},
            ))
    return out


MAT_RANK = {"high": 3, "medium": 2, "low": 1}


def _value(d: dict) -> tuple:
    """Kayıt değeri (küçük = önce atılır): önem, kaynak kalitesi, tazelik."""
    a = d.get("analysis") or {}
    return (MAT_RANK.get(a.get("materiality"), 0), -(d.get("tier") or 3), d.get("published", ""))


def _protected(d: dict) -> bool:
    """Resmi bildirim/birincil kaynak ya da yüksek önemli kayıt kotaya takılmaz (yaş sınırı hariç)."""
    return d.get("tier") == 1 and d.get("source_type") != "technical" or \
        (d.get("analysis") or {}).get("materiality") == "high"


def retain(items: list[dict], watch: set[str], total: int = 800, max_per_ticker: int = 90,
           min_per_ticker: int = 25, max_age_days: int = 30) -> list[dict]:
    """Akışta tutulacak kayıtlar. Salt "en yeni N" yerine hisse başına denge:
    - çok haber üreten hisse (ör. NVDA) en fazla `max_per_ticker` kayıt tutar; fazlası önce düşük önemli,
      zayıf kaynaklı ve eski olanlardan atılır (resmi bildirim ve yüksek önemli kayıtlar korunur),
    - az haber alan hisse (ör. küçük BIST hissesi) son `min_per_ticker` kaydını eski de olsa korur,
    - toplam `total`'ı aşarsa, en düşük değerli kayıtlar en kalabalık hisselerden atılır.
    """
    horizon = iso(now_utc() - timedelta(days=max_age_days))
    items = sorted((d for d in items if d.get("published", "") >= horizon), key=lambda d: d["published"], reverse=True)

    def key(d):
        return next((t for t in d.get("tickers") or [] if t in watch), "_genel")

    groups: dict[str, list[dict]] = {}
    for d in items:
        groups.setdefault(key(d), []).append(d)
    keep: dict[str, list[dict]] = {}
    for k, g in groups.items():                       # g: yeniden eskiye
        prot = [d for d in g if _protected(d)]
        rest = sorted((d for d in g if not _protected(d)), key=_value, reverse=True)
        keep[k] = prot + rest[: max(0, max_per_ticker - len(prot))]
    n = sum(len(v) for v in keep.values())
    if n > total:                                     # en kalabalık gruptan en düşük değerliyi at
        pools = {k: sorted((d for d in v if not _protected(d)), key=_value) for k, v in keep.items()}
        while n > total:
            k = max(pools, key=lambda x: (len(keep[x]) if pools[x] and len(keep[x]) > min_per_ticker else -1))
            if not pools[k] or len(keep[k]) <= min_per_ticker:
                break
            drop = pools[k].pop(0)
            keep[k] = [d for d in keep[k] if d is not drop]
            n -= 1
    out = [d for v in keep.values() for d in v]
    out.sort(key=lambda d: d["published"], reverse=True)
    return out


def fair_order(queue: list[Item], watch: set[str]) -> list[Item]:
    """AI kotasını hisseler arasında adil dağıt: öncelik sınıfı (bildirim, rapor, haber…) korunur,
    her sınıfın içinde hisseler sırayla birer kayıt alır (her hissenin en yenisi önce).
    Böylece çok haber üreten bir hisse (ör. NVDA) turun kotasını tek başına tüketmez."""
    out: list[Item] = []
    i = 0
    while i < len(queue):
        pri = PRIORITY.get(queue[i].source_type, 9)
        j = i
        buckets: dict[str, list[Item]] = {}
        while j < len(queue) and PRIORITY.get(queue[j].source_type, 9) == pri:
            it = queue[j]
            key = next((t for t in it.tickers if t in watch), it.tickers[0] if it.tickers else "_genel")
            buckets.setdefault(key, []).append(it)
            j += 1
        while buckets:
            for k in list(buckets):
                out.append(buckets[k].pop(0))
                if not buckets[k]:
                    del buckets[k]
        i = j
    return out


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
    second: dict[str, dict] = {}                 # kopyalardan gelen dış duygu skorları
    for it in sorted(collected, key=lambda i: (PRIORITY.get(i.source_type, 9), i.published)):
        k = title_key(it)
        it.extra["k"] = k
        if it.id in seen_ids:
            continue
        if it.source_type in ("news", "social") and k in seen_keys:
            dup_hits.setdefault(k, []).append(it.source.split(" · ")[0])
            for sk in SECOND_OPINIONS:             # kopya atılsa da dış skoru (Marketaux vb.) asıl kayda taşı
                if it.extra.get(sk):
                    second.setdefault(k, {}).setdefault(sk, {}).update(it.extra[sk])
            seen_ids[it.id] = None
            continue
        seen_ids[it.id] = None
        seen_keys[k] = None
        new.append(it)
    log.info("Yeni kayıt: %d / toplanan %d", len(new), len(collected))

    # 3) Fiyatlar ve makro seriler
    acfg = (settings.get("sources") or {}).get("analyst") or {}
    px = prices.update_all(stocks, float(acfg.get("refresh_hours", 6)) if acfg.get("enabled", True) else None)
    try:
        macro = tcmb.update_macro(settings)
        status.append({"name": "TCMB EVDS", "ok": True, "count": len((macro or {}).get("series", []))})
    except Exception as e:
        log.exception("EVDS hatası")
        macro = None
        status.append({"name": "TCMB EVDS", "ok": False, "count": 0, "error": str(e)[:200]})
    scfg = (settings.get("sources") or {}).get("bist_bulletin") or {}
    flows = {}
    if scfg.get("enabled", True) and any(s.market == "BIST" for s in stocks):
        try:                                                # Borsa İstanbul günlük bülteni: açığa satış
            flows = bist_data.update_flows(stocks)
            status.append({"name": "BIST bülteni", "ok": True, "count": len(flows.get("summary") or {})})
        except Exception as e:
            log.exception("BIST bülteni hatası")
            status.append({"name": "BIST bülteni", "ok": False, "count": 0, "error": str(e)[:200]})
    agm = []
    if scfg.get("agm", True) and any(s.market == "BIST" for s in stocks):
        try:
            agm = bist_data.agm_events(stocks, bist_data.agm_list())
        except Exception as e:
            log.warning("Genel kurul listesi alınamadı: %s", e)
    try:                                                    # Takvim: makro, vade sonu, bilanço, temettü, genel kurul
        calendar_events.update(stocks, px, extra=agm)
    except Exception as e:
        log.warning("Takvim oluşturulamadı: %s", e)
    try:                                                    # Şirket Geri Alım: güncel / ortalama fiyat için
        bb_quotes.update(settings)
    except Exception as e:
        log.warning("Geri alım fiyatları alınamadı: %s", e)
    watch_desc = ", ".join(f"{s.symbol} ({s.name})" for s in stocks)

    # 3a) Teknik olaylar: haber olmasa da EMA kesişimi, RSI eşiği, 52 hafta zirve/dip, hacim patlaması
    tcfg = (settings.get("sources") or {}).get("technical") or {}
    if tcfg.get("enabled", True):
        n_tech = 0
        for it in technical_items(stocks, px):
            if it.id not in seen_ids:
                seen_ids[it.id] = None
                new.append(it)
                n_tech += 1
        status.append({"name": "Teknik sinyaller", "ok": True, "count": n_tech})

    # 3a'') Habersiz hareket: endeksten arındırılmış olağandışı hareket, ilgili önemli haber/bildirim yokken
    ncfg = (settings.get("sources") or {}).get("anomaly") or {}
    if ncfg.get("enabled", True):
        n_an = 0
        recent = [i.to_dict() for i in new] + feed
        for d in recent:
            enrich(d)
        for it in anomaly.anomaly_items(stocks, px, recent, ncfg):
            if it.id not in seen_ids:
                seen_ids[it.id] = None
                new.append(it)
                n_an += 1
        status.append({"name": "Habersiz hareket", "ok": True, "count": n_an})

    # 3c) Açığa satış artışı (BIST bülteni)
    if flows:
        for it in bist_data.flow_items(stocks, flows, scfg):
            if it.id not in seen_ids:
                seen_ids[it.id] = None
                new.append(it)

    # 3a') Analist not değişiklikleri (Yahoo): kural tabanlı, AI kotası harcamaz
    if acfg.get("enabled", True):
        n_an = 0
        for it in analyst_items(stocks, px, int(acfg.get("max_age_days", 3))):
            if it.id not in seen_ids:
                seen_ids[it.id] = None
                new.append(it)
                n_an += 1
        status.append({"name": "Analist notları", "ok": True, "count": n_an})

    # 3b) Yaklaşan bilançolar (Yahoo takvimi): N gün kala akışa bir kayıt
    ecfg = (settings.get("sources") or {}).get("earnings_calendar") or {}
    n_earn = 0
    if ecfg.get("enabled", True):
        for e in earnings_items(stocks, px, int(ecfg.get("days_ahead", 7))):
            if e.id not in seen_ids:
                seen_ids[e.id] = None
                new.append(e)
                n_earn += 1
        status.append({"name": "Kazanç takvimi", "ok": True, "count": n_earn})

    # 4) AI değerlendirme — önce rapor & bildirim, sonra en yeni haberler
    analyzer = Analyzer(settings)
    watch = {s.symbol for s in stocks}
    queue = fair_order(sorted(new, key=lambda i: (PRIORITY.get(i.source_type, 9), -parse_iso(i.published).timestamp())), watch)
    for it in queue:
        if not analyzer.can_run():
            break
        if it.extra.get("no_ai"):
            continue
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
        for sk, v in (second.get(k) or {}).items():
            d["extra"].setdefault(sk, {}).update({t: x for t, x in v.items() if t not in d["extra"][sk]})
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
    fcfg = settings.get("feed") or {}
    items = retain(items, {s.symbol for s in stocks}, total=int(fcfg.get("keep_items", 800)),
                   max_per_ticker=int(fcfg.get("max_per_ticker", 90)), min_per_ticker=int(fcfg.get("min_per_ticker", 25)),
                   max_age_days=int(fcfg.get("max_age_days", 30)))

    # 5a) Sinyal arşivi ve karnesi (yönlü sinyaller 1 ve 5 seans sonra endekse göre notlanır)
    try:
        scorecard.update(items, px, {s.symbol for s in stocks})
    except Exception as e:
        log.exception("Karne hatası")
        status.append({"name": "Sinyal karnesi", "ok": False, "count": 0, "error": str(e)[:200]})

    FEED.write_text(json.dumps({
        "generated": iso(now_utc()),
        "sources": status,
        "watchlist": [{"symbol": s.symbol, "name": s.name, "market": s.market, "tv": s.tv} for s in stocks],
        "ai": analyzer.status(),
        # Sadece tanımlı olup olmadıkları (değerler asla yazılmaz)
        "secrets": {k: bool(os.environ.get(k)) for k in (
            "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SEC_USER_AGENT",
            "EVDS_API_KEY", "X_BEARER_TOKEN", "MATRIKS_API_KEY", "FOREKS_USERNAME", "MARKETAUX_API_TOKEN", "FINNHUB_API_KEY")},
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
    state_extra["src"] = source_health(status, state.get("src") or {})
    feed_doc = json.loads(FEED.read_text(encoding="utf-8"))
    feed_doc["sources"] = status
    FEED.write_text(json.dumps(feed_doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if state_extra:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        st.update(state_extra)
        STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    log.info("Özet: %s", summary)
    return summary
