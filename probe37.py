import os, sys
os.chdir("app"); sys.path.insert(0, os.getcwd())
from radar.fundamentals import kapfin
idx = kapfin.fetch_indices()
print({k: len(v) for k, v in idx.items()})
allc = set(); [allc.update(m["code"] for m in v) for v in idx.values()]
print("tüm endekslerde farklı kod", len(allc))
sec = kapfin.fetch_sectors(); print("sektör sayfasında kod", len(sec))
