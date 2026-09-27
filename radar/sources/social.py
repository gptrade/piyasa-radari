"""Sosyal medya: X (Twitter) API v2 ve StockTwits."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from .. import http
from ..models import UTC, Item, iso
from . import Context

log = logging.getLogger("radar.social")


def collect_x(ctx: Context) -> list[Item]:
    """X API v2 recent search. X_BEARER_TOKEN yoksa atlanır (X API ücretli bir katman ister)."""
    cfg = ctx.cfg("x_twitter")
    token = os.environ.get("X_BEARER_TOKEN")
    if not cfg.get("enabled", True) or not token:
        return []
    out: list[Item] = []
    for st in ctx.stocks:
        if st.market == "US":
            query = f"${st.symbol} -is:retweet lang:en"
        else:
            query = f'(#{st.symbol} OR "{st.name}") -is:retweet lang:tr'
        r = http.get("https://api.x.com/2/tweets/search/recent",
                     headers={"Authorization": f"Bearer {token}"},
                     params={"query": query,
                             "max_results": max(10, int(cfg.get("max_results_per_query", 10))),
                             "start_time": iso(ctx.since),
                             "tweet.fields": "created_at,public_metrics,author_id",
                             "expansions": "author_id", "user.fields": "username,verified"})
        if r is None:
            continue
        data = r.json()
        users = {u["id"]: u for u in (data.get("includes") or {}).get("users", [])}
        for tw in data.get("data") or []:
            u = users.get(tw.get("author_id"), {})
            m = tw.get("public_metrics") or {}
            handle = u.get("username", "x")
            out.append(Item(
                source=f"X · @{handle}", source_type="social", market=st.market,
                title=tw["text"][:180], summary=tw["text"],
                url=f"https://x.com/{handle}/status/{tw['id']}",
                published=iso(datetime.fromisoformat(tw["created_at"].replace("Z", "+00:00"))),
                tickers=[st.symbol], lang="en" if st.market == "US" else "tr",
                extra={"likes": m.get("like_count"), "reposts": m.get("retweet_count")},
            ))
    log.info("X: %d gönderi", len(out))
    return out


def collect_stocktwits(ctx: Context) -> list[Item]:
    if not ctx.cfg("stocktwits").get("enabled", True):
        return []
    out: list[Item] = []
    for st in ctx.market("US"):
        r = http.get(f"https://api.stocktwits.com/api/2/streams/symbol/{st.symbol}.json")
        if r is None:
            continue
        try:
            msgs = r.json().get("messages") or []
        except ValueError:
            continue
        for m in msgs:
            ts = datetime.strptime(m["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if ts < ctx.since:
                continue
            # Tek tek her mesaj gürültü; sadece etkileşim alanları al.
            likes = (m.get("likes") or {}).get("total", 0)
            if likes < 5:
                continue
            user = (m.get("user") or {}).get("username", "stocktwits")
            senti = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            out.append(Item(
                source=f"StockTwits · @{user}", source_type="social", market="US",
                title=m.get("body", "")[:180], summary=m.get("body", ""),
                url=f"https://stocktwits.com/{user}/message/{m['id']}",
                published=iso(ts), tickers=[st.symbol], lang="en",
                extra={"likes": likes, "user_sentiment": senti},
            ))
    log.info("StockTwits: %d mesaj", len(out))
    return out
