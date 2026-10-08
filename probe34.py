import os, sys, json
os.chdir("app"); sys.path.insert(0, os.getcwd())
from radar.fundamentals import dividends as D, kapfin
for idx, code in [(1570793, "TUPRS"), (1571600, "FROTO"), (1565152, "EREGL")]:
    print(code, json.dumps(D.fetch(idx, code), ensure_ascii=False)[:600])
rows = kapfin.list_reports("4028e4a1413b7ef5014144f83882011f", __import__("datetime").date(2025, 10, 1), __import__("datetime").date(2026, 9, 30))
print([(r["subject"], r["disclosureIndex"]) for r in rows if kapfin.is_div(r)])
