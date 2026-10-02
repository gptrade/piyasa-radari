import json, sys, logging, time, re
from datetime import timedelta
sys.path.insert(0, "app")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
import radar.config as C
from radar import http, research, documents, prices
from radar.analyze import Analyzer
from radar.config import load_settings, load_watchlist, TickerMatcher
from radar.models import Item, now_utc, iso
from radar.sources import Context, feeds
C.DATA.mkdir(parents=True, exist_ok=True)
st = load_watchlist(); S = load_settings()
ctx = Context(settings=S, stocks=st, matcher=TickerMatcher(st), since=now_utc() - timedelta(days=3))
print("== aracı kurum notları")
notes = research.collect_broker_notes(ctx)
for i in notes: print("  İZLEME", i.published[:16], i.extra["broker_note"], "|", i.title[:120])
print("  diğer BIST notları:", len(research.PENDING))
for n in research.PENDING[:25]: print("   ", n["ts"][:10], n["broker"], n["t"], n.get("rating"), n.get("action"), n.get("tp"), n.get("prev"), "|", n["title"][:110])
print("uyarılar", http.FAILURES)
print("\n== kurum görünümleri")
t0 = time.time(); outl = research.collect_outlooks(ctx); print("süre", round(time.time() - t0, 1))
for o in outl: print("  ", o.title, o.url, o.extra["doc"], "| metin başı:", o.extra["full_text"][:300].replace("\n", " "))
print("\n== SEC 10-Q")
a = __import__("requests").get("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=10-Q&dateb=&owner=include&count=3&output=atom", headers={"User-Agent": http.SEC_UA}, timeout=30)
link = re.findall(r'<link[^>]+href="([^"]+-index\.htm)"', a.text)[0]
q = Item(source="SEC EDGAR", source_type="disclosure", market="US", title="10-Q - Quarterly report", url=link, published=iso(now_utc()), tickers=["AAPL"], extra={"form": "10-Q"})
print("attach", documents.attach([q], {"AAPL"}, {}), q.extra.get("doc"))
print("  metin:", (q.extra.get("full_text") or "")[:400].replace("\n", " / "), "...", len(q.extra.get("full_text") or ""))
an = Analyzer(S)
items = []
for it in [*notes[:3], *outl, q]:
    ctx_txt = "Piyasa geneli. İzleme listesi: " + ", ".join(s.symbol for s in st) if it.source_type == "macro" else ""
    t0 = time.time(); it.analysis = an.assess(it, ctx_txt); print("\n== AI", it.title[:70], round(time.time() - t0, 1), "sn"); print(json.dumps(it.analysis, ensure_ascii=False)[:1500])
    d = it.to_dict(); d["extra"].pop("full_text", None); items.append(d)
px = {s.symbol: p for s in st if (p := prices._old(s, "analyst") and None) is None}
res = research.update(items, {}, an, st, {"synthesis_hours": 0})
print("\n== research.update", res, "AI", an.status())
data = json.loads(research.STORE.read_text())
print("sentez:", json.dumps(data.get("synthesis"), ensure_ascii=False)[:2500])
import shutil, os; os.makedirs("probe15", exist_ok=True); shutil.copy(research.STORE, "probe15/research.json")
json.dump(items, open("probe15/items.json", "w"), ensure_ascii=False)
