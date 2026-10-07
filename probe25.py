"""Faz 1 fikstürleri: KAP export'tan küçültülmüş HTML (yalnız ilk 3 tablo başlığı + ilk 40 satır),
listeleme satır alanları, sektör sayfası yapısı."""
import re, json, time, os
import requests
from lxml import html as LH, etree
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}
os.makedirs("probe25", exist_ok=True)

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
    open(f"probe25/{name}.html", "w").write("\n".join(out))
    print(name, idx, "yazıldı", sum(len(x) for x in out))

for idx, name in [(1652360, "trgyo_2026_06"), (1652359, "trgyo_2026_06_b"), (1571106, "trgyo_2025_12"), (1637885, "akbnk_2026_06")]:
    shrink(idx, name); time.sleep(2)

OID = "4028e4a1413b7ef5014144f83882011f"
rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=90,
            json={"fromDate": "2025-10-08", "toDate": "2026-10-07", "mkkMemberOidList": [OID], "subjectList": []})
for x in rr.json():
    if x.get("disclosureClass") == "FR": print(json.dumps(x, ensure_ascii=False))

for u in ["https://www.kap.org.tr/tr/Sektorler", "https://www.kap.org.tr/tr/sirket-bilgileri/ozet/1107-turk-hava-yollari-a-o"]:
    r = S.get(u, timeout=60); t = r.text.replace('\\"', '"')
    print("\n", u, r.status_code, len(t))
    for kw in ["THYAO", "sector", "Sektör", "sektor"]:
        for m in list(re.finditer(kw, t))[:3]:
            print(f"  [{kw}]", re.sub(r"\s+", " ", t[max(0, m.start()-200):m.start()+300]))
    time.sleep(2)
