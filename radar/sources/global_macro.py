"""Küresel makro: merkez bankaları (Fed, ECB), kurum haberleri (IMF, yaptırımlar) ve GDELT haber hacmi/ton alarmı.

Merkez bankaları: resmi RSS akışları. Faiz kararı / politika metni yüksek önemli işaretlenir ve metni sayfadan
alınıp AI'a verilir. Konuşmalarda yalnız para politikası ve ekonomiyle ilgili başlıklar alınır (düzenleme,
ödeme sistemleri, yapay zekâ konuşmaları akışa girmez).

ABD Hazinesi/OFAC ve IMF RSS'leri otomatik erişimi engellediği için (403/404) bu ikisi Google News konu
aramasıyla izlenir: IMF'in Türkiye değerlendirmeleri ve Türkiye'yi ilgilendiren yaptırım haberleri.

GDELT (api.gdeltproject.org, ücretsiz, anahtarsız): dünya basınının 15 dakikalık haber sayısı ve ortalama
tonu. Her tema için son 2 saatin haber payı önceki 3 günün olağan payıyla, tonu 3 günlük ortalamayla
karşılaştırılır. Hacim birkaç katına çıkar ya da ton belirgin biçimde bozulursa akışa bir makro kayıt düşer
(öne çıkan başlıklarla birlikte); AI bunun izleme listesine etkisini değerlendirir.
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from .. import http
from ..models import UTC, Item, iso, make_id, now_utc, parse_iso
from . import Context
from .feeds import entries_to_items, fetch_feed
from .tr_official import _save_state, _state, due

log = logging.getLogger("radar.global")

# ------------------------------------------------------------------ merkez bankaları
FED_MONETARY = "https://www.federalreserve.gov/feeds/press_monetary.xml"
FED_SPEECHES = "https://www.federalreserve.gov/feeds/speeches.xml"
ECB_PRESS = "https://www.ecb.europa.eu/rss/press.html"

MACRO_WORDS = re.compile(r"monetary|econom|inflation|outlook|labor|labour|interest rate|policy rate|"
                         r"financial conditions|balance sheet|mandate|price stability|growth|projection", re.I)
FED_HIGH = re.compile(r"FOMC statement|economic projections|Minutes of the Federal Open Market", re.I)
ECB_HIGH = re.compile(r"monetary policy decision|monetary policy statement|press conference|"
                      r"account of the monetary policy meeting|staff macroeconomic projections", re.I)
ECB_SKIP = re.compile(r"supervis|banking supervision|on-chain|crypto|payment|digital euro|AI\b", re.I)


def keep_fed_speech(title: str) -> bool:
    return bool(MACRO_WORDS.search(title or ""))


def keep_ecb(title: str) -> bool:
    t = title or ""
    if ECB_HIGH.search(t):
        return True
    return bool(MACRO_WORDS.search(t)) and not ECB_SKIP.search(t)


def _page_text(url: str, limit: int = 6000) -> str:
    r = http.get(url, timeout=30, retries=1)
    if r is None or "html" not in (r.headers.get("content-type") or "html"):
        return ""
    return article_text(r.text)[:limit]


def article_text(page: str) -> str:
    """Sayfanın asıl metni: Fed `id="article"`, ECB `<main>`/`class="section"`; bulunamazsa tüm sayfa."""
    from ..documents import html_text
    for marker in ('id="article"', "<main", 'class="section"', "<article"):
        i = page.find(marker)
        if i > 0:
            j = page.find(">", i)
            page = page[j + 1:] if j > 0 else page[i:]
            break
    text = html_text(page)
    for marker in ("For release at", "For immediate release", "Share this page"):
        i = text.find(marker)
        if 0 <= i < 1500:
            text = text[i:]
            break
    return text


def collect_central_banks(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("central_banks")
    if not cfg.get("enabled", True):
        return []
    out: list[Item] = []
    fed = entries_to_items(fetch_feed(FED_MONETARY), source="Fed · Para politikası", source_type="macro", market="US",
                           since=ctx.since, lang="en", allow_empty=True, extra={"cb": "Fed"})
    for it in fed:
        it.extra["high_impact"] = bool(FED_HIGH.search(it.title))
    out += fed
    sp = entries_to_items(fetch_feed(FED_SPEECHES), source="Fed · Konuşmalar", source_type="macro", market="US",
                          since=ctx.since, lang="en", allow_empty=True, extra={"cb": "Fed"})
    out += [i for i in sp if keep_fed_speech(i.title)]
    ecb = entries_to_items(fetch_feed(ECB_PRESS), source="ECB", source_type="macro", market="BIST",
                           since=ctx.since, lang="en", allow_empty=True, extra={"cb": "ECB"})
    for it in ecb:
        if keep_ecb(it.title):
            it.extra["high_impact"] = bool(ECB_HIGH.search(it.title))
            out.append(it)
    # Karar metinleri: AI'a başlık yerine metnin kendisi verilsin (yalnız yüksek önemli olanlar)
    ranked = sorted((i for i in out if i.extra.get("cb")), key=lambda i: not i.extra.get("high_impact"))
    for it in ranked[:int(cfg.get("max_fulltext", 4))]:
        text = _page_text(it.url)
        if len(text) > 300:
            it.extra["full_text"] = text
    # IMF ve yaptırımlar: Google News konu araması
    for q, name, hl in cfg.get("news_queries") or DEFAULT_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&{hl}"
        for it in [i for i in entries_to_items(fetch_feed(url, warn_empty=False), source="Google News", source_type="macro",
                                   market="BIST", since=ctx.since, lang="tr" if "hl=tr" in hl else "en",
                                   allow_empty=True, extra={"topic": name}, limit=20)
                   if TURKEY.search(i.title) and MUST[name].search(i.title)][:int(cfg.get("per_query", 5))]:
            pub = it.title.rsplit(" - ", 1)
            it.source = f"{pub[1].strip() if len(pub) == 2 else 'Google News'} · {name}"
            out.append(it)
    log.info("Merkez bankaları ve kurumlar: %d kayıt", len(out))
    return out


HL_TR = "hl=tr&gl=TR&ceid=TR:tr"
# Google aramaları gevşek eşleşir (Lübnan, Ukrayna, İran haberleri gelir): başlıkta Türkiye geçmeli
TURKEY = re.compile(r"T[uü]rk|Türkiye|TCMB|\blira\b", re.I)
MUST = {"IMF": re.compile(r"\bIMF\b|Uluslararası Para Fonu|International Monetary Fund", re.I),
        "Yaptırımlar": re.compile(r"sanction|yaptırım|OFAC", re.I)}
HL_EN = "hl=en-US&gl=US&ceid=US:en"
DEFAULT_QUERIES = [
    ('IMF Türkiye', "IMF", HL_TR),
    ('IMF (Turkey OR Türkiye) ("Article IV" OR "staff concluding" OR outlook)', "IMF", HL_EN),
    ('(OFAC OR "Treasury sanctions") (Turkey OR Türkiye OR Turkish)', "Yaptırımlar", HL_EN),
]


# ------------------------------------------------------------------ GDELT
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_GAP = 8.0           # GDELT: 5 saniyede en fazla bir istek
_last_call = [0.0]

DEFAULT_THEMES = [
    {"key": "tr_global", "name": "Türkiye (dünya basını)", "market": "BIST",
     "query": '(Turkey OR Türkiye OR Turkish) (lira OR economy OR inflation OR "central bank" OR sanctions '
              'OR tariffs OR rating OR bonds OR markets)'},
    {"key": "tr_press", "name": "Türk basını: piyasa gündemi", "market": "BIST",
     "query": 'sourcelang:turkish (borsa OR dolar OR faiz OR enflasyon OR "merkez bankası")'},
    {"key": "oil", "name": "Petrol", "market": "BIST", "query": '("Brent crude" OR "oil prices" OR OPEC)'},
]


def _gdelt(params: dict) -> dict | None:
    """GDELT isteği: 5 sn'de bir sınırına uyar; 429 ya da bağlantı hatasında artan beklemeyle 2 kez daha dener."""
    for attempt in range(3):
        wait = _last_call[0] + GDELT_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        n0 = len(http.FAILURES)
        r = http.get(GDELT, params={**params, "format": "json"}, timeout=45, retries=0)
        if r is None:
            if attempt < 2:
                del http.FAILURES[n0:]            # yeniden denenecek: son denemenin hatası kalsın
                time.sleep(GDELT_GAP * (attempt + 2))
                continue
            return None
        try:
            return r.json()
        except ValueError:                      # sorgu hatası düz metin döner
            http.note_failure(GDELT, r.text.strip()[:60] or "JSON değil")
            return None
    return None


def _series(js: dict | None) -> list[dict]:
    tl = (js or {}).get("timeline") or []
    return tl[0].get("data") or [] if tl else []


def _bin_time(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def spike(vol: list[dict], tone: list[dict], now: datetime, window_h: float = 2) -> dict | None:
    """Son `window_h` saatin haber sayısı/payı ve tonu, önceki dönemin olağan değerleriyle.
    vol: [{date, value (haber), norm (o aralıkta GDELT'in tüm haberleri)}], tone: [{date, value}]."""
    edge = now - timedelta(minutes=15)                   # son (yarım) aralığı alma
    bins = [b for b in vol if _bin_time(b["date"]) < edge]
    if len(bins) < 48:
        return None
    w = max(1, int(window_h * 4))
    cur, base = bins[-w:], bins[:-w]
    count = sum(b["value"] for b in cur)
    norm = sum(b["norm"] for b in cur) or 1
    share = count / norm
    shares = []
    for i in range(0, len(base) - w + 1, w):
        chunk = base[i:i + w]
        n = sum(b["norm"] for b in chunk)
        if n:
            shares.append(sum(b["value"] for b in chunk) / n)
    if not shares:
        return None
    usual = statistics.median(shares)
    mean_count = sum(b["value"] for b in base) / max(1, len(base)) * w
    tmap = {t["date"]: t["value"] for t in tone}

    def wtone(chunk):
        n = sum(b["value"] for b in chunk if b["date"] in tmap)
        return sum(tmap[b["date"]] * b["value"] for b in chunk if b["date"] in tmap) / n if n else None
    return {"count": count, "usual_count": round(mean_count, 1), "ratio": round(share / usual, 2) if usual else None,
            "tone": None if wtone(cur) is None else round(wtone(cur), 2),
            "base_tone": None if wtone(base) is None else round(wtone(base), 2)}


def triggered(s: dict | None, cfg: dict) -> str | None:
    """Alarm nedeni ('hacim', 'ton', 'hacim+ton') ya da None."""
    if not s or s["count"] < int(cfg.get("min_count", 12)):
        return None
    vol = s["ratio"] is not None and s["ratio"] >= float(cfg.get("volume_ratio", 3))
    d = None if s["tone"] is None or s["base_tone"] is None else s["tone"] - s["base_tone"]
    tone = d is not None and abs(d) >= float(cfg.get("tone_shift", 2))
    return "hacim+ton" if vol and tone else "hacim" if vol else "ton" if tone else None


def gdelt_item(theme: dict, s: dict, why: str, arts: list[dict], now: datetime) -> Item:
    d = None if s["tone"] is None or s["base_tone"] is None else round(s["tone"] - s["base_tone"], 1)
    parts = []
    if "hacim" in why:
        parts.append(f"haber hacmi olağanın {s['ratio']:.1f} katı".replace(".", ","))
    if "ton" in why and d is not None:
        parts.append(f"ton {'sertleşti' if d < 0 else 'iyileşti'} ({d:+.1f})".replace(".", ","))
    heads = [f"- {a.get('title', '').strip()} ({a.get('domain', '')})" for a in arts[:8] if a.get("title")]
    summary = (f"GDELT: '{theme['name']}' temasında son 2 saatte {s['count']} haber (3 günlük olağan "
               f"~{s['usual_count']:.0f}); ortalama ton {s['tone']} (3 günlük ortalama {s['base_tone']}). "
               f"Öne çıkan başlıklar:\n" + "\n".join(heads))
    bucket = now.replace(minute=0, second=0, microsecond=0)
    return Item(
        id=make_id("gdelt", theme["key"], iso(bucket)), source="GDELT · Dünya basını", source_type="macro",
        market=theme.get("market", "BIST"), title=f"{theme['name']}: {', '.join(parts)}", summary=summary,
        url=(arts[0].get("url") if arts else "") or f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote_plus(theme['query'])}&mode=artlist",
        published=iso(now), lang="tr",
        extra={"gdelt": {"theme": theme["key"], "why": why, **s,
                         "articles": [{k: a.get(k) for k in ("title", "domain", "url", "language")} for a in arts[:8]]}},
    )


def collect_gdelt(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("gdelt")
    if not cfg.get("enabled", True) or not due("gdelt", cfg.get("interval_min", 30)):
        return []
    now = now_utc()
    st = _state()
    cool = timedelta(hours=float(cfg.get("cooldown_hours", 6)))
    out, checked = [], 0
    for theme in cfg.get("themes") or DEFAULT_THEMES:
        key = f"gdelt_{theme['key']}"
        if st.get(key) and now - parse_iso(st[key]) < cool:
            continue
        vol = _series(_gdelt({"query": theme["query"], "mode": "timelinevolraw", "timespan": "3d"}))
        checked += 1
        s = spike(vol, [], now)
        # Ton yalnız hacim belirgin arttığında çekilir (istek sayısını yarıya indirir)
        if s and s["ratio"] and s["ratio"] >= float(cfg.get("tone_check_ratio", 1.5)) \
                and s["count"] >= int(theme.get("min_count", cfg.get("min_count", 12))):
            s = spike(vol, _series(_gdelt({"query": theme["query"], "mode": "timelinetone", "timespan": "3d"})), now)
        why = triggered(s, {**cfg, **theme})
        log.info("GDELT %s: %s → %s", theme["key"], s, why)
        if not why:
            continue
        arts = (_gdelt({"query": theme["query"], "mode": "artlist", "timespan": "2h", "maxrecords": 8,
                        "sort": "hybridrel"}) or {}).get("articles") or []
        out.append(gdelt_item(theme, s, why, arts, now))
        st[key] = iso(now)
    if out:
        _save_state({**_state(), **{k: v for k, v in st.items() if k.startswith("gdelt_")}})
    log.info("GDELT: %d tema tarandı, %d alarm", checked, len(out))
    return out
