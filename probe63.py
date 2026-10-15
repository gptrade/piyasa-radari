"""p63b: tüm evren için ay sonu fiyat geçmişi (süre ve kapsam) + dosyayı kaydet."""
import json, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, "app")
from radar.fundamentals import store
uni = json.loads(subprocess.check_output(["git", "-C", "app", "show", "origin/fin:_universe.json"]))
codes = sorted(m["code"] for m in uni["members"])
store.FIN = Path("probe63"); store.PX_HIST = Path("probe63/_px_hist.json")
t = time.time(); ok = store.update_price_history(codes)
d = json.loads(store.PX_HIST.read_text())["p"]
print("evren", len(codes), "fiyatlı", len(d), f"{time.time()-t:.0f}s", "boyut", store.PX_HIST.stat().st_size)
