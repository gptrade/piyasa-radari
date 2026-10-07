"""Faz 0: KAP mali tablo fizibilitesi. Yalnızca yapı/özet yazdırır."""
import json, re, sys, time
from datetime import date, timedelta
import requests

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)",
                  "Accept-Language": "tr-TR,tr;q=0.9"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json",
     "Content-Type": "application/json"}

def get(url, **kw):
    try:
        r = S.get(url, timeout=40, **kw)
        print(f"GET {url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B")
        return r
    except Exception as e:
        print(f"GET {url} HATA {e}")

print("=== robots.txt ===")
r = get("https://www.kap.org.tr/robots.txt")
if r is not None: print(r.text[:3000])

print("\n=== FR bildirimleri (Ağustos sezonu) ===")
want = {"THYAO", "ASELS", "TRGYO", "KCHOL", "AKBNK", "AKSGY", "EREGL", "BIMAS"}
rows = []
d = date(2026, 7, 20)
while d < date(2026, 9, 10):
    to = d + timedelta(days=6)
    try:
        rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=60,
                    json={"fromDate": d.isoformat(), "toDate": to.isoformat(), "mkkMemberOidList": [], "subjectList": []})
        js = rr.json()
        print(d, rr.status_code, len(js))
        rows += js
    except Exception as e:
        print(d, "HATA", e)
    d = to + timedelta(days=1); time.sleep(2)
classes = {}
for x in rows: classes[x.get("disclosureClass")] = classes.get(x.get("disclosureClass"), 0) + 1
print("sınıflar", classes)
fr = [x for x in rows if x.get("disclosureClass") == "FR"]
print("FR sayısı", len(fr))
if fr: print("örnek FR anahtarları", sorted(fr[0].keys())); print(json.dumps(fr[0], ensure_ascii=False)[:800])
subj = {}
for x in fr: subj[x.get("subject")] = subj.get(x.get("subject"), 0) + 1
print("FR konuları", subj)
picked = {}
for x in fr:
    codes = [c.strip() for c in str(x.get("stockCodes") or x.get("relatedStocks") or "").replace(";", ",").split(",")]
    for c in codes:
        if c in want and c not in picked and "Finansal Rapor" in (x.get("subject") or ""):
            picked[c] = x
print("bulunan", {k: v.get("disclosureIndex") for k, v in picked.items()})

print("\n=== Bildirim sayfası yapısı ===")
for code, x in list(picked.items())[:5]:
    idx = x["disclosureIndex"]
    r = get(f"https://www.kap.org.tr/tr/Bildirim/{idx}")
    if r is None: continue
    t = r.text
    print(code, "tablo sayısı", t.count("<table"), "tr", t.count("<tr"),
          "__NEXT_DATA__" in t, "self.__next_f" in t)
    for kw in ["Dönen Varlıklar", "Hasılat", "Satış Gelirleri", "Toplam Varlıklar", "İşletme Faaliyetlerinden",
               "Ana Ortaklık", "Faiz Gelirleri", "Net Dönem Karı"]:
        i = t.find(kw); print(f"   {kw!r}: {i}", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", t[i:i+400]))[:260] if i > 0 else "")
    links = set(re.findall(r'href="([^"]+)"', t))
    print("   ilginç linkler", [l for l in links if re.search(r"xbrl|excel|xls|pdf|download|indir|export", l, re.I)][:15])
    apis = set(re.findall(r'/tr/api/[A-Za-z0-9_/\-{}]+', t))
    print("   sayfadaki api yolları", sorted(apis)[:30])
    time.sleep(3)

print("\n=== Şirket listesi / endeksler ===")
for u in ["https://www.kap.org.tr/tr/bist-sirketler", "https://www.kap.org.tr/tr/Endeksler",
          "https://www.kap.org.tr/tr/api/company/generic/excel/IGS/A"]:
    r = get(u)
    if r is not None:
        t = r.text
        print("   XU100" in t, "BIST 100" in t, t.count("THYAO"), re.sub(r"\s+", " ", t[:300]))
    time.sleep(2)
