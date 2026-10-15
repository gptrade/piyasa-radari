"""p63: GYO tarihsel PD/DD (onizleme-gyo-pddd): Yahoo ay sonu gerçek fiyatlar + KAP özkaynak."""
import json, sys, time, subprocess
from pathlib import Path
sys.path.insert(0, "app")
from radar.fundamentals import store, metrics as M
scr = json.loads(subprocess.check_output(["git", "-C", "app", "show", "origin/fin:_screen.json"]))
gyo = [r["code"] for r in scr["rows"] if r.get("sector") == "GAYRİMENKUL YATIRIM ORTAKLIKLARI"]
hold = ["KCHOL", "SAHOL", "DOHOL", "AGHOL", "TKFEN", "THYAO", "EREGL"]
t = time.time()
store.FIN = Path("fin"); store.PX_HIST = Path("fin/_px_hist.json"); store.FIN.mkdir(exist_ok=True)
ok = store.update_price_history(gyo + hold)
print("indirme", ok, f"{time.time()-t:.0f}s")
hist = json.loads(store.PX_HIST.read_text())["p"]
print("fiyatlı", len(hist), "/", len(gyo + hold))
for c in ["EKGYO", "ISGYO", "TRGYO", "ALGYO", "OZKGY", "SNGYO", "KLGYO", "AKSGY"] + hold:
    try:
        doc = json.loads(subprocess.check_output(["git", "-C", "app", "show", f"origin/fin:{c}.json"], stderr=subprocess.DEVNULL))
    except Exception:
        print(c, "fin yok"); continue
    px = next((r["price"] for r in scr["rows"] if r["code"] == c), None)
    m = M.company(doc, px, hist.get(c))
    ph = m and m.get("pb_hist")
    print(f"\n{c} fiyat {px} PD/DD {m and m['valuation'].get('pb')} → ort {ph and ph.get('avg')} (n={ph and ph.get('n')}, {ph and ph.get('from')}) rel {ph and ph.get('rel')}")
    print("  ", ph and ph["series"][-10:])
    print("   son fiyatlar:", hist.get(c, [])[-4:])
