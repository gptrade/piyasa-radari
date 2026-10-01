import json, sys, logging
from datetime import timedelta
sys.path.insert(0, "app")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
from radar import http
from radar.analyze import Analyzer
from radar.config import load_settings, load_watchlist, TickerMatcher
from radar.models import now_utc
from radar.sources import Context, global_macro as gm
st = load_watchlist(); S = load_settings()
ctx = Context(settings=S, stocks=st, matcher=TickerMatcher(st), since=now_utc() - timedelta(days=20))
items = gm.collect_central_banks(ctx)
print("== merkez bankaları", len(items), "uyarı", http.FAILURES)
for i in items:
    print(" ", i.published[:16], i.market, "|", i.source, "|", i.title[:100], "| yüksek" if i.extra.get("high_impact") else "", "| metin", len(i.extra.get("full_text", "")))
print("== GDELT ham ölçümler")
now = now_utc(); cfg = S["sources"]["gdelt"]
forced = None
for th in gm.DEFAULT_THEMES:
    vol = gm._series(gm._gdelt({"query": th["query"], "mode": "timelinevolraw", "timespan": "3d"}))
    tone = gm._series(gm._gdelt({"query": th["query"], "mode": "timelinetone", "timespan": "3d"}))
    s = gm.spike(vol, tone, now)
    print(" ", th["key"], "bins", len(vol), s, "→", gm.triggered(s, cfg))
    if s and (forced is None or (s["ratio"] or 0) > (forced[1]["ratio"] or 0)):
        forced = (th, s)
th, s = forced
arts = (gm._gdelt({"query": th["query"], "mode": "artlist", "timespan": "2h", "maxrecords": 8, "sort": "hybridrel"}) or {}).get("articles") or []
it = gm.gdelt_item(th, s, "hacim+ton", arts, now)
print("== örnek GDELT kaydı (zorlanmış):", it.title); print(it.summary[:1200])
print("uyarılar", http.FAILURES)
an = Analyzer(S)
fomc = next((i for i in items if "FOMC statement" in i.title), None)
for x in [fomc, it]:
    if not x: continue
    ctxt = "Piyasa geneli haber. İzleme listesi: " + ", ".join(f"{s.symbol} ({s.name})" for s in st)
    res = an.assess(x, ctxt)
    print("== AI:", x.title[:80]); print(json.dumps(res, ensure_ascii=False)[:1400])
json.dump({"items": [dict(i.to_dict(), extra={k: v for k, v in i.extra.items() if k != "full_text"}) for i in items[:12]],
           "gdelt": dict(it.to_dict(), analysis=res)}, open("probe11/out.json", "w"), ensure_ascii=False, indent=1)
