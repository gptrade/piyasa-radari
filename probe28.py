"""Faz 1 fikstürleri: KAP export'tan küçültülmüş HTML (yalnız ilk 3 tablo başlığı + ilk 40 satır),
listeleme satır alanları, sektör sayfası yapısı."""
import re, json, time, os
import requests
from lxml import html as LH, etree
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}
os.makedirs("probe28", exist_ok=True)



def shrink(idx, name, keep=60):
    raw = S.get(f"https://www.kap.org.tr/tr/api/notification/export/excel/{idx}", timeout=90).content
    doc = LH.fromstring(raw.decode("utf-8", "replace"))
    # üst bilgi metni
    head = re.sub(r"\s+", " ", doc.text_content())[:600]
    out = ["<html><body>", f"<div>{head}</div>"]
    for tb in doc.xpath("//table"):
        rows = tb.xpath("./tr|./tbody/tr")
        if len(rows) < 25: continue
        title = re.sub(r"\s+", " ", rows[1].text_content()).strip() if len(rows) > 1 else ""
        if not re.match(r"(Finansal Durum|Kar veya Zarar|Nakit Akış|Bilanço|BİLANÇO|Özkaynak)", title): continue
        t = etree.Element("table")
        n = 0
        for tr in rows:
            vals = [re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.xpath("./td|./th")]
            if n > 2 and not any(re.search(r"\d", v) for v in vals[2:]) and n > keep: continue
            new = etree.SubElement(t, "tr")
            for td in tr.xpath("./td|./th"):
                c = etree.SubElement(new, "td")
                if td.get("colspan"): c.set("colspan", td.get("colspan"))
                c.text = re.sub(r"\s+", " ", td.text_content()).strip()
            n += 1
            if n > 400: break
        out.append(etree.tostring(t, encoding="unicode"))
    out.append("</body></html>")
    open(f"probe28/{name}.html", "w").write("\n".join(out))
    print(name, idx, "yazıldı", sum(len(x) for x in out))

OID = "4028e4a1413b7ef5014144f83882011f"
rows = []
for frm, to in [("2024-10-01", "2025-09-30"), ("2025-10-01", "2026-09-30")]:
    rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=90,
                json={"fromDate": frm, "toDate": to, "mkkMemberOidList": [OID], "subjectList": []})
    rows += [x for x in rr.json() if x.get("subject") == "Finansal Rapor"]
    time.sleep(3)
best = {}
for x in sorted(rows, key=lambda x: x["disclosureIndex"], reverse=True):
    best.setdefault((x["year"], x["period"]), []).append(x["disclosureIndex"])
print(best)
for (y, p), idxs in sorted(best.items()):
    if (y, p) in [(2026, 2), (2025, 4)]:
        continue
    for idx in idxs:
        raw_name = f"trgyo_{y}_{p*3:02d}"
        shrink(idx, raw_name + "_tmp")
        t = open(f"probe28/{raw_name}_tmp.html").read()
        if "Niteliği Konsolide Finansal" in t.replace("Konsolide Olmayan", "X"):
            os.rename(f"probe28/{raw_name}_tmp.html", f"probe28/{raw_name}.html"); print("konsolide", raw_name, idx); break
        os.remove(f"probe28/{raw_name}_tmp.html")
        time.sleep(3)
    time.sleep(3)
