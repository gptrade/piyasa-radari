"""Uluslararası Regülasyon Takip: BCBS/BIS, Türkiye, Körfez ve Orta Doğu bankacılık düzenleyicilerinin risk yönetimi ve
model validasyonu yayınları.

`python -m radar.regwatch` — regulasyon.yml iş akışı (günlük). Çıktı: site/data/regulasyon/regwatch.json

1. Toplama: config/regwatch.yml'deki kurum sayfaları (RSS, tarihli bağlantı listeleri, tablo, SharePoint liste servisi).
   Sertifika zincirini eksik gönderen sitelerde (SAMA, Katar, Umman, BDDK) eksik ara sertifika AIA ile kurumun kendi
   yayın adresinden alınır; doğrulama her zaman açıktır. Bot korumalı ya da erişime kapalı siteler atlanır.
2. Sınıflandırma: yeni başlıklar toplu hâlde ücretsiz modelle (Gemma) okunur — ilgili mi (risk yönetimi, model validasyonu,
   sermaye, likidite…), konu etiketleri, tür (taslak/nihai/rehber/duyuru), Türkçe başlık ve tek cümle özet. Faiz kararı,
   enflasyon raporu, rutin makro ve kurumsal haberler elenir.
3. Yönetici özeti: haftada bir, son 90 günün ilgili dokümanlarından en kritik 3 eğilim.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import json
import logging
import re
import sys
import tempfile
import time
from urllib.parse import urljoin, urlparse

import requests
import yaml

from .config import CONFIG, DATA

log = logging.getLogger("radar.regwatch")

OUT = DATA / "regulasyon" / "regwatch.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36 "
      "piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)")
SINCE = "2025-07-01"                 # bu tarihten eski dokümanlar alınmaz
TYPES = {"taslak": "Taslak / istişare", "nihai": "Nihai düzenleme", "rehber": "Rehber / ilke", "duyuru": "Duyuru / sirküler"}
MON = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
MONTHS = {m.lower(): i for i, m in enumerate(MON.split("|"), 1)}
DATE_RX = re.compile(rf"\b(\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]20\d\d|20\d\d[/.\-]\d{{1,2}}[/.\-]\d{{1,2}}|\d{{1,2}}\s+(?:{MON})[a-z]*\.?,?\s+20\d\d|"
                     rf"(?:{MON})[a-z]*\.?\s+\d{{1,2}},?\s+20\d\d)", re.I)


# ─────────────────────────────── yardımcılar
TR_MON = {"oca": 1, "şub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6, "tem": 7, "ağu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12}


def parse_date(s: str | None, dayfirst: bool = True) -> str | None:
    """'16.10.2026', '01/10/2026', '2026-10-16', '19 Oct 2026', 'September 16, 2026', RFC822, '6 Eki 2026' → 'YYYY-AA-GG'."""
    s = (s or "").strip()
    m = re.search(r"(\d{1,2})\s+(Oca|Şub|Mar|Nis|May|Haz|Tem|Ağu|Eyl|Eki|Kas|Ara)[a-zçğıöşü]*\.?\s+(20\d\d)", s)
    if m and not re.search(rf"\b({MON})\b", s):
        try:
            return dt.date(int(m.group(3)), TR_MON[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    if not s:
        return None
    m = re.search(r"(20\d\d)[/.\-](\d{1,2})[/.\-](\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d\d)", s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            d, mo = (a, b) if dayfirst else (b, a)
            if mo > 12:
                d, mo = mo, d
        else:
            m = re.search(rf"(\d{{1,2}})\s+({MON})[a-z]*\.?,?\s+(20\d\d)", s, re.I) or None
            if m:
                d, mo, y = int(m.group(1)), MONTHS[m.group(2)[:3].lower()], int(m.group(3))
            else:
                m = re.search(rf"({MON})[a-z]*\.?\s+(\d{{1,2}}),?\s+(20\d\d)", s, re.I)
                if not m:
                    return None
                mo, d, y = MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


class Fetcher:
    """Kurum siteleri için oturum: sertifika zinciri eksikse AIA ile tamamlar (doğrulama kapanmaz)."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,tr;q=0.8"})
        self.verify: dict[str, object] = {}

    def _verify(self, url: str):
        host = urlparse(url).hostname or ""
        if host in self.verify:
            return self.verify[host]
        v: object = True
        try:
            self.s.head(url, timeout=25, allow_redirects=True)
        except requests.exceptions.SSLError:
            try:
                import certifi
                from aia import AIASession
                cadata = AIASession().cadata_from_url(url)
                f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem")
                f.write(open(certifi.where(), encoding="utf-8").read() + "\n" + cadata)
                f.close()
                v = f.name
                log.info("%s: eksik ara sertifika AIA ile tamamlandı", host)
            except Exception as e:                                           # noqa: BLE001
                log.warning("%s: sertifika zinciri tamamlanamadı (%s)", host, e)
        except requests.RequestException:
            pass
        self.verify[host] = v
        return v

    def get(self, url: str, **kw) -> requests.Response | None:
        try:
            r = self.s.get(url, timeout=45, verify=self._verify(url), **kw)
        except requests.RequestException as e:
            log.warning("%s: %s", url[:90], type(e).__name__)
            return None
        if r.status_code != 200:
            log.warning("%s: HTTP %s", url[:90], r.status_code)
            return None
        if "Just a moment" in r.text[:3000] or "captcha" in r.text[:3000].lower():
            log.warning("%s: bot doğrulaması", url[:90])
            return None
        return r


# ─────────────────────────────── çıkarıcılar
def from_rss(text: str, base: str) -> list[dict]:
    out = []
    for block in re.findall(r"<entry\b.*?</entry>", text, re.S | re.I):          # Atom (ör. TCMB)
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
        link = re.search(r"<link[^>]*href=\"([^\"]+)\"", block, re.S | re.I)
        d = re.search(r"<(?:published|updated)[^>]*>(.*?)</", block, re.S | re.I)
        title = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1))) if t else ""
        if title and link:
            out.append({"title": title, "url": urljoin(base, link.group(1).strip()), "date": parse_date(clean(d.group(1)) if d else None), "desc": ""})
    for block in re.findall(r"<item\b.*?</item>", text, re.S | re.I):
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S | re.I)
        link = re.search(r"<link[^>]*>(.*?)</link>", block, re.S | re.I)
        d = re.search(r"<(?:pubDate|dc:date|date|NewsDate)[^>]*>(.*?)</", block, re.S | re.I)
        desc = re.search(r"<description[^>]*>(.*?)</description>", block, re.S | re.I)
        title = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1))) if t else ""
        url = clean(re.sub(r"<!\[CDATA\[|\]\]>", "", link.group(1))) if link else ""
        if title and url:
            out.append({"title": title, "url": urljoin(base, url), "date": parse_date(clean(d.group(1)) if d else None, dayfirst=True),
                        "desc": clean(re.sub(r"<!\[CDATA\[|\]\]>", "", desc.group(1)))[:300] if desc else ""})
    return out


def from_html(text: str, base: str) -> list[dict]:
    """Tarihli bağlantılar: metni ≥18 karakter olan, kurumun alan adındaki (ya da PDF) bağlantılar; tarih bağlantının
    yakın atasındaki metinden."""
    import lxml.html
    doc = lxml.html.fromstring(text)
    for bad in doc.xpath("//script|//style|//nav|//header|//footer|//noscript"):
        bad.drop_tree()
    host = (urlparse(base).hostname or "").replace("www.", "")
    out, seen = [], set()
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if not href or href.startswith(("javascript", "mailto", "#", "tel:")):
            continue
        txt = re.sub(r"\s+", " ", a.text_content()).strip()
        if len(txt) < 18:
            continue
        url = urljoin(base, href)
        if host not in (urlparse(url).hostname or "") and not url.lower().endswith(".pdf"):
            continue
        node, date = a, None
        for _ in range(4):
            node = node.getparent()
            if node is None:
                break
            t = re.sub(r"\s+", " ", node.text_content())
            if len(t) > 1500:
                break
            m = DATE_RX.search(t)
            if m:
                date = parse_date(m.group(1))
                break
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": txt[:300], "url": url, "date": date, "desc": ""})
    return out


def from_table(text: str, base: str) -> list[dict]:
    """Tablo satırları: satırda bir bağlantı ve bir tarih varsa; başlık en uzun hücre."""
    import lxml.html
    doc = lxml.html.fromstring(text)
    out, seen = [], set()
    for tr in doc.iter("tr"):
        cells = [re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.findall("td")]
        links = [a.get("href") for a in tr.iter("a") if a.get("href")]
        if len(cells) < 2 or not links:
            continue
        date = next((parse_date(m.group(1)) for c in cells for m in [DATE_RX.search(c)] if m), None)
        title = max(cells, key=len)
        url = urljoin(base, links[0])
        if len(title) < 12 or url in seen:
            continue
        seen.add(url)
        out.append({"title": title[:300], "url": url, "date": date, "desc": ""})
    return out


def from_sp(text: str, src: dict) -> list[dict]:
    try:
        d = json.loads(text)
    except ValueError:
        return []
    rows = (d.get("d") or {}).get("results") or d.get("value") or []
    out = []
    for r in rows:
        title = clean(str(r.get(src.get("title", "Title")) or ""))
        path = r.get(src.get("path", "FileRef")) or ""
        if title and path:
            out.append({"title": title, "url": urljoin(src.get("base", src["url"]), path), "date": parse_date(str(r.get(src.get("date", "Created")) or "")),
                        "desc": ""})
    return out


BIS_PREFIX = re.compile(r"^(?:Publication|Press release|Speech)\s+(Standards|Consultative(?: document)?|Implementation reports?|Guidelines?|"
                        r"Working papers?|Newsletters?|BCBS Newsletter No \d+|Reports?|Other documents?|Principles?)?\s*"
                        r"(\d{1,2}\s+\w{3,9}\s+20\d\d)?\s*", re.I)


def tidy(reg: str, it: dict) -> dict:
    if reg == "bcbs":                                       # "Publication Consultative 16 Oct 2026 Başlık …" → başlık + tür ipucu
        m = BIS_PREFIX.match(it["title"])
        if m and m.end():
            it["hint"] = (m.group(1) or "").strip()
            it["title"] = it["title"][m.end():].strip()
    it["title"] = re.sub(r"^\d{1,2}[./]\d{1,2}[./]20\d\d\s+", "", it["title"])   # BDDK: başlıktaki tarih
    return it


def collect(cfg: dict, f: Fetcher | None = None) -> tuple[list[dict], dict]:
    f = f or Fetcher()
    items, status = [], {}
    for reg in cfg["regulators"]:
        if reg.get("blocked"):
            status[reg["id"]] = {"ok": False, "why": reg["blocked"], "n": 0}
            continue
        n, errs = 0, []
        for src in reg.get("sources") or []:
            r = f.get(src["url"], headers={"Accept": "application/json;odata=verbose"} if src["type"] == "sp" else None)
            if r is None:
                errs.append(urlparse(src["url"]).path[:40] or "/")
                continue
            r.encoding = r.encoding or "utf-8"
            text = r.text
            got = (from_rss(text, src["url"]) if src["type"] == "rss" else from_table(text, src["url"]) if src["type"] == "table"
                   else from_sp(text, src) if src["type"] == "sp" else from_html(text, src["url"]))
            got = [g for g in got if g["date"]]                   # tarihsiz bağlantılar çoğunlukla menü/gezinme ya da arşiv
            for it in got:
                it["reg"] = reg["id"]
                items.append(tidy(reg["id"], it))
            n += len(got)
            time.sleep(getattr(f, "gap", 1.0))
        status[reg["id"]] = {"ok": n > 0, "n": n, "why": ("okunamayan: " + ", ".join(errs)) if errs else None}
        log.info("%s: %d bağlantı%s", reg["name"], n, f" (hata: {errs})" if errs else "")
    return items, status


# ─────────────────────────────── sınıflandırma (Gemma, ücretsiz kota)
CLS_SYSTEM = ("Sen kıdemli bir bankacılık regülasyonu, risk yönetimi ve model validasyonu analistisin. Sana merkez bankası / "
              "düzenleyici sitelerinden toplanmış doküman başlıkları verilecek. Hangilerinin risk yönetimi, model validasyonu ve "
              "banka düzenlemesi açısından ilgili olduğunu belirle.")
CLS_FMT = """
İLGİLİ: model validasyonu, model risk yönetimi (MRM), IRB, AI/ML model yönetişimi, backtesting, IFRS 9/ECL, stres testi, ICAAP/ILAAP,
ALM, likidite (LCR/NSFR), faiz oranı riski (IRRBB), Basel III / sermaye yeterliliği / RWA / büyük riskler / kaldıraç, kredi riski,
piyasa riski / FRTB / CVA, operasyonel risk / operasyonel dayanıklılık / BT-siber risk yönetimi, iklim riski, risk yönetişimi ve
iç denetim/iç kontrol düzenlemeleri, banka denetim rehberleri ve istişare metinleri, makro ihtiyati düzenlemeler.
İLGİSİZ (relevant=false): faiz kararları, enflasyon/ödeme dengesi/rezerv/döviz likiditesi/istatistik bültenleri, swap ve iş birliği
anlaşmaları, ihale/mezat sonuçları, tatil ve kurumsal etkinlik haberleri, ziyaretler, konuşma ve röportajlar, atama, tek bir kuruma
lisans verme/iptal/vesayet, yaptırım listeleri, tüketici kampanyaları, ödeme sistemi ve ürün tanıtımları, destek/garanti programları,
genel finansal istikrar raporları (yalnız risk metodolojisi değişikliği içeriyorsa ilgili), menü ve bölüm adları, dolandırıcılık
ve siber saldırı uyarıları, mutabakat zaptı imzaları, fintek/inovasyon/dijital kimlik lansmanları, eğitim, çalıştay ve tatbikat
haberleri, ödeme sistemi çalışma saatleri, forum ve ödül haberleri, AML/CFT bülten ve uyarıları (yalnız risk yönetimi düzenlemesiyse ilgili).
Emin değilsen relevant=false. relevant=true yalnız bankaların risk yönetimini, sermaye/likidite hesaplamasını, modellerini ya da
denetim beklentilerini doğrudan etkileyen düzenleme, rehber, istişare, sirküler ve Basel standartları için.
Her başlık için SADECE şu JSON dizisini döndür (aynı sırayla, i numarasıyla):
{"items": [{"i": 0, "relevant": true, "topics": ["mrm","irb","aiml","backtest","ecl","stress","icaap","alm","basel","credit","market","oprisk","climate","gov"],
"type": "taslak|nihai|rehber|duyuru", "title_tr": "Türkçe başlık", "summary_tr": "1 cümle: ne düzenleniyor, kimi etkiliyor"}]}
İlgisizlerde yalnız {"i": n, "relevant": false} yeterli. Başlık Arapça ise Türkçeye çevir."""
CLS_TOOL = {"name": "classify", "description": "Doküman sınıflandırması", "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}}}
TOPIC_KEYS = {"mrm", "irb", "aiml", "backtest", "ecl", "stress", "icaap", "alm", "basel", "credit", "market", "oprisk", "climate", "gov"}


def classify(analyzer, batch: list[dict], regs: dict) -> list[dict] | None:
    lines = "\n".join(f"{i}. [{regs[it['reg']]['name']}] {it['title']}" + (f" — {it['desc'][:160]}" if it.get("desc") else "") +
                      (f" (BIS türü: {it['hint']})" if it.get("hint") else "") for i, it in enumerate(batch))
    x = analyzer.ask_json(CLS_SYSTEM, "BAŞLIKLAR:\n" + lines, CLS_TOOL, CLS_FMT, max_tokens=3000, light=True)
    if not isinstance(x, dict) or not isinstance(x.get("items"), list):
        return None
    out = []
    for r in x["items"]:
        if not isinstance(r, dict) or not isinstance(r.get("i"), int) or not 0 <= r["i"] < len(batch):
            continue
        out.append(r)
    return out


SUMMARY_SYSTEM = "Sen kıdemli bir finansal regülasyon, risk yönetimi ve model validasyonu analistisin."
SUMMARY_FMT = """
SADECE JSON: {"trends": [{"title": "kısa başlık", "detail": "2-3 cümle; somut doküman ve kurum adlarıyla", "regulators": ["kurum"],
"tr_impact": "Türkiye'deki bankalar için tek cümle çıkarım"}]}  — tam 3 eğilim."""


def summarize(analyzer, items: list[dict], regs: dict, today: dt.date) -> dict | None:
    since = (today - dt.timedelta(days=90)).isoformat()
    recent = [i for i in items if i.get("relevant") and (i.get("date") or "") >= since][:80]
    if len(recent) < 3:
        return None
    docs = "\n".join(f"- {regs[i['reg']]['name']} | {i.get('date') or '?'} | {i['title']} | {TYPES.get(i.get('type'), '')} | {i.get('summary') or ''}"
                     for i in recent)
    x = analyzer.ask_json(SUMMARY_SYSTEM, "Son 90 günün risk yönetimi ve model validasyonu dokümanları. Dönemin en kritik 3 regülatif "
                          "eğilimini çıkar.\n\n" + docs, CLS_TOOL, SUMMARY_FMT, max_tokens=2000)
    if isinstance(x, dict) and isinstance(x.get("trends"), list) and x["trends"]:
        return {"date": today.isoformat(), "n_docs": len(recent), "trends": x["trends"][:3], "model": x.get("_model")}
    return None


# ─────────────────────────────── durum ve çalıştırma
def load_config(path=None) -> dict:
    return yaml.safe_load((path or CONFIG / "regwatch.yml").read_text(encoding="utf-8"))


def load_state() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"items": [], "summary": None}


def save_state(st: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    st["items"].sort(key=lambda x: (x.get("date") or x.get("first_seen", "")[:10], x.get("first_seen") or ""), reverse=True)
    OUT.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def future_date(it: dict, today: dt.date) -> dict:
    """Gelecek tarih yayın tarihi olamaz: sayfa yürürlük tarihini veriyor (ör. CBUAE Rulebook "effective date").
    Yürürlük tarihi ayrı alana taşınır; yayın tarihi yerine ilk görüldüğü gün kullanılır ve tahmini olduğu işaretlenir."""
    d = it.get("date")
    if d and d > (today + dt.timedelta(days=1)).isoformat():
        it["effective"] = d
        it["date"] = (it.get("first_seen") or today.isoformat())[:10]
        it["date_est"] = True
    return it


def run(today: dt.date | None = None, analyzer=None, fetcher: Fetcher | None = None, max_batches: int = 25) -> dict:
    today = today or dt.date.today()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cfg = load_config()
    regs = {r["id"]: r for r in cfg["regulators"]}
    st = load_state()
    first_run = not st["items"]
    known = {i["url"] for i in st["items"]}
    found, status = collect(cfg, fetcher)
    for it in found:
        if it["url"] in known or (it.get("date") and it["date"] < SINCE):
            continue
        known.add(it["url"])
        it.update({"first_seen": now, "baseline": first_run and not it.get("date")})
        st["items"].append(it)
    for it in st["items"]:
        future_date(it, today)
    if analyzer is None:
        from .analyze import Analyzer
        from .config import load_settings
        analyzer = Analyzer(load_settings())
    pending = [i for i in st["items"] if "relevant" not in i]
    t0 = time.monotonic()
    pending.sort(key=lambda i: i.get("date") or "", reverse=True)        # en yeniler önce
    for b in range(0, min(len(pending), max_batches * 20), 20):
        if time.monotonic() - t0 > 18 * 60:
            break
        batch = pending[b:b + 20]
        res = classify(analyzer, batch, regs) if getattr(analyzer, "providers", None) else None
        if res is None:
            if getattr(analyzer, "last_blocked", False) or not getattr(analyzer, "providers", None):
                break                                              # kota/AI yok: kalanlar sonraki turda
            continue
        for r in res:
            it = batch[r["i"]]
            it["relevant"] = bool(r.get("relevant"))
            if it["relevant"]:
                it["topics"] = [t for t in (r.get("topics") or []) if t in TOPIC_KEYS]
                typ = str(r.get("type") or "duyuru").lower()
                it["type"] = typ if typ in TYPES else "duyuru"
                it["title_tr"] = str(r.get("title_tr") or "").strip()[:300] or None
                it["summary"] = str(r.get("summary_tr") or "").strip()[:400] or None
        for it in batch:                                           # yanıtta olmayan başlık: ilgisiz say
            it.setdefault("relevant", False)
    if not st.get("summary") or st["summary"].get("date", "") <= (today - dt.timedelta(days=7)).isoformat():
        s = summarize(analyzer, st["items"], regs, today) if getattr(analyzer, "providers", None) else None
        if s:
            st["summary"] = s
    st["status"] = status
    st["regulators"] = [{"id": r["id"], "name": r["name"], "country": r["country"], "blocked": r.get("blocked"), "note": r.get("note"),
                         "sources": [s["url"] for s in r.get("sources") or []]} for r in cfg["regulators"]]
    st["topics"] = cfg["topics"]
    st["types"] = TYPES
    st["generated"] = now
    save_state(st)
    return st


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    st = run()
    rel = sum(1 for i in st["items"] if i.get("relevant"))
    log.info("Regülasyon: %d bağlantı, %d ilgili, %d sınıflandırılmadı", len(st["items"]), rel,
             sum(1 for i in st["items"] if "relevant" not in i))
    return 0


if __name__ == "__main__":
    sys.exit(main())
