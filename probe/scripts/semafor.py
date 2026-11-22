"""Semafor Google News akışı: kaç kayıt, kaçı izleme listesi/endeks şirketiyle eşleşiyor (başlıklar kamuya açık)."""
import sys, collections
sys.path.insert(0, ".")
from radar.sources.feeds import fetch_feed
from radar import config
from datetime import datetime, timezone
f = fetch_feed("https://news.google.com/rss/search?q=site:semafor.com+when:7d&hl=en-US&gl=US&ceid=US:en")
print("kayit", len(f.entries) if f else None)
wl = config.load_watchlist(); m = config.TickerMatcher(wl)
print("izleme", [x.symbol for x in wl])
n = 0
for e in (f.entries if f else []):
    t = e.get("title", "")
    hit = m.match(t + " " + e.get("summary", ""), market="US") + m.match(t + " " + e.get("summary", ""), market="BIST")
    n += bool(hit)
    if hit or f.entries.index(e) < 25:
        print(e.get("published", "")[5:22], "|", t[:110], "|", hit)
print("eslesen", n)
