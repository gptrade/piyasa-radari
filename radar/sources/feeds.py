"""RSS tabanlı kaynaklar: SEC EDGAR, Google News, Yahoo Finance, Türk haber siteleri, Reddit."""
from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime
from urllib.parse import quote_plus, urljoin
from zoneinfo import ZoneInfo

import feedparser

from .. import http
from ..models import UTC, Item, iso
from . import Context

log = logging.getLogger("radar.rss")


IST = ZoneInfo("Europe/Istanbul")
TR_MONTHS = {"oca": 1, "şub": 2, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7,
             "ağu": 8, "agu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12}
_TR_DATE = re.compile(r"(\d{1,2})[ .]+([A-Za-zÇĞİÖŞÜçğıöşü]{3,})[ .]+(\d{4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
_NUM_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")


_ISO_NAIVE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?\s*$")


def parse_tr_date(s: str | None) -> datetime | None:
    """'10 Ara 2024 11:23:57', '28 Eylül 2026', '28.09.2026 18:00' → İstanbul saatiyle datetime."""
    if not s:
        return None
    m = _TR_DATE.search(s)
    if m:
        mon = TR_MONTHS.get(m.group(2)[:3].replace("İ", "i").lower())
        if mon:
            h, mi, se = (int(x) if x else 0 for x in m.group(4, 5, 6))
            return datetime(int(m.group(3)), mon, int(m.group(1)), h, mi, se, tzinfo=IST)
    m = _NUM_DATE.search(s)
    if m:
        h, mi, se = (int(x) if x else 0 for x in m.group(4, 5, 6))
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), h, mi, se, tzinfo=IST)
    return None


def _entry_time(e) -> datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    if t:
        return datetime.fromtimestamp(calendar.timegm(t), tz=UTC)
    # RFC 822 olmayan tarihler: "2026-08-18 15:13:09" (Investing.com, saat dilimsiz → UTC),
    # Türkçe ay adları (TCMB ve bazı Türk siteleri)
    for key in ("published", "updated", "dc_date", "date"):
        v = e.get(key)
        m = _ISO_NAIVE.match(v or "")
        if m:
            y, mo, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
            return datetime(y, mo, d, h, mi, se, tzinfo=UTC)
        d = parse_tr_date(v)
        if d:
            return d.astimezone(UTC)
    return None


def fetch_feed(url: str, headers: dict | None = None, warn_empty: bool = True):
    r = http.get(url, headers=headers)
    if r is None:
        return None
    feed = feedparser.parse(r.content)
    feed["_base"] = url
    if not feed.entries and warn_empty:       # arama akışlarında boş sonuç normaldir
        http.note_failure(url, "RSS boş ya da okunamadı")
    return feed


def entries_to_items(feed, *, source: str, source_type: str, market: str, since: datetime,
                     lang: str, tickers: list[str] | None = None, matcher=None,
                     extra: dict | None = None, allow_empty: bool = False,
                     limit: int | None = None) -> list[Item]:
    items: list[Item] = []
    if feed is None:
        return items
    base = feed.get("_base", "")
    undated = 0
    for e in feed.entries:
        ts = _entry_time(e)
        if ts is None:
            undated += 1
            continue
        if ts < since:
            continue
        title = e.get("title", "")
        summary = e.get("summary", "")
        tk = list(tickers or [])
        if matcher is not None:
            for t in matcher.match(f"{title} {summary}", market=market):
                if t not in tk:
                    tk.append(t)
        if not tk and not allow_empty:
            continue
        src = source
        if source == "Google News" and e.get("source", {}).get("title"):
            src = f"{e['source']['title']} · Google News"
        link = e.get("link", "")
        items.append(Item(source=src, source_type=source_type, market=market, title=title,
                          summary=summary, url=urljoin(base, link) if base and link else link,
                          published=iso(ts), tickers=tk, lang=lang, extra=dict(extra or {})))
    if undated and undated == len(feed.entries):
        http.note_failure(base or source, f"{undated} kaydın tarihi okunamadı")
    if limit:
        items.sort(key=lambda i: i.published, reverse=True)
        items = items[:limit]
    return items


# ---------------------------------------------------------------- SEC EDGAR
SEC_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={t}"
           "&type={form}&dateb=&owner=include&count=20&output=atom")


def collect_sec(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("sec_edgar")
    if not cfg.get("enabled", True):
        return []
    forms = set(cfg.get("forms") or [])
    out: list[Item] = []
    for st in ctx.market("US"):
        feed = fetch_feed(SEC_URL.format(t=st.symbol, form=""), headers={"User-Agent": http.SEC_UA})
        for it in entries_to_items(feed, source="SEC EDGAR", source_type="disclosure", market="US",
                                   since=ctx.since, lang="en", tickers=[st.symbol]):
            form = it.title.split(" - ")[0].strip()
            if forms and form not in forms:
                continue
            it.extra["form"] = form
            out.append(it)
    log.info("SEC: %d kayıt", len(out))
    return out


# ---------------------------------------------------------------- Google News
def collect_google_news(ctx: Context) -> list[Item]:
    if not ctx.cfg("google_news").get("enabled", True):
        return []
    out: list[Item] = []
    for st in ctx.stocks:
        if st.market == "BIST":
            q = f'"{st.symbol}" OR "{st.name}" hisse'
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl=tr&gl=TR&ceid=TR:tr"
            lang = "tr"
        else:
            q = f'"{st.name}" OR "{st.symbol}" stock'
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl=en-US&gl=US&ceid=US:en"
            lang = "en"
        out += entries_to_items(fetch_feed(url, warn_empty=False), source="Google News", source_type="news",
                                market=st.market, since=ctx.since, lang=lang, tickers=[st.symbol],
                                limit=int(ctx.cfg("google_news").get("max_per_stock", 8)))
        # Doğrudan RSS'i olmayan siteler (ör. Barchart): Google News "site:" aramasıyla
        for site in (ctx.cfg("google_news").get("sites") or {}).get(st.market, []):
            q = f'"{st.symbol}" site:{site}' if st.market == "US" else f'"{st.name}" site:{site}'
            hl = "hl=en-US&gl=US&ceid=US:en" if st.market == "US" else "hl=tr&gl=TR&ceid=TR:tr"
            url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&{hl}"
            out += entries_to_items(fetch_feed(url, warn_empty=False), source="Google News", source_type="news",
                                    market=st.market, since=ctx.since, lang=lang, tickers=[st.symbol], limit=4)
    log.info("Google News: %d haber", len(out))
    return out


# ---------------------------------------------------------------- Yahoo Finance
def collect_yahoo(ctx: Context) -> list[Item]:
    if not ctx.cfg("yahoo_finance_rss").get("enabled", True):
        return []
    out: list[Item] = []
    for st in ctx.market("US"):
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={st.symbol}&region=US&lang=en-US"
        out += entries_to_items(fetch_feed(url), source="Yahoo Finance", source_type="news",
                                market="US", since=ctx.since, lang="en", tickers=[st.symbol],
                                limit=int(ctx.cfg("yahoo_finance_rss").get("max_per_stock", 8)))
    log.info("Yahoo: %d haber", len(out))
    return out


# ---------------------------------------------------------------- Türk haber siteleri
def collect_turkish_rss(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("turkish_news_rss")
    if not cfg.get("enabled", True):
        return []
    out: list[Item] = []
    for f in cfg.get("feeds") or []:
        market = f.get("market", "BIST")          # BIST | US | ALL (akış iki piyasadan da haber içerir)
        feed = fetch_feed(f["url"])
        if market != "ALL":
            out += entries_to_items(feed, source=f["name"], source_type="news", market=market,
                                    since=ctx.since, lang=f.get("lang", "tr"), matcher=ctx.matcher)
            continue
        for m in ("BIST", "US"):                  # her piyasa için ayrı eşleştir; kayıt hissenin piyasasına düşer
            out += entries_to_items(feed, source=f["name"], source_type="news", market=m,
                                    since=ctx.since, lang=f.get("lang", "tr"), matcher=ctx.matcher)
    log.info("TR RSS: %d haber", len(out))
    return out


# ---------------------------------------------------------------- Reddit
def collect_reddit(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("reddit")
    if not cfg.get("enabled", True):
        return []
    subs = "+".join(cfg.get("subreddits") or ["stocks"])
    stocks = ctx.market("US")
    # Hisse başına ayrı istek Reddit'in hız sınırına (HTTP 429) takılıyor: tek sorgu, sonra eşleştir.
    q = " OR ".join(f'"${st.symbol}"' for st in stocks)
    url = (f"https://www.reddit.com/r/{subs}/search.rss?q={quote_plus(q)}"
           f"&restrict_sr=on&sort=new&t=day&limit=100")
    sym_matcher = type(ctx.matcher)([type(st)(st.symbol, st.name, st.market, []) for st in stocks])
    out: list[Item] = entries_to_items(fetch_feed(url, warn_empty=False), source="Reddit", source_type="social",
                                       market="US", since=ctx.since, lang="en", matcher=sym_matcher)
    log.info("Reddit: %d gönderi", len(out))
    return out


# ---------------------------------------------------------------- Basın bülteni servisleri
PRESS_WIRES = {
    "PR Newswire": "https://www.prnewswire.com/rss/news-releases-list.rss",
    "GlobeNewswire": ("https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/"
                      "GlobeNewswire%20-%20News%20about%20Public%20Companies"),
}
_EXCH = r"(?:NASDAQ|Nasdaq|NYSE|NYSE American|NYSE Arca|Cboe|OTCQX|OTC)(?:\s*(?:GS|GM|CM))?"


def wire_tickers(title: str, summary: str, stocks) -> list[str]:
    """Bülten eşleştirme: önce '(NASDAQ: NVDA)' gibi borsa etiketi, sonra başlıkta şirket adı.

    Genel akışlarda binlerce şirket olduğundan metin gövdesinde serbest ad eşleştirmesi yapılmaz
    (ör. 'Apple Hospitality' yanlışlıkla AAPL'e düşmesin diye sadece başlık + etiket).
    """
    import re
    text = f"{title} {summary}"
    any_tag = re.findall(rf"{_EXCH}\s*:\s*([A-Z][A-Z.]{{0,5}})\b", text)
    out = []
    for st in stocks:
        if st.symbol in any_tag:
            out.append(st.symbol)
            continue
        if any_tag:          # bülten başka bir şirkete ait; ad benzerliğine güvenme
            continue
        name = re.compile(rf"^(?:{'|'.join(re.escape(a) for a in [st.name, *st.aliases])})(?![\w-])", re.I)
        if name.search(title.strip()):
            out.append(st.symbol)
    return out


def collect_press_wires(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("press_wires")
    if not cfg.get("enabled", True):
        return []
    stocks = ctx.market("US")
    out: list[Item] = []
    for name, url in PRESS_WIRES.items():
        feed = fetch_feed(url)
        for it in entries_to_items(feed, source=name, source_type="news", market="US",
                                   since=ctx.since, lang="en", allow_empty=True):
            it.tickers = wire_tickers(it.title, it.summary, stocks)
            if it.tickers:
                it.extra["press_release"] = True
                out.append(it)
    log.info("Basın bültenleri: %d", len(out))
    return out
