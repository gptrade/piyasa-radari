import os, re, requests
S = requests.Session(); key = os.environ.get("EVDS_API_KEY") or ""
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(u):
    r = S.get(B + u, headers={"key": key}, timeout=60); return r.json()
cats = j("categories/type=json")
pick = [c for c in cats if re.search(r"F[İI]YAT|TÜKET", str(c.get("TOPIC_TITLE_TR")))]
print([(c["CATEGORY_ID"], c["TOPIC_TITLE_TR"]) for c in pick])
for c in pick:
    try: groups = j(f"datagroups/mode=2&code={int(c['CATEGORY_ID'])}&type=json")
    except Exception as e: print("grup hata", c["CATEGORY_ID"], e); continue
    for g in groups:
        title = str(g.get("DATAGROUP_NAME"))
        print(" grup", int(c["CATEGORY_ID"]), g.get("DATAGROUP_CODE"), title, g.get("START_DATE"), g.get("END_DATE"))
        if re.search(r"TÜKETİCİ|Tüketici|TÜFE", title):
            try: ser = j(f"serieList/type=json&code={g['DATAGROUP_CODE']}")
            except Exception as e: print("  seri hata", e); continue
            for s in ser[:3]: print("    seri", s.get("SERIE_CODE"), s.get("SERIE_NAME"), s.get("START_DATE"), s.get("END_DATE"))
