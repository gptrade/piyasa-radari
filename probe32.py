"""Kâr payı bildirimlerinin yapısı (KAP)."""
import re, json, time, requests
from datetime import date, timedelta
from lxml import html as LH
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma)"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}
rows = []
for frm, to in [("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30"), ("2026-05-01", "2026-05-31")]:
    d0 = date.fromisoformat(frm)
    while d0 <= date.fromisoformat(to):
        d1 = min(d0 + timedelta(days=2), date.fromisoformat(to))
        r = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=60,
                   json={"fromDate": d0.isoformat(), "toDate": d1.isoformat(), "mkkMemberOidList": [], "subjectList": []})
        try: rows += [x for x in r.json() if "pay" in (x.get("subject") or "").lower() and "kâr" in (x.get("subject") or "").lower() or "Kar Payı" in (x.get("subject") or "")]
        except Exception as e: print("hata", d0, r.status_code)
        d0 = d1 + timedelta(days=1); time.sleep(1.5)
import collections
print(collections.Counter(x["subject"] for x in rows).most_common(10))
print(json.dumps(rows[0], ensure_ascii=False)[:600])
picks = [x for x in rows if (x.get("stockCodes") or "").split(",")[0].strip() in ("TUPRS", "FROTO", "TCELL", "BIMAS", "EREGL")][:3] or rows[:3]
for x in picks:
    r = S.get(f"https://www.kap.org.tr/tr/Bildirim/{x['disclosureIndex']}", timeout=60)
    t = r.text.replace('\\"', '"')
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t))
    print("\n####", x["stockCodes"], x["subject"], x["disclosureIndex"], r.status_code, len(t))
    for kw in ["Brüt", "Net", "Hak Kullanım", "Ödeme Tarihi", "Nakit Kar Payı", "Pay Başına", "Bedelsiz", "Kayıt Tarihi", "Yıl"]:
        i = txt.find(kw); print(f"  [{kw}]", txt[max(0, i - 80):i + 400] if i >= 0 else "yok")
    time.sleep(3)
