import os, subprocess, sys, json, logging, traceback
from pathlib import Path
os.makedirs("site/data/fin", exist_ok=True)
subprocess.run("cp ../fin/_screen.json site/data/fin/ 2>/dev/null; ls site/data/fin | head -3", shell=True)
sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
from radar import sa
import importlib.util
spec = importlib.util.spec_from_file_location("radar.sa", "../probe/scripts/sa_new.py"); sa = importlib.util.module_from_spec(spec); spec.loader.exec_module(sa)
print("evren", len(sa.universe()), "izleme", sorted(sa.watch_codes())[:5])
try:
    doc = sa.run(Path("/tmp/o"), budget_s=120, max_pages=10)
    for k, v in list(doc["rows"].items())[:3]:
        print(k, json.dumps({kk: v.get(kk) for kk in ("pt", "rt", "fy", "an", "qt", "st", "t")}, ensure_ascii=False)[:700])
    print("stopped", doc.get("stopped"))
except Exception:
    traceback.print_exc()
