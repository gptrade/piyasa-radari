"""Faz 1 kuru çalıştırma: önizleme dalındaki veri katmanını 240 sn bütçeyle çalıştır, özet yazdır."""
import json, glob, os, sys
os.chdir("app")
sys.path.insert(0, os.getcwd())
from radar.fundamentals import store
s = store.run(240)
print("ÖZET", json.dumps(s, ensure_ascii=False))
uni = json.load(open("site/data/fin/_universe.json"))
print("evren", len(uni["members"]), [ (m["code"], m.get("sector")) for m in uni["members"][:8]])
print("sektörsüz", [m["code"] for m in uni["members"] if not m.get("sector")])
cpi = json.load(open("site/data/fin/_cpi.json")) if os.path.exists("site/data/fin/_cpi.json") else {}
print("TÜFE", len(cpi.get("m", {})), sorted(cpi.get("m", {}).items())[-3:])
st = json.load(open("site/data/fin/_state.json"))
print("kuyruk", {k: sorted(v) for k, v in list(st.get("queue", {}).items())[:6]})
import time
print("rate_limited?", s.get("rate_limited"), "pause", st.get("kap_pause_until"))
for f in sorted(glob.glob("site/data/fin/[A-Z]*.json"))[:25]:
    d = json.load(open(f)); size = os.path.getsize(f)
    for pk, r in sorted(d["reports"].items()):
        inc = r.get("is", {}).get("rows", {})
        print(f"{d['code']:6} {pk} kons={r.get('consolidated')} {r.get('template')} {r.get('currency')}x{r.get('scale')} "
              f"bs={len(r.get('bs',{}).get('rows',{}))} is={len(inc)} cf={len(r.get('cf',{}).get('rows',{}))} "
              f"hasılat={inc.get('Hasılat',[None])[0]} anaort={inc.get('Ana Ortaklık Payları',[None])[0]} {size//1024}KB")

d = json.load(open(sorted(glob.glob("site/data/fin/[A-Z]*.json"))[0]))
se = d.get("series", {})
print("seri örneği", d["code"], se.get("periods"), "ttm hasılat", se.get("ttm", {}).get("revenue"), "net borç", se.get("bs", {}).get("net_debt"))
