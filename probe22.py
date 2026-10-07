"""Faz 0e: KAP üye filtresi aralık sınırı, EVDS yeni TÜFE serisi."""
import os, re, json, time
import requests
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}
OID = "4028e4a1413b7ef5014144f83882011f"
for frm, to, extra in [("2025-10-08", "2026-10-07", {}), ("2026-04-08", "2026-10-07", {}), ("2026-07-01", "2026-09-30", {}),
                       ("2023-01-01", "2026-10-07", {"disclosureClass": "FR"}),
                       ("2023-01-01", "2026-10-07", {"subjectList": ["4028328c594bfdca01594c0af9aa0057"]}),
                       ("2026-07-01", "2026-09-30", {"mkkMemberOidList": [OID], "disclosureClass": "FR"})]:
    body = {"fromDate": frm, "toDate": to, "mkkMemberOidList": [OID], "subjectList": []}; body.update(extra)
    rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=90, json=body)
    try:
        js = rr.json()
        if isinstance(js, list):
            fr = [x for x in js if x.get("subject") == "Finansal Rapor"]
            print(frm, to, extra, rr.status_code, len(js), "FR", [(x["year"], x["period"], x["disclosureIndex"]) for x in fr])
        else: print(frm, to, extra, rr.status_code, str(js)[:200])
    except Exception as e: print(frm, to, extra, rr.status_code, rr.text[:200])
    time.sleep(2)

key = os.environ.get("EVDS_API_KEY") or ""
B = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
def j(u):
    try:
        r = S.get(B + u, headers={"key": key}, timeout=60); return r.status_code, r.json()
    except Exception as e: return "HATA", str(e)
st, cats = j("categories/type=json")
print("\nkategoriler", st, [(c.get("CATEGORY_ID"), c.get("TOPIC_TITLE_TR")) for c in cats][:40] if isinstance(cats, list) else str(cats)[:300])
for c in cats if isinstance(cats, list) else []:
    if re.search(r"fiyat", str(c.get("TOPIC_TITLE_TR")), re.I):
        st, groups = j(f"datagroups/mode=2&code={c['CATEGORY_ID']}&type=json")
        for g in groups if isinstance(groups, list) else []:
            title = str(g.get("DATAGROUP_NAME"))
            if re.search(r"tüketici|tufe|tüfe", title, re.I):
                print(" grup", g.get("DATAGROUP_CODE"), title, g.get("START_DATE"), g.get("END_DATE"))
                st, ser = j(f"serieList/type=json&code={g['DATAGROUP_CODE']}")
                for s in (ser if isinstance(ser, list) else [])[:4]:
                    print("    seri", s.get("SERIE_CODE"), s.get("SERIE_NAME"), s.get("START_DATE"), s.get("END_DATE"))
