import os, sys, json
sys.path.insert(0, "main")
from radar import http
key = os.environ.get("EVDS_API_KEY", "")
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(path):
    r = http.get(B + path, headers={"key": key}, timeout=60)
    if r is None: return ("NONE",)
    try: return r.json()
    except ValueError: return ("TXT", r.status_code, r.text[:200])
out=[]
cats = j("categories/type=json")
out.append("cat örnek: " + json.dumps(cats[:3], ensure_ascii=False)[:600])
cid = cats[0].get("CATEGORY_ID") if isinstance(cats, list) and cats and isinstance(cats[0], dict) else None
g = j(f"datagroups/mode=2&code={cid}&type=json")
out.append("grup örnek: " + json.dumps(g if not isinstance(g, list) else g[:2], ensure_ascii=False)[:800])
allg = j("datagroups/mode=0&type=json")
out.append("mode0: " + (str(len(allg)) if isinstance(allg, list) else json.dumps(allg)[:300]))
if isinstance(allg, list):
    for x in allg:
        n = json.dumps(x, ensure_ascii=False).lower()
        if any(w in n for w in ("dibs", "tahvil", "bond", "gösterge", "benchmark", "getiri", "yield", "borçlanma")):
            out.append("  " + json.dumps({k: x.get(k) for k in ("DATAGROUP_CODE", "DATAGROUP_NAME", "FREQUENCY_STR", "START_DATE", "END_DATE")}, ensure_ascii=False))
open("probe/log46.txt", "w").write("\n".join(out)); print("\n".join(out))
