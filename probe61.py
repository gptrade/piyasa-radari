"""p61: Gemma ile gerçek haber yorumu kalitesi ve süresi (onizleme-gemma dalı)."""
import json, sys, time, subprocess, logging
sys.path.insert(0, "app")
logging.basicConfig(level=logging.WARNING)
from radar.analyze import Analyzer
from radar.config import load_settings
from radar.models import Item
feed = json.loads(subprocess.check_output(["git", "-C", "app", "show", "origin/data:feed.json"]))
items = [i for i in feed["items"] if i["source_type"] in ("news", "disclosure") and i.get("analysis")][:6]
a = Analyzer(load_settings())
for raw in items:
    it = Item(source=raw["source"], source_type=raw["source_type"], market=raw["market"], title=raw["title"],
              url=raw.get("url", ""), published=raw["published"], tickers=raw.get("tickers") or [],
              summary=raw.get("summary", ""), lang=raw.get("lang", "tr"))
    t = time.time()
    out = a.assess(it)
    old = raw["analysis"]
    print(f"\n{raw['title'][:90]}\n  {time.time()-t:.1f}s  yeni: {out and (out.get('model'), out['sentiment'], out['confidence'], out['materiality'], out.get('headline_tr'))}")
    print(f"  eski: {(old.get('model'), old['sentiment'], old['confidence'], old['materiality'], old.get('headline_tr'))}")
print("\nstatus", a.status())
