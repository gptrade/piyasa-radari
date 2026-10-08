"""KAP hız ölçümü: 6 sn aralıkla 30 dk boyunca; probe30 durumundan devam."""
import json, os, shutil, sys, time
shutil.copytree("probe30/fin", "app/site/data/fin", dirs_exist_ok=True)
os.chdir("app"); sys.path.insert(0, os.getcwd())
from radar.fundamentals import store, kapfin
st = json.load(open("site/data/fin/_state.json")); st.pop("kap_pause_until", None); json.dump(st, open("site/data/fin/_state.json", "w"))
store.MAX_REQ = 1000; store.MAX_PERIODS = 1000
t0 = time.time(); i = 0
while time.time() - t0 < 30 * 60:
    i += 1; r0 = kapfin.REQUESTS
    s = store.run(240)
    print(i, round((time.time() - t0) / 60, 1), "dk istek", kapfin.REQUESTS - r0, json.dumps(s, ensure_ascii=False), flush=True)
    if s.get("rate_limited"):
        st = json.load(open("site/data/fin/_state.json")); st.pop("kap_pause_until", None); json.dump(st, open("site/data/fin/_state.json", "w"))
        time.sleep(120)
shutil.copytree("site/data/fin", "../probe31/fin", dirs_exist_ok=True)
