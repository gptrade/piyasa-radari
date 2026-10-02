import re, io, json, time, requests, feedparser
from urllib.parse import quote_plus
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36 piyasa-radari/1.0", "Accept-Language": "tr,en;q=0.8"}
SEC = {"User-Agent": "piyasa-radari research gptrade@users.noreply.github.com"}
def g(u, **kw):
    try: return requests.get(u, headers=kw.pop("h", UA), timeout=40, **kw)
    except Exception as e: print("   ERR", u, type(e).__name__, e); return None
def pdf_info(b):
    from pypdf import PdfReader
    i = b.find(b"%PDF"); r = PdfReader(io.BytesIO(b[i:])); t = (r.pages[0].extract_text() or "")
    return len(r.pages), t[:300].replace("\n", " / ")
print("######## robots.txt")
for host in ["arastirma.isyatirim.com.tr","www.isyatirim.com.tr","www.garantibbvayatirim.com.tr","www.ykyatirim.com.tr","www.foreks.com","am.jpmorgan.com","cdn.jpmorganfunds.com","www.blackrock.com","corporate.vanguard.com","am.gs.com"]:
    r = g(f"https://{host}/robots.txt")
    if r is not None: print("==", host, r.status_code, "|", r.text[:500].replace("\n"," ; "))
print("\n######## İş Yatırım araştırma RSS")
r = g("https://arastirma.isyatirim.com.tr/feed/")
if r is not None:
    f = feedparser.parse(r.content); print("status", r.status_code, "entries", len(f.entries))
    for e in f.entries[:15]: print("  ", e.get("published"), "|", e.get("title"), "|", [t.get("term") for t in e.get("tags", [])][:4], "|", e.get("link"))
    if f.entries:
        e = f.entries[0]; c = (e.get("content") or [{}])[0].get("value", "") or e.get("summary", "")
        print("  içerik uzunluğu", len(c), "| pdf linkleri", re.findall(r'https?://[^"\']+\.pdf', c)[:3]); print("  ", re.sub(r"<[^>]+>", " ", c)[:600])
        p = g(e["link"]); 
        if p is not None: print("  sayfa", p.status_code, len(p.text), "pdf:", sorted(set(re.findall(r'https?://[^"\'\s]+\.pdf', p.text)))[:5])
for cat in ["sirket-raporlari", "sirket-notlari", "hisse-onerileri"]:
    r = g(f"https://arastirma.isyatirim.com.tr/category/{cat}/feed/"); print("  kategori", cat, r.status_code if r is not None else None, len(feedparser.parse(r.content).entries) if r is not None else 0)
print("\n######## Garanti BBVA Yatırım şirket raporları")
for u in ["https://www.garantibbvayatirim.com.tr/arastirma-raporlari/sirket-raporlari", "https://www.garantibbvayatirim.com.tr/arastirma-raporlari/sirket-ve-sektor-raporlari"]:
    r = g(u)
    if r is None: continue
    links = re.findall(r'href="([^"]+)"[^>]*>([^<]{3,120})<', r.text)
    docs = [(h, t.strip()) for h, t in links if re.search(r"\.pdf|\.vsf|document-file", h, re.I)]
    print("==", u, r.status_code, len(r.text), "belge linki", len(docs))
    for h, t in docs[:10]: print("    ", t, "|", h)
    if docs:
        h = docs[0][0]; h = h if h.startswith("http") else "https://www.garantibbvayatirim.com.tr" + h
        d = g(h); 
        if d is not None:
            print("    ilk belge", d.status_code, d.headers.get("content-type"), len(d.content))
            try: print("    pdf", pdf_info(d.content))
            except Exception as ex: print("    pdf değil", ex)
print("\n######## Yapı Kredi Yatırım")
for u in ["https://www.ykyatirim.com.tr/arastirma", "https://www.ykyatirim.com.tr/arastirma-raporlari", "https://www.ykyatirim.com.tr/arastirma/sirket-raporlari"]:
    r = g(u)
    if r is not None: print("==", u, r.status_code, len(r.text), "pdf:", len(re.findall(r'\.pdf', r.text)), sorted(set(re.findall(r'https?://[^"\'\s]+\.pdf', r.text)))[:3])
print("\n######## Foreks hisse değerlendirmeleri (Google News)")
q = 'site:foreks.com "HİSSE DEĞERLENDİRMESİ"'
for hl in ["hl=tr&gl=TR&ceid=TR:tr"]:
    r = g(f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&{hl}")
    f = feedparser.parse(r.content); print("entries", len(f.entries))
    for e in f.entries[:15]: print("  ", e.get("published"), "|", e.get("title"))
print("\n######## J.P. Morgan Guide to the Markets")
for u in ["https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/market-insights/guide-to-the-markets/mi-guide-to-the-markets-us.pdf",
          "https://cdn.jpmorganfunds.com/content/dam/jpm-am-aem/global/en/insights/market-insights/guide-to-the-markets/mi-guide-to-the-markets-us.pdf"]:
    r = g(u)
    if r is not None:
        print("==", u[:60], r.status_code, r.headers.get("content-type"), len(r.content), r.headers.get("last-modified"))
        try: print("   ", pdf_info(r.content))
        except Exception as ex: print("   pdf değil", ex)
print("\n######## BlackRock weekly commentary")
for u in ["https://www.blackrock.com/us/individual/insights/blackrock-investment-institute/weekly-commentary",
          "https://www.blackrock.com/corporate/insights/blackrock-investment-institute/publications/weekly-commentary"]:
    r = g(u)
    if r is not None:
        pdfs = sorted(set(re.findall(r'(/[^"\'\s]*weekly-investment-commentary[^"\'\s]*\.pdf)', r.text)))
        print("==", u[:70], r.status_code, len(r.text), "pdf", pdfs[-3:])
        if pdfs:
            d = g("https://www.blackrock.com" + pdfs[-1])
            if d is not None:
                try: print("   ", d.status_code, pdf_info(d.content))
                except Exception as ex: print("   pdf değil", ex)
print("\n######## Vanguard / GSAM")
for u in ["https://corporate.vanguard.com/content/corporatesite/us/en/corp/vemo/vemo-return-forecasts.html",
          "https://corporate.vanguard.com/content/corporatesite/us/en/corp/articles/market-perspectives.html",
          "https://am.gs.com/en-us/advisors/insights/article/market-outlook", "https://am.gs.com/en-us/advisors/insights"]:
    r = g(u)
    if r is not None: print("==", u[:80], r.status_code, len(r.text), "pdf:", sorted(set(re.findall(r'https?://[^"\'\s]+\.pdf', r.text)))[:3])
print("\n######## SEC 10-Q")
r = g("https://data.sec.gov/submissions/CIK0000320193.json", h=SEC)
f = r.json()["filings"]["recent"]
for i, form in enumerate(f["form"]):
    if form in ("10-Q", "10-K"):
        acc = f["accessionNumber"][i].replace("-", ""); doc = f["primaryDocument"][i]
        u = f"https://www.sec.gov/Archives/edgar/data/320193/{acc}/{doc}"
        d = g(u, h=SEC); t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", d.text)))
        print(form, f["filingDate"][i], u, d.status_code, "metin", len(t))
        for m in re.finditer(r"Item\s*[27]\.?\s*Management", t, re.I): print("   MD&A konumu", m.start(), t[m.start():m.start()+150])
        for m in re.finditer(r"Item\s*1A\.?\s*Risk Factors", t, re.I): print("   Risk konumu", m.start())
        break
