import re, io, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0 Safari/537.36 piyasa-radari/1.0", "Accept-Language": "tr,en;q=0.8"}
from pypdf import PdfReader
def pdf(b, pages=None):
    i = b.find(b"%PDF"); r = PdfReader(io.BytesIO(b[i:])); n = len(r.pages)
    return n, [(r.pages[k].extract_text() or "") for k in (pages or range(n))]
print("######## İş Yatırım kullanım koşulları")
b = requests.get("https://www.isyatirim.com.tr/tr-tr/Resmi-Duyurular/Documents/Kullan%C4%B1mKo%C5%9Fullar%C4%B1ileKi%C5%9FiselVerilerinKorunmas%C4%B1veGizlilikPolitikas%C4%B1.pdf", headers=UA, timeout=60).content
n, txt = pdf(b); t = re.sub(r"\s+", " ", " ".join(txt)); print("sayfa", n, "metin", len(t))
for kw in ["otomatik", "robot", "kopyala", "çoğalt", "yayım", "izin", "ticari", "kaynak göster", "veri madencili", "scrap"]:
    for m in list(re.finditer(kw, t, re.I))[:2]: print(f"  [{kw}]", t[max(0, m.start()-250):m.start()+250])
print("\n######## Foreks llms-analysis HİSSE DEĞERLENDİRMESİ")
for name in ["llms-analysis.txt", "llms-news.txt"]:
    s = requests.get("https://www.foreks.com/" + name, headers=UA, timeout=40).text
    blocks = s.split("\n### ")
    print("==", name, "kayıt", len(blocks) - 1, "ilk tarih", re.findall(r"\*\*Tarih:\*\* ([\d\- :]+)", s)[-1:], "son", re.findall(r"\*\*Tarih:\*\* ([\d\- :]+)", s)[:1])
    for bl in blocks[1:]:
        title = bl.split("\n", 1)[0]
        if re.search(r"DEĞERLENDİRME|hedef fiyat|tavsiye|model portföy|ANALİZ", title, re.I): print("   ", title[:220])
s = requests.get("https://www.foreks.com/terms", headers=UA, timeout=30); print("\nforeks terms", s.status_code)
for u in ["https://www.foreks.com/kullanim-kosullari/", "https://www.foreks.com/yasal-uyari/"]:
    r = requests.get(u, headers=UA, timeout=30); t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)); print("==", u, r.status_code, len(t))
    for kw in ["otomatik", "kopyala", "çoğalt", "izin", "yapay zeka", "kaynak"]:
        for m in list(re.finditer(kw, t, re.I))[:1]: print(f"  [{kw}]", t[max(0, m.start()-200):m.start()+250])
print("\n######## BlackRock weekly metin")
page = requests.get("https://www.blackrock.com/us/individual/insights/blackrock-investment-institute/weekly-commentary", headers=UA, timeout=40).text
p = sorted(set(re.findall(r'(/us/individual/literature/market-commentary/weekly-investment-commentary[^"\'\s]*\.pdf)', page)))[-1]
n, txt = pdf(requests.get("https://www.blackrock.com" + p, headers=UA, timeout=60).content)
for k, x in enumerate(txt[:3]): print("  sayfa", k, re.sub(r"\s+", " ", x)[:500])
print("\n######## JPM GTTM içindekiler")
n, txt = pdf(requests.get("https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/market-insights/guide-to-the-markets/mi-guide-to-the-markets-us.pdf", headers=UA, timeout=90).content, range(0, 8))
for k, x in enumerate(txt): print("  sayfa", k, re.sub(r"\s+", " ", x)[:400])
