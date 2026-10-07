"""Faz 0c: KAP excel (HTML) dışa aktarımını ayrıştır; yalnız yapı ve birkaç kalem yazdır."""
import re, time
import requests
from lxml import html as LH

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)"})
KEY = re.compile(r"^(Hasılat|TOPLAM VARLIKLAR|Toplam Varlıklar|Dönen Varlıklar|Satışların Maliyeti|BRÜT KAR|Brüt Kar|ESAS FAALİYET KARI|Esas Faaliyet Karı|Ana Ortaklık Payları|Amortisman ve İtfa Gideri|İşletme Faaliyetlerinden Nakit Akışları|Ödenmiş Sermaye|Kısa Vadeli Borçlanmalar|Uzun Vadeli Borçlanmalar|Nakit ve Nakit Benzerleri|Faiz Gelirleri|TOPLAM ÖZKAYNAKLAR|Toplam Özkaynaklar|Net Parasal|Yatırım Amaçlı Gayrimenkuller|Maddi Duran Varlık Alımından|DÖNEM KARI|Dönem Karı)", re.I)

def cell(td): return re.sub(r"\s+", " ", td.text_content()).strip()

for code, idx in [("EREGL", 1644583), ("TRGYO", 1652360), ("AKBNK", 1637885)]:
    r = S.get(f"https://www.kap.org.tr/tr/api/notification/export/excel/{idx}", timeout=90)
    doc = LH.fromstring(r.content.decode(r.encoding or "utf-8", "replace"))
    tables = doc.xpath("//table")
    print(f"\n##### {code} tablolar {len(tables)} encoding {r.encoding}")
    shown = 0
    for ti, tb in enumerate(tables):
        rows = [[cell(td) for td in tr.xpath("./td|./th")] for tr in tb.xpath(".//tr")]
        flat = " ".join(" ".join(x) for x in rows[:200])
        if not re.search(r"Hasılat|Toplam Varlıklar|TOPLAM VARLIKLAR|Faaliyetlerinden Nakit|Faiz Gelirleri", flat):
            continue
        if len(rows) < 15: continue
        print(f"--- tablo {ti} satır {len(rows)}")
        for row in rows[:6]: print("   H", [c for c in row if c][:9])
        for row in rows:
            cs = [c for c in row if c]
            if cs and KEY.search(cs[0]): print("   *", cs[:8])
        shown += 1
        if shown >= 6: break
    time.sleep(3)
