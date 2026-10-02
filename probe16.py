import sys, re, requests, feedparser
from urllib.parse import quote_plus
sys.path.insert(0, "app")
from radar import research
from radar.config import load_watchlist
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36"}
known = {s.symbol: [s.name, *s.aliases] for s in load_watchlist() if s.market == "BIST"}
qs = ['"hedef fiyatını"', 'site:foreks.com "HİSSE DEĞERLENDİRMESİ"', '"tavsiyesini" Yatırım hisse', '"hedef fiyat" yatırım hisse', 'hedef fiyat AL tavsiyesi', '"model portföy"']
for q in qs:
    for w in ["2d", "7d"]:
        f = feedparser.parse(requests.get(f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{w}&hl=tr&gl=TR&ceid=TR:tr", headers=UA, timeout=30).content)
        print(f"== {q} when:{w} → {len(f.entries)}")
        if w == "7d":
            for e in f.entries[:25]:
                n = research.parse_note(e.title, "", known)
                print("   ", "OK " if n else "-- ", e.title[:150], "|", n)
for name in ["llms-analysis.txt", "llms-news.txt"]:
    s = requests.get("https://www.foreks.com/" + name, headers=UA, timeout=30).text
    es = research.parse_llms(s)
    print("==", name, len(es), [e["title"][:90] for e in es if research.NOTE_HINT.search(e["title"])][:10])
