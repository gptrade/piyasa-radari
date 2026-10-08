"""Banka/sigorta önizleme verisi: seçili şirketler, KAP sınırına uygun aralıklarla ~40 dk."""
import json, os, shutil, sys, time, glob
os.chdir("app"); sys.path.insert(0, os.getcwd())
from radar.fundamentals import store
t0 = time.time(); i = 0
while time.time() - t0 < 40 * 60:
    i += 1
    s = store.run(200)
    print(i, round((time.time() - t0) / 60, 1), json.dumps(s, ensure_ascii=False), flush=True)
    if s.get("pending") == 0 and s.get("listed_total") == s.get("companies"):
        break
    st = json.load(open("site/data/fin/_state.json")); st.pop("kap_pause_until", None); st.get("last", {}).pop("recent", None)
    json.dump(st, open("site/data/fin/_state.json", "w"))
    time.sleep(330)
shutil.copytree("site/data/fin", "../probe36/fin", dirs_exist_ok=True)
scr = json.load(open("site/data/fin/_screen.json"))
for r in scr["rows"]:
    print(r["code"], r["t"], r["period"], r["quality"], r["valuation_score"], r["overall"], r["grade"], json.dumps(r["cat"], ensure_ascii=False))
    print("   ", {k: r["r"].get(k) for k in ("roe", "real_roe", "roa", "nim", "cost_income", "cost_of_risk", "ldr", "equity_assets", "loan_growth", "net_growth", "combined", "loss_ratio", "expense_ratio", "premium_growth")}, "pe", r["v"].get("pe"), "pb", r["v"].get("pb"))
