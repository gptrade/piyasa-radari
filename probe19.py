"""Faz 0b: KAP excel dışa aktarımı yapısı, geçmiş derinlik, endeks listesi, kullanım koşulları."""
import io, json, re, time
from datetime import date, timedelta
import requests, openpyxl

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari arastirma; gptrade@users.noreply.github.com)",
                  "Accept-Language": "tr-TR,tr;q=0.9"})
H = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}

def show_xlsx(idx, code):
    r = S.get(f"https://www.kap.org.tr/tr/api/notification/export/excel/{idx}", timeout=60)
    print(f"\n##### {code} {idx} excel -> {r.status_code} {r.headers.get('content-type')} {len(r.content)}B")
    if r.status_code != 200: return
    try:
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
    except Exception as e:
        print("açılamadı", e, r.content[:200]); return
    print("sayfalar", wb.sheetnames[:40])
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        txt = " ".join(str(c) for row in rows[:400] for c in row if c)
        if not re.search(r"Hasılat|Toplam Varlıklar|TOPLAM VARLIKLAR|Faaliyetlerinden|Faiz Gelirleri|Dönen Varlıklar", txt):
            continue
        print(f"--- sayfa {ws.title!r} satır {len(rows)}")
        for row in rows[:12]:
            print("   ", [c for c in row if c is not None][:8])
        for row in rows:
            cells = [c for c in row if c is not None]
            if cells and re.search(r"^(Hasılat|TOPLAM VARLIKLAR|Toplam Varlıklar|Dönen Varlıklar|Satışların Maliyeti|ESAS FAALİYET KARI|Esas Faaliyet Karı|Ana Ortaklık Payları|Amortisman|İşletme Faaliyetlerinden|Ödenmiş Sermaye|Finansal Borçlar|Kısa Vadeli Borçlanmalar|Nakit ve Nakit Benzerleri|Faiz Gelirleri|TOPLAM ÖZKAYNAKLAR|Toplam Özkaynaklar|Net Parasal)", str(cells[0]).strip()):
                print("    *", cells[:7])
    time.sleep(2)

# 1) Kullanım koşulları bağlantıları
r = S.get("https://www.kap.org.tr/tr", timeout=60)
links = set(re.findall(r'href=\\?"([^"\\]+)', r.text))
print("ana sayfa", r.status_code, [l for l in links if re.search(r"kosul|koşul|yasal|uyari|uyarı|sart|şart|gizlilik|kvkk|about|hakkinda|hakkında", l, re.I)][:30])
for l in [l for l in links if re.search(r"kosul|koşul|yasal|uyari|uyarı|sart|şart", l, re.I)][:4]:
    u = l if l.startswith("http") else "https://www.kap.org.tr" + l
    rr = S.get(u, timeout=60); t = re.sub(r"<[^>]+>", " ", rr.text); t = re.sub(r"\s+", " ", t)
    for kw in ["otomatik", "robot", "yazılım", "çoğalt", "ticari", "yeniden", "kopyala", "izin"]:
        for m in re.finditer(kw, t, re.I):
            print(f"   [{kw}] ...{t[max(0,m.start()-250):m.start()+250]}...")
            break
    time.sleep(2)

# 2) Excel dışa aktarımı yapısı
for code, idx in [("EREGL", 1644583), ("TRGYO", 1652360), ("AKBNK", 1637885)]:
    show_xlsx(idx, code)

# 3) Geçmiş derinlik: 2023 Ağustos ve 2021 Mayıs haftası
for d in [date(2023, 8, 14), date(2021, 5, 3)]:
    rr = S.post("https://www.kap.org.tr/tr/api/disclosure/members/byCriteria", headers=H, timeout=60,
                json={"fromDate": d.isoformat(), "toDate": (d + timedelta(days=6)).isoformat(), "mkkMemberOidList": [], "subjectList": []})
    js = rr.json(); fr = [x for x in js if x.get("subject") == "Finansal Rapor"]
    print("\ngeçmiş", d, rr.status_code, len(js), "FR", len(fr), [(x.get("stockCodes"), x.get("year"), x.get("period"), x.get("ruleType")) for x in fr[:5]])
    time.sleep(2)

# 4) Endeks sayfasındaki BIST 100 verisi
r = S.get("https://www.kap.org.tr/tr/Endeksler", timeout=60); t = r.text.replace('\\"', '"')
i = t.find("BIST 100"); print("\nendeks", r.status_code, re.sub(r"\s+", " ", t[i-300:i+1500]) if i > 0 else "yok")
# 5) Şirket listesi excel başlıkları
r = S.get("https://www.kap.org.tr/tr/api/company/generic/excel/IGS/A", timeout=60)
wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True)
for ws in wb.worksheets:
    rows = list(ws.iter_rows(values_only=True)); print("\nşirket listesi", ws.title, len(rows)); [print("   ", x) for x in rows[:6]]
