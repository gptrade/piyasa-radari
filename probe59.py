import sys, os, collections
sys.path.insert(0, "app"); os.makedirs("probe59", exist_ok=True)
import logging; logging.basicConfig(level=logging.INFO)
from datetime import date, timedelta
from radar import global_calendar as gc
rows = gc.fetch_eurostat(date.today()-timedelta(days=14), date.today()+timedelta(days=75))
print("eurostat", None if rows is None else len(rows))
for r in rows or []: print(" ", r["d"], r["hm"], r["imp"], r["short"], r["period"])
