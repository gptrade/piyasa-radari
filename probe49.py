import json, os, sys, collections
sys.path.insert(0, "app")
os.makedirs("probe49", exist_ok=True)
from radar import config
from radar import tr_calendar as tc, calendar_events as ce
tc.RAW_FILE = __import__("pathlib").Path("probe49/raw.json"); tc.LAST_FILE = __import__("pathlib").Path("probe49/last.json")
evs, daily, st = ce.official()
print("status", st)
print("events", len(evs), collections.Counter(e["kind"] for e in evs))
for e in evs:
    if e.get("last"): print("LAST", e["date"], e["title"], "=>", e["last"])
print(json.dumps(json.load(open("probe49/last.json")), ensure_ascii=False, indent=1))
print("daily", daily)
for e in evs[:5]: print(e["when"], e["title"])
os.remove("probe49/raw.json")
