import time, json, requests, feedparser
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 piyasa-radari/1.0"}
FEEDS = {
 "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
 "fed_monetary": "https://www.federalreserve.gov/feeds/press_monetary.xml",
 "fed_speeches": "https://www.federalreserve.gov/feeds/speeches.xml",
 "ecb_press": "https://www.ecb.europa.eu/rss/press.html",
 "ecb_blog": "https://www.ecb.europa.eu/rss/blog.html",
 "treasury_press": "https://home.treasury.gov/news/press-releases/feed",
 "ofac_recent": "https://ofac.treasury.gov/recent-actions/rss.xml",
 "ofac_old": "https://home.treasury.gov/system/files/126/ofac.xml",
 "imf_news": "https://www.imf.org/en/News/RSS?Language=ENG",
 "imf_pr": "https://www.imf.org/en/Publications/RSS?language=eng&series=IMF%20Press%20Releases",
 "imf_rss_list": "https://www.imf.org/en/Home/rss-list",
}
for k, u in FEEDS.items():
    try:
        r = requests.get(u, headers=UA, timeout=30)
        f = feedparser.parse(r.content)
        print(f"== {k} HTTP {r.status_code} {r.headers.get('content-type')} entries={len(f.entries)}")
        for e in f.entries[:6]:
            print("   ", e.get("published") or e.get("updated"), "|", (e.get("title") or "")[:110], "|", e.get("link"), "| tags:", [t.get("term") for t in e.get("tags", [])][:3])
        if not f.entries: print("   body:", r.text[:300].replace("\n"," "))
    except Exception as ex:
        print(f"== {k} ERR {ex}")
print("\n######## GDELT")
G = "https://api.gdeltproject.org/api/v2/doc/doc"
for q, mode in [('("Turkish lira" OR "Turkey economy")', "timelinevolraw"), ('("Turkish lira" OR "Turkey economy")', "timelinetone"),
                ('(sourcecountry:turkey sourcelang:turkish) (borsa OR dolar OR faiz)', "timelinevolraw"),
                ('("Turkish lira" OR "Turkey economy")', "artlist")]:
    params = {"query": q, "mode": mode, "format": "json", "timespan": "3d" if mode != "artlist" else "6h"}
    if mode == "artlist": params.update({"maxrecords": 5, "sort": "hybridrel"})
    r = requests.get(G, params=params, headers=UA, timeout=60)
    print("--", mode, q, r.status_code, len(r.content))
    try:
        js = r.json()
        if mode == "artlist":
            for a in js.get("articles", [])[:5]: print("   ", {k: a.get(k) for k in ("seendate","domain","language","sourcecountry","title","url")})
        else:
            tl = js.get("timeline", [])
            print("   series", [s.get("series") for s in tl], "n", len(tl[0]["data"]) if tl else 0)
            if tl: print("   first", tl[0]["data"][:2], "last", tl[0]["data"][-3:])
    except Exception as ex:
        print("   not json:", r.text[:300])
    time.sleep(6)
