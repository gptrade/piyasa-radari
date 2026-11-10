import os, sys, json
sys.path.insert(0, "main")
from radar import http
key = os.environ.get("EVDS_API_KEY", "")
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(path):
    r = http.get(B + path, headers={"key": key}, timeout=90)
    if r is None: return ("NONE",)
    try: return r.json()
    except ValueError: return ("TXT", r.status_code, r.text[:300])
out=[]
sl = j("serieList/type=json&code=bie_pydibs")
for s in (sl if isinstance(sl, list) else []):
    out.append(json.dumps({k: s.get(k) for k in ("SERIE_CODE", "SERIE_NAME", "FREQUENCY_STR", "START_DATE", "END_DATE", "DEFAULT_AGG_METHOD")}, ensure_ascii=False))
codes = [s["SERIE_CODE"] for s in sl][:8] if isinstance(sl, list) else []
if codes:
    d = j(f"series={'-'.join(codes)}&startDate=20-10-2026&endDate=10-11-2026&type=json")
    out.append("son veri: " + json.dumps(d.get("items", d) if isinstance(d, dict) else d, ensure_ascii=False)[:2500])
    d2 = j(f"series={'-'.join(codes)}&startDate=26-09-2012&endDate=30-12-2012&type=json")
    out.append("ilk veri: " + json.dumps(d2.get("items", d2)[:5] if isinstance(d2, dict) else d2, ensure_ascii=False)[:1500])
open("probe/log47.txt", "w").write("\n".join(out)); print("\n".join(out))
