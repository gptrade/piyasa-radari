import os, re, requests
S = requests.Session(); key = os.environ.get("EVDS_API_KEY") or ""
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(u): return S.get(B + u, headers={"key": key}, timeout=60).json()
cats = j("categories/type=json")
for c in cats:
    cid = int(c["CATEGORY_ID"])
    if str(cid).startswith("20") and cid < 30000: print(cid, c["TOPIC_TITLE_TR"])
for cid in [20, 2002, 2005, 2006, 2007, 2008]:
    try:
        for g in j(f"datagroups/mode=2&code={cid}&type=json"):
            print(" grup", cid, g.get("DATAGROUP_CODE"), g.get("DATAGROUP_NAME"), g.get("START_DATE"), g.get("END_DATE"))
            if re.search(r"Tüketici|TÜFE", str(g.get("DATAGROUP_NAME"))):
                for s in j(f"serieList/type=json&code={g['DATAGROUP_CODE']}")[:3]:
                    print("    seri", s.get("SERIE_CODE"), s.get("SERIE_NAME"), s.get("START_DATE"), s.get("END_DATE"))
    except Exception as e: print(cid, "hata", e)
