"""RSS tabanlı kaynaklar: SEC EDGAR, Google News, Yahoo Finance, Türk haber siteleri, Reddit."""
from __future__ import annotations

import calendar
import logging
from datetime import datetime
from urllib.parse import quote_plus

import feedparser

from .. import http
from ..models import UTC, Item, iso
from . import Context

log = logging.getLogger("radar.rss")


def _entry_time(e) -> datetime | None:
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t:
        return None
    return datetime.fromtimestamp(calendar.timegm(t), tz=UTC)


def fetch_feed(url: str, headers: dict | None = None):
    r = http.get(url, headers=headers)
    if r is None:
        return None
    return feedparser.parse(r.content)


def entries_to_items(feed, *, source: str, source_type: str, market: str, since: datetime,
                     lang: str, tickers: list[str] | None = None, matcher=None,
                     extra: dict | None = None) -> list[Item]:
    items: list[Item] = []
    if feed is None:
        return items
    for e in feed.entries:
        ts = _entry_time(e)
        if ts is None or ts < since:
            continue
        title = e.get("title", "")
        summary = e.get("summary", "")
        tk = list(tickers or [])
        if matcher is not None:
            for t in matcher.match(f"{title} {summary}", market=market):
                if t not in tk:
                    tk.append(t)
        if not tk:
            continue
        src = source
        if source == "Google News" and e.get("source", {}).get("title"):
            src = f"{e['source']['title']} · Google News"
        items.append(Item(source=src, source_type=source_type, market=market, title=title,
                          summary=summary, url=e.get("link", ""), published=iso(ts),
                          tickers=tk, lang=lang, extra=dict(extra or {})))
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
        out += entries_to_items(fetch_feed(url), source="Google News", source_type="news",
                                market=st.market, since=ctx.since, lang=lang, tickers=[st.symbol])
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
                                market="US", since=ctx.since, lang="en", tickers=[st.symbol])
    log.info("Yahoo: %d haber", len(out))
    return out


# ---------------------------------------------------------------- Türk haber siteleri
def collect_turkish_rss(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("turkish_news_rss")
    if not cfg.get("enabled", True):
        return []
    out: list[Item] = []
    for f in cfg.get("feeds") or []:
        out += entries_to_items(fetch_feed(f["url"]), source=f["name"], source_type="news",
                                market="BIST", since=ctx.since, lang="tr", matcher=ctx.matcher)
    log.info("TR RSS: %d haber", len(out))
    return out


# ---------------------------------------------------------------- Reddit
def collect_reddit(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("reddit")
    if not cfg.get("enabled", True):
        return []
    subs = "+".join(cfg.get("subreddits") or ["stocks"])
    out: list[Item] = []
    for st in ctx.market("US"):
        url = (f"https://www.reddit.com/r/{subs}/search.rss?q={quote_plus('$' + st.symbol)}"
               f"&restrict_sr=on&sort=new&t=day")
        out += entries_to_items(fetch_feed(url), source="Reddit", source_type="social", market="US",
                                since=ctx.since, lang="en", tickers=[st.symbol])
    log.info("Reddit: %d gönderi", len(out))
    return out
