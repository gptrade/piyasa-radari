"""Belge okuma: KAP yatırımcı sunumu / finansal rapor / faaliyet raporu ve SEC 8-K ekleri (EX-99).

İzleme listesindeki şirketlerin bu tür bildirimlerinde ekli belge (PDF) ya da bildirim sayfası indirilir,
metni çıkarılır ve AI değerlendirmesine tam metin olarak verilir. AI bu durumda belge özeti üretir:
öne çıkan bulgular, önemli rakamlar (önceki döneme göre), rehberlik ve riskler.

Belge metni panele YAZILMAZ (pipeline `full_text`i kaydetmeden siler); yalnız AI özeti ve belge künyesi
(tür, dosya sayısı, sayfa) yayımlanır. Kaynak belgeye bağlantı bildirimin kendisidir.
"""
from __future__ import annotations

import html as htmlmod
import io
import logging
import re

from . import http
from .models import Item

log = logging.getLogger("radar.documents")

KAP_FILE = re.compile(r"https://www\.kap\.org\.tr/tr/api/file/download/[0-9a-fA-F]{32}")
# KAP bildirim konusu → belge türü (sıra önemli: özel olan önce)
KAP_KINDS = [
    ("yatırımcı sunumu", "Yatırımcı sunumu"),
    ("sunum", "Yatırımcı sunumu"),
    ("faaliyet raporu", "Faaliyet raporu"),
    ("finansal rapor", "Finansal rapor"),
    ("yatırımcı raporu", "Yatırımcı raporu"),
    ("değerleme raporu", "Değerleme raporu"),
]
# Genel özel durum açıklamalarında sunum ekini yakalamak için (konu "Özel Durum Açıklaması (Genel)" olabiliyor)
PRESENTATION = re.compile(r"sunum|presentation|analist toplant|investor day|webcast", re.I)
SEC_FORMS = {"8-K", "6-K"}
SEC_PERIODIC = {"10-Q": "10-Q çeyreklik rapor", "10-K": "10-K yıllık rapor"}
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 40
MAX_CHARS = 40000


def _low(s: str) -> str:
    return (s or "").replace("İ", "i").replace("I", "ı").lower()


def doc_kind(it: Item) -> str | None:
    """Kayıt belge okumaya değer mi? Değerse belge türü."""
    ex = it.extra
    if it.source == "KAP":
        subj = _low(ex.get("subject"))
        for key, label in KAP_KINDS:
            if key in subj:
                return label
        if (ex.get("att") or 0) > 0 and PRESENTATION.search(f"{ex.get('subject') or ''} {it.summary}"):
            return "Yatırımcı sunumu"
        return None
    if it.source == "SEC EDGAR" and ex.get("form") in SEC_FORMS:
        return f"{ex['form']} eki (EX-99)"
    if it.source == "SEC EDGAR" and ex.get("form") in SEC_PERIODIC:
        return SEC_PERIODIC[ex["form"]]
    return None


def html_text(s: str) -> str:
    s = re.sub(r"(?is)<!--.*?-->|<(script|style|noscript|svg)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = htmlmod.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\s*\n\s*", "\n", s).strip()


def pdf_bytes(content: bytes) -> bytes | None:
    """KAP indirmesi PDF'i Java serileştirme başlığıyla sarmalayabiliyor (b'\\xac\\xed…[B…%PDF'): baştaki
    sarmalayıcı atlanır. PDF değilse None."""
    i = content.find(b"%PDF", 0, 2048)
    return content[i:] if i >= 0 else None


def pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = reader.pages[:MAX_PAGES]
    return "\n".join((p.extract_text() or "") for p in pages), len(reader.pages)


def fit(text: str, anchors: tuple[str, ...] = ()) -> str:
    """Uzun metni MAX_CHARS'a sığdır: baştan yarısı + (varsa) çapa noktasından (ör. gelir tablosu) yarısı."""
    if len(text) <= MAX_CHARS:
        return text
    half = MAX_CHARS // 2
    low = text.lower()
    for a in anchors:
        i = low.find(a.lower(), half)
        if i > 0:
            return text[:half] + "\n…\n" + text[i:i + half]
    return text[:MAX_CHARS]


INCOME = ("kar veya zarar kısmı", "kâr veya zarar kısmı", "kar veya zarar tablosu", "gelir tablosu",
          "income statement", "statements of operations")


def kap_body(page: str, filer: str | None) -> str:
    """Bildirim sayfası metni; üstteki site menüsü atılır (şirket adının ilk geçtiği yerden başlar)."""
    text = html_text(page)
    if filer:
        i = _low(text).find(_low(filer)[:30], 800)
        if i > 0:
            text = text[i:]
    return text


def fetch_kap(it: Item) -> tuple[str, list[dict]] | None:
    url = it.url
    r = http.get(url, timeout=60, retries=1)
    if r is None:
        return None
    page = r.text
    parts, files = [], []
    for link in list(dict.fromkeys(KAP_FILE.findall(page)))[:3]:
        f = http.get(link, timeout=90, retries=1)
        if f is None or len(f.content) > MAX_PDF_BYTES:
            continue
        data = pdf_bytes(f.content)
        if data is None:
            continue                                       # Excel/Word ekleri: bildirim sayfasındaki metin yeterli
        try:
            text, n = pdf_text(data)
        except Exception as e:
            log.warning("KAP eki okunamadı (%s): %s", link[-12:], e)
            continue
        if len(text.strip()) < 200:                        # taranmış (resim) PDF
            files.append({"type": "PDF", "pages": n, "note": "metin çıkmadı"})
            continue
        parts.append(text)
        files.append({"type": "PDF", "pages": n})
    body = kap_body(page, it.extra.get("filer"))
    # Finansal raporda tablolar sayfanın kendisinde; sunumda asıl içerik ekte
    if not parts or "rapor" in _low(it.extra.get("subject")):
        parts.insert(0, body)
        files.insert(0, {"type": "Bildirim sayfası"})
    text = "\n\n".join(parts)
    return (fit(text, INCOME), files) if len(text) > 300 else None


# 10-Q: Item 2 (MD&A) → Item 3; 10-K: Item 7 (MD&A) → Item 7A/8. Risk faktörleri: Item 1A → Item 2 / 1B.
SECTIONS = {
    "10-Q": [(r"Item\s*2\.?\s*Management.{0,3}s\s+Discussion", r"Item\s*3\.?\s*Quantitative|Item\s*4\.?\s*Controls"),
             (r"Item\s*1A\.?\s*Risk\s+Factors", r"Item\s*2\.?\s*Unregistered|Item\s*5\.?|Item\s*6\.?\s*Exhibits")],
    "10-K": [(r"Item\s*7\.?\s*Management.{0,3}s\s+Discussion", r"Item\s*7A\.?|Item\s*8\.?\s*Financial"),
             (r"Item\s*1A\.?\s*Risk\s+Factors", r"Item\s*1B\.?|Item\s*1C\.?|Item\s*2\.?\s*Properties")],
}


def section(text: str, start: str, end: str, limit: int) -> str:
    """Başlığın SON geçtiği yer (ilk geçişler içindekiler tablosudur) ile bitiş başlığı arası."""
    starts = [m.start() for m in re.finditer(start, text, re.I)]
    for st in reversed(starts):
        m = re.search(end, text[st + 200:], re.I)
        body = text[st:st + 200 + m.start()] if m else text[st:st + limit]
        if len(body) > 1500:                     # içindekiler satırı değil, asıl bölüm
            return body[:limit]
    return ""


def periodic_text(text: str, form: str) -> str:
    mdna, risk = SECTIONS[form]
    a = section(text, *mdna, limit=30000)
    b = section(text, *risk, limit=8000)
    parts = ([f"[YÖNETİMİN DEĞERLENDİRMESİ (MD&A)]\n{a}"] if a else []) + ([f"[RİSK FAKTÖRLERİ]\n{b}"] if b else [])
    return "\n\n".join(parts)


def fetch_sec(it: Item) -> tuple[str, list[dict]] | None:
    base = it.url.rsplit("/", 1)[0]
    r = http.get(f"{base}/index.json", headers={"User-Agent": http.SEC_UA}, timeout=30, retries=1)
    if r is None:
        return None
    try:
        rows = r.json()["directory"]["item"]
        names = [x["name"] for x in rows]
    except (ValueError, KeyError, TypeError):
        return None
    form = it.extra.get("form")
    if form in SEC_PERIODIC:
        htm = [x for x in rows if x["name"].lower().endswith(".htm") and not re.search(r"index|^R\d|ex-?\d", x["name"], re.I)]
        if not htm:
            return None
        main = max(htm, key=lambda x: int(x.get("size") or 0))["name"]
        f = http.get(f"{base}/{main}", headers={"User-Agent": http.SEC_UA}, timeout=90, retries=1)
        if f is None:
            return None
        text = periodic_text(html_text(f.text), form)
        return (text, [{"type": form, "name": main}]) if len(text) > 1500 else None
    ex = [n for n in names if re.search(r"ex-?99", n, re.I) and n.lower().endswith((".htm", ".html", ".txt"))][:2]
    parts, files = [], []
    for n in ex:
        f = http.get(f"{base}/{n}", headers={"User-Agent": http.SEC_UA}, timeout=60, retries=1)
        if f is None:
            continue
        parts.append(html_text(f.text) if not n.lower().endswith(".txt") else f.text)
        files.append({"type": "EX-99", "name": n})
    text = "\n\n".join(parts)
    return (fit(text, INCOME), files) if len(text) > 300 else None


def attach(items: list[Item], watch: set[str], cfg: dict) -> dict:
    """Uygun kayıtlara belge metnini ekler (extra.full_text + extra.doc). Durum özeti döner."""
    if not cfg.get("enabled", True):
        return {"count": 0}
    limit = int(cfg.get("max_per_run", 4))
    done, tried = 0, 0
    for it in items:
        if done >= limit or tried >= limit * 2:
            break
        if not set(it.tickers) & watch or it.extra.get("full_text"):
            continue
        kind = doc_kind(it)
        if not kind:
            continue
        tried += 1
        try:
            got = fetch_kap(it) if it.source == "KAP" else fetch_sec(it)
        except Exception as e:
            log.warning("Belge alınamadı (%s): %s", it.url[:80], e)
            got = None
        if not got:
            continue
        text, files = got
        it.extra["full_text"] = text
        it.extra["doc"] = {"kind": kind, "files": files, "chars": len(text)}
        done += 1
    log.info("Belge: %d okundu (%d denendi)", done, tried)
    return {"count": done, "tried": tried}
