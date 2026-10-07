"""Faz 0d: tablo hücre düzeni, birim bilgisi, üye filtresiyle uzun aralık, EVDS TÜFE."""
import os, re, json, time
from datetime import date, datetime, timedelta
import requests
from lxml import html as LH

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}

def cells(tr):
    out = []
    for td in tr.xpath("./td|./th"):
        t = re.sub(r"\s+", " ", td.text_content()).strip()
        cs = td.get("colspan")
        out.append(f"{t}" + (f"<cs{cs}>" if cs else ""))
    return out

r = S.get("https://www.kap.org.tr/tr/api/notification/export/excel/1652360", timeout=90)
doc = LH.fromstring(r.content.decode("utf-8", "replace"))
tables = doc.xpath("//table")
print("TRGYO tablo", len(tables))
# Büyük tabloların başlıkları
for ti, tb in enumerate(tables):
    trs = tb.xpath(".//tr")
    if len(trs) >= 25:
        heads = [" ".join(c for c in cells(tr) if c)[:90] for tr in trs[:3]]
        print(f"T{ti} satır={len(trs)} iç-tablo={len(tb.xpath('.//table'))} :: {heads}")
# Genel bilgi (birim, yuvarlama, denetim)
txt = re.sub(r"\s+", " ", doc.text_content())
for kw in ["Para Birimi", "Yuvarlama", "Finansal Tablo Niteliği", "Konsolide", "Bağımsız Denetim", "Dönem", "Sunum"]:
    i = txt.find(kw); print(f"[{kw}]", txt[i-50:i+200] if i >= 0 else "yok")
# Ham satır düzeni: KZ tablosu (300) ve nakit akış (453), ilk 12 satır ham
for ti in (300, 453):
    if ti < len(tables):
        print(f"\n--- T{ti} ham")
        for tr in tables[ti].xpath("./tr|./tbody/tr")[:14]:
            print("   ", cells(tr))
# Bilanço tablosunu ara
for ti, tb in enumerate(tables):
    t = tb.text_content()
    if "Dönen Varlıklar" in t and "Toplam Varlıklar".upper() in t.upper() and len(tb.xpath(".//tr")) > 40 and not tb.xpath(".//table"):
        print(f"\n--- bilanço adayı T{ti}")
        for tr in tb.xpath("./tr|./tbody/tr")[:10]: print("   ", cells(tr))
        for tr in tb.xpath("./tr|./tbody/tr"):
            c = cells(tr)
            if c and re.match(r"(TOPLAM VARLIKLAR|Toplam Varlıklar|TOPLAM KAYNAKLAR|Toplam Özkaynaklar|Kısa Vadeli Borçlanmalar|Nakit ve Nakit Benzerleri|Yatırım Amaçlı Gayrimenkuller|Ödenmiş Sermaye)", c[0], re.I):
                print("   *", c)
        break

# Üye filtresiyle uzun aralık (TRGYO oid'i endeks sayfasından)
e = S.get("https://www.kap.org.tr/tr/Endeksler", timeout=60).text.replace('\\"', '"')
m = re.search(r'"stockCode":"TRGYO","title":"[^"]+","mkkMemberOid":"([0-9a-f]+)"', e)
oid = m.group(1) if m else None
print("\nTRGYO oid", oid)
for frm in ["2023-01-01", "2020-01-01"]:
    rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=90,
                json={"fromDate": frm, "toDate": "2026-10-07", "mkkMemberOidList": [oid], "subjectList": []})
    try:
        js = rr.json()
        fr = [x for x in js if x.get("subject") in ("Finansal Rapor", "Finansal Rapor Bildirimi")]
        print(frm, rr.status_code, "toplam", len(js), "FR", len(fr), sorted({(x['year'], x['period'], x['ruleType']) for x in fr})[-14:])
    except Exception as ex:
        print(frm, rr.status_code, ex, rr.text[:200])
    time.sleep(2)

# EVDS TÜFE
key = os.environ.get("EVDS_API_KEY")
for code in ["TP.FG.J0", "TP.FE.OKTG01", "TP.TUFE1YI.T1"]:
    u = f"https://evds3.tcmb.gov.tr/igmevdsms-dis/series={code}&startDate=01-01-2023&endDate=07-10-2026&type=json&frequency=5"
    try:
        rr = S.get(u, headers={"key": key or ""}, timeout=60)
        js = rr.json(); items = js.get("items", [])
        k = code.replace(".", "_")
        vals = [(x.get("Tarih"), x.get(k)) for x in items if x.get(k) not in (None, "")]
        print("EVDS", code, rr.status_code, len(vals), vals[:2], vals[-3:])
    except Exception as ex:
        print("EVDS", code, "HATA", ex)
