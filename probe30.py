"""Önizleme verisi: seçili BIST-100 şirketleri için veri katmanını ~70 dk, KAP'a nazik aralıklarla çalıştırır.
Çıktı (yalnız KAP kamu bildirimlerinden türetilmiş veri): probe30/fin/*.json"""
import json, os, shutil, sys, time, glob
os.chdir("app"); sys.path.insert(0, os.getcwd())
from radar.fundamentals import store
t0 = time.time()
i = 0
while time.time() - t0 < 70 * 60:
    i += 1
    s = store.run(200)
    print(i, round((time.time() - t0) / 60, 1), "dk", json.dumps(s, ensure_ascii=False), flush=True)
    if s.get("pending") == 0 and s.get("listed_total") == s.get("companies"):
        break
    time.sleep(300 if not s.get("rate_limited") else 60)
    st = json.load(open("site/data/fin/_state.json")); st.pop("kap_pause_until", None)
    if s.get("rate_limited"):
        time.sleep(600)
    json.dump(st, open("site/data/fin/_state.json", "w"))
shutil.copytree("site/data/fin", "../probe30/fin", dirs_exist_ok=True)
for f in sorted(glob.glob("site/data/fin/[A-Z]*.json")):
    d = json.load(open(f)); m = d.get("metrics") or {}
    print(d["code"], sorted(d["reports"]), m.get("period"), m.get("overall"), m.get("grade"))
