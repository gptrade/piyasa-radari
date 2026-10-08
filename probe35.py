"""Banka/sigorta/aracı kurum şablonları: tablo başlıkları, kalemler, fikstürler (yalnız sayılı satırlar)."""
import os, re, sys, json, time
os.chdir("app"); sys.path.insert(0, os.getcwd())
from datetime import date
from lxml import html as LH, etree
from radar.fundamentals import kapfin
OUT = "../probe35"; os.makedirs(OUT, exist_ok=True)
C = {"AKBNK": "4028e4a240e8d1830140e905edcd0006", "GARAN": "4028e4a140f2ed720140f37cb2a601b7",
     "ANSGR": "4028e4a140e95bea0140ed21b5c10078", "ISMEN": "4028e4a140f275530140f277aa100008"}
for code, oid in C.items():
    rows = kapfin.list_reports(oid, date(2025, 10, 1), date(2026, 9, 30)) or []
    idxs = sorted([r["disclosureIndex"] for r in rows if kapfin.is_fr(r) and r.get("year") == 2026 and r.get("period") == 2], reverse=True)
    print("\n#####", code, idxs)
    for idx in idxs[:2]:
        r = kapfin._kap("GET", kapfin.EXPORT_URL.format(idx=idx), timeout=120)
        time.sleep(35)
        if r is None: print("yok", idx); continue
        text = r.content.decode("utf-8", "replace")
        rep = kapfin.parse_export(text)
        print(idx, "kons", rep.get("consolidated"), rep.get("currency"), rep.get("scale"), rep.get("template"))
        doc = LH.fromstring(text)
        out = ['<html><body><div>' + re.sub(r"\s+", " ", doc.text_content())[:500] + '</div>']
        for tb in doc.xpath("//table"):
            trs = tb.xpath("./tr|./tbody/tr")
            if len(trs) < 10: continue
            cells = [[re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.xpath("./td|./th")] for tr in trs]
            title = next((c for c in cells[1] if c), "") if len(cells) > 1 else ""
            print("  TABLO", len(trs), "|", title[:90], "|", [c for c in cells[0] if c][:4])
            t = etree.Element("table"); kept = 0
            for i, (tr, cs) in enumerate(zip(trs, cells)):
                if i > 1 and not any(re.search(r"\d", c) for c in cs[2:]): continue
                new = etree.SubElement(t, "tr")
                for td, c in zip(tr.xpath("./td|./th"), cs):
                    e = etree.SubElement(new, "td"); e.text = c
                    if td.get("colspan"): e.set("colspan", td.get("colspan"))
                kept += 1
            if re.match(r"(Finansal Durum|Bilanço|BİLANÇO|Kar veya Zarar|Gelir Tablosu|Nakit Akış|NAKİT|Varlıklar|VARLIKLAR|Yükümlülük|YÜKÜMLÜLÜK|Nazım)", title) or True:
                out.append(etree.tostring(t, encoding="unicode"))
            labs = [cs[1] if len(cs) > 1 else "" for i, cs in enumerate(cells) if i > 1 and any(re.search(r"\d", c) for c in cs[2:])]
            print("     ", " · ".join(l[:50] for l in labs[:70]))
        if rep.get("consolidated") or idx == idxs[-1]:
            open(f"{OUT}/{code.lower()}_2026_06.html", "w").write("\n".join(out) + "</body></html>")
            break
