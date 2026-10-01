import json, re, sys, time
from datetime import date, timedelta, datetime
sys.path.insert(0, "app")
import yfinance as yf
from radar import documents, http, prices
from radar.analyze import Analyzer
from radar.config import load_settings, load_watchlist
from radar.models import Item, iso, now_utc
from radar.sources import kap
import requests
out = {"valuation": {}, "docs": []}
st = load_watchlist()
print("== değerleme")
for s in st:
    v = prices.valuation_data(yf.Ticker(s.yahoo))
    out["valuation"][s.symbol] = v
    print(s.symbol, json.dumps(v, ensure_ascii=False)[:400])
print("== KAP belge adayları")
r = requests.post(kap.LIST_URL, json={"fromDate": (date.today()-timedelta(days=6)).isoformat(), "toDate": date.today().isoformat(), "mkkMemberOidList": [], "subjectList": []},
                  headers={"User-Agent": http.DEFAULT_UA, "Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}, timeout=60)
rows = r.json()
items = kap.parse_rows(rows, {s.symbol for s in st}, "all")
cands = [i for i in items if documents.doc_kind(i)]
print("aday", len(cands), "izleme listesinden", sum(1 for i in cands if i.extra.get("watch")))
from collections import Counter
print(Counter(documents.doc_kind(i) for i in cands))
pick, kinds = [], set()
for i in sorted(cands, key=lambda i: (not i.extra.get("watch"), i.published), reverse=False):
    k = documents.doc_kind(i)
    if k not in kinds:
        kinds.add(k); pick.append(i)
pick = pick[:3]
SEC_UA = {"User-Agent": http.SEC_UA}
a = requests.get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=8-K&dateb=&owner=include&count=5&output=atom", headers=SEC_UA, timeout=30)
link = re.findall(r'<link[^>]+href="([^"]+-index\.htm)"', a.text)[1]
pick.append(Item(source="SEC EDGAR", source_type="disclosure", market="US", title="8-K - Current report", url=link,
                 published=iso(now_utc()), tickers=["AAPL"], lang="en", extra={"form": "8-K"}))
watch = {t for i in pick for t in i.tickers}
t0 = time.time()
ds = documents.attach(pick, watch, {"max_per_run": 4})
print("attach", ds, "süre", round(time.time() - t0, 1), "uyarı", http.FAILURES)
an = Analyzer(load_settings())
for i in pick:
    d = i.extra.get("doc")
    print("--", i.source, i.tickers, i.extra.get("subject"), i.url, "| doc:", d)
    if not d:
        continue
    print("   metin başı:", i.extra["full_text"][:300].replace("\n", " / "))
    res = an.assess(i, "")
    print("   AI:", json.dumps(res, ensure_ascii=False)[:1500])
    out["docs"].append({"title": i.title, "source": i.source, "tickers": i.tickers, "url": i.url, "market": i.market,
                        "published": i.published, "extra": {k: v for k, v in i.extra.items() if k != "full_text"}, "analysis": res})
print("AI durum", an.status())
json.dump(out, open("probe9/out.json", "w"), ensure_ascii=False, indent=1)
