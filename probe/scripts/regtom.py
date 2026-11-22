import requests, feedparser
UA = "Mozilla/5.0 piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"
r = requests.get("https://www.regulationtomorrow.com/robots.txt", headers={"User-Agent": UA}, timeout=20)
print("robots", r.status_code); print(r.text[:1500])
for u in ["https://www.regulationtomorrow.com/feed/", "https://www.regulationtomorrow.com/feed/?paged=2"]:
    r = requests.get(u, headers={"User-Agent": UA}, timeout=20)
    f = feedparser.parse(r.content)
    print(u, r.status_code, r.headers.get("content-type"), len(f.entries))
    for e in f.entries[:12]:
        print(" ", e.get("published", "")[:16], "|", e.get("title", "")[:120], "|", [t.term for t in e.get("tags", [])][:4])
