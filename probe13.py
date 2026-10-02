import re, io, os, requests, feedparser
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36 piyasa-radari/1.0", "Accept-Language": "tr,en;q=0.8"}
SEC = {"User-Agent": os.environ.get("SEC_USER_AGENT") or "piyasa-radari research gptrade@users.noreply.github.com"}
def g(u, h=UA, **kw):
    try: return requests.get(u, headers=h, timeout=40, **kw)
    except Exception as e: print("   ERR", u, type(e).__name__, e); return None
def pdf_info(b):
    from pypdf import PdfReader
    i = b.find(b"%PDF"); r = PdfReader(io.BytesIO(b[i:])); return len(r.pages), " / ".join((r.pages[k].extract_text() or "")[:400] for k in range(min(2, len(r.pages)))).replace("\n", " ")
print("######## İş Yatırım şirket raporları kategorisi")
f = feedparser.parse(g("https://arastirma.isyatirim.com.tr/category/sirket-raporlari/feed/").content)
for e in f.entries[:10]: print("  ", e.get("published"), "|", e.get("title"), "|", [t.get("term") for t in e.get("tags", [])][:5])
for e in f.entries[:2]:
    p = g(e["link"]); t = p.text
    print("== post", e["link"], p.status_code, len(t))
    i = t.find("Raporu Göster")
    print("  buton bağlamı:", re.sub(r"\s+", " ", t[max(0, i - 700):i + 100]) if i > 0 else "yok")
    links = sorted(set(re.findall(r'href="(https?://[^"]+)"', t)))
    print("  dış/rapor linkleri:", [l for l in links if re.search(r"pdf|Documents|rapor|report|download|viewer", l, re.I)][:10])
    c = (e.get("content") or [{}])[0].get("value", "")
    print("  RSS içeriği:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))[:900])
for cat in ["model-portfoy-degisiklikleri", "en-cok-onerilenler", "hedef-fiyat"]:
    r = g(f"https://arastirma.isyatirim.com.tr/category/{cat}/feed/")
    print("  kategori", cat, r.status_code if r is not None else None, len(feedparser.parse(r.content).entries) if r is not None else 0)
e = next((x for x in feedparser.parse(g("https://arastirma.isyatirim.com.tr/feed/").content).entries if "Önerilen" in x.title), None)
if e:
    c = (e.get("content") or [{}])[0].get("value", ""); print("== En çok önerilenler içeriği:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", c))[:1500])
print("\n######## İş Yatırım hedef fiyat tablosu")
for u in ["https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Temel-Degerler-Ve-Oranlar.aspx",
          "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse=TTKOM"]:
    r = g(u)
    if r is None: continue
    t = r.text; print("==", u, r.status_code, len(t))
    for kw in ["Hedef Fiyat", "Öneri", "AL", "TUT"]:
        i = t.find(kw); print("   ", kw, i, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t[i - 200:i + 400])) if i > 0 else "")
        if kw == "Hedef Fiyat": pass
print("\n######## Foreks llms dosyaları")
for name in ["llms.txt", "llms-news.txt", "llms-analysis.txt"]:
    r = g("https://www.foreks.com/" + name)
    if r is not None:
        print("==", name, r.status_code, len(r.text)); print(r.text[:1500])
r = g("https://www.foreks.com/haber/")
if r is not None: print("== /haber/", r.status_code, len(r.text), re.findall(r"HİSSE DEĞERLENDİRMESİ[^<\"]{0,140}", r.text)[:5])
print("\n######## SEC 10-Q (SEC_USER_AGENT)", bool(os.environ.get("SEC_USER_AGENT")))
r = g("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=AAPL&type=10-Q&dateb=&owner=include&count=5&output=atom", h=SEC)
print("atom", r.status_code); link = re.findall(r'<link[^>]+href="([^"]+-index\.htm)"', r.text)[0]; base = link.rsplit("/", 1)[0]
ij = g(base + "/index.json", h=SEC); items = ij.json()["directory"]["item"]
print("dosyalar", [(x["name"], x.get("size")) for x in items][:15])
htm = [x for x in items if x["name"].endswith(".htm") and not re.search(r"index|^R\d|ex\d", x["name"], re.I)]
doc = max(htm, key=lambda x: int(x.get("size") or 0))["name"]; d = g(f"{base}/{doc}", h=SEC)
t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", d.text)))
print("ana belge", doc, d.status_code, "metin", len(t))
for pat in [r"Item\s*2\.?\s*Management.s Discussion", r"Item\s*1A\.?\s*Risk Factors", r"Item\s*3\.?\s*Quantitative"]:
    print("  ", pat, [m.start() for m in re.finditer(pat, t, re.I)][:4])
