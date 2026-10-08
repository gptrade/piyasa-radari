"""Kâr payı bildirim fikstürleri: gömülü HTML'i çözüp yalnız tabloları kaydeder."""
import re, json, time, os, requests
from lxml import html as LH, etree
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma)"})
os.makedirs("probe33", exist_ok=True)
for idx, name in [(1570793, "tuprs"), (1571600, "froto"), (1565152, "eregl"), (1565350, "aydem")]:
    t = S.get(f"https://www.kap.org.tr/tr/Bildirim/{idx}", timeout=60).text
    # Next.js akışındaki kaçışlı HTML'i çöz
    u = t.encode().decode("unicode_escape", errors="ignore") if "\\u003c" in t else t
    try:
        u = u.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        pass
    u = u.replace('\\"', '"')
    i = u.find("Kar Payı Dağıtım"); 
    doc = LH.fromstring(u)
    keep = []
    for tb in doc.xpath("//table"):
        txt = re.sub(r"\s+", " ", tb.text_content())
        if re.search(r"Kar Payı|Hak Kullanım|Ödeme Tarihi|Kayıt Tarihi|Dağıtım|Brüt|Pay Grubu|Bilgi", txt) and len(txt) < 6000 and not tb.xpath(".//table"):
            keep.append(etree.tostring(tb, encoding="unicode"))
    open(f"probe33/{name}.html", "w").write("<html><body>" + "\n".join(keep) + "</body></html>")
    print(name, idx, len(keep), "tablo")
    for k in keep[:14]:
        print("   ", re.sub(r"\s+", " ", LH.fromstring(k).text_content())[:300])
    time.sleep(3)
