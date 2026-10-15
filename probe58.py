import sys, os, json, collections, shutil
sys.path.insert(0, "app")
os.makedirs("probe58", exist_ok=True)
from pathlib import Path
from radar import global_calendar as gc
gc.CACHE = Path("probe58/global_calendar.json")
cache, st = gc.refresh({"NVDA","TSLA","AAPL"}, force=True)
print("status", st)
evs = gc.events(cache, "2026-10-01", "2026-12-31", {"NVDA","TSLA","AAPL"})
print("events", len(evs), collections.Counter((e["region"], e["kind"], e["importance"]) for e in evs))
for e in sorted(evs, key=lambda e: e["when"]):
    if e["importance"] >= 3: print(" ", e["date"], e["region"], e["title"], e.get("detail","")[:60])
