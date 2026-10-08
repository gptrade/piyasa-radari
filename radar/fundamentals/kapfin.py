"""KAP finansal rapor bildirimlerinden mali tabloları okur.

KAP her "Finansal Rapor" bildirimi için `/tr/api/notification/export/excel/{idx}` adresinde
Excel uyumlu bir HTML dosyası verir. İçinde bilanço, kar/zarar ve nakit akış tabloları
standart TFRS kalem adlarıyla bulunur. Bu modül o dosyayı sade bir sözlüğe çevirir:

    {"year": 2026, "period": 2, "consolidated": True, "currency": "TRY", "scale": 1000,
     "template": "sanayi" | "finansal",
     "bs": {"cols": [{"end": "2026-06-30"}, ...], "rows": {"Dönen Varlıklar": [..], ...}},
     "is": {"cols": [{"start": "2026-01-01", "end": "2026-06-30"}, ...], "rows": {...}},
     "cf": {...}}

Değerler raporda yazdığı gibi (sunum birimi cinsinden) saklanır; `scale` ile çarpılınca TL olur.
Aynı adlı ikinci kalem "Ad#2" diye saklanır (ör. kapsamlı gelirin "Ana Ortaklık Payları").
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta

from lxml import html as LH

from .. import http

log = logging.getLogger("radar.fundamentals.kap")

LIST_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
EXPORT_URL = "https://www.kap.org.tr/tr/api/notification/export/excel/{idx}"
INDEX_URL = "https://www.kap.org.tr/tr/Endeksler"
SECTOR_URL = "https://www.kap.org.tr/tr/Sektorler"
HEADERS = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json",
           "Content-Type": "application/json"}

KINDS = (("bs", re.compile(r"^(Finansal Durum Tablosu|Bilanço|BİLANÇO)")),
         ("is", re.compile(r"^(Kar veya Zarar|Gelir Tablosu|GELİR TABLOSU)")),
         ("cf", re.compile(r"^(Nakit Akış|NAKİT AKIŞ|Nakit Akım|NAKİT AKIM)")))
SUBHEAD = {"TP", "YP", "Toplam", "TOPLAM"}
LIST_GAP = 2.0
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
NUM = re.compile(r"^\(?-?[\d.]+(,\d+)?\)?$")


class RateLimited(Exception):
    """KAP 429 döndü: bu çalıştırmada KAP'a daha fazla istek atılmaz."""


REQUESTS = 0   # bu çalıştırmada KAP'a atılan istek sayısı (store bütçe için okur)
EXPORTS = 0    # dışa aktarım (excel) indirmeleri: KAP ~5 dakikada 10'dan fazlasına 429 veriyor


def _kap(method: str, url: str, **kw):
    """KAP isteği; 429'da RateLimited fırlatır, diğer hatalarda None döner."""
    global REQUESTS
    REQUESTS += 1
    headers = {"User-Agent": http.DEFAULT_UA, "Accept-Language": "tr,en;q=0.8", **kw.pop("headers", {})}
    try:
        r = http._session.request(method, url, headers=headers, timeout=kw.pop("timeout", 90), **kw)
    except Exception as e:  # ağ hatası
        log.warning("KAP %s %s -> %s", method, url[-60:], e)
        return None
    if r.status_code == 429:
        raise RateLimited(url)
    if r.status_code != 200:
        log.warning("KAP %s %s -> HTTP %s", method, url[-60:], r.status_code)
        return None
    return r


def _d(m: re.Match) -> str:
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def parse_num(s: str) -> float | None:
    s = (s or "").strip().replace("\xa0", "").replace(" ", "")
    if not s or not NUM.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.startswith("(-")
    s = s.strip("()").lstrip("-")
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_scale(text: str) -> tuple[str, int]:
    """'Sunum Para Birimi 1.000 TL' → ('TRY', 1000)."""
    m = re.search(r"Sunum Para Birimi\s*([\d.]*)\s*([A-ZÇĞİÖŞÜa-z]{2,4})", text)
    if not m:
        return "TRY", 1
    mult = int(m.group(1).replace(".", "")) if m.group(1).replace(".", "") else 1
    cur = m.group(2).upper()
    cur = {"TL": "TRY", "TRL": "TRY", "YTL": "TRY"}.get(cur, cur)
    return cur, mult


def _cells(tr) -> list[str]:
    return [re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.xpath("./td|./th")]


def _cols(header: list[str], kind: str) -> list[dict]:
    out = []
    for h in header[1:]:
        ds = list(DATE.finditer(h))
        col: dict = {"label": h}
        if kind == "bs" and ds:
            col["end"] = _d(ds[-1])
        elif len(ds) >= 2:
            col["start"], col["end"] = _d(ds[0]), _d(ds[-1])
        elif ds:
            col["end"] = _d(ds[-1])
        col["prior"] = h.lower().startswith("önceki")
        out.append(col)
    return out


def _subhead(row: list[str]) -> list[str] | None:
    """Banka bilançosunun 'TP | YP | Toplam' alt başlığı."""
    xs = [c for c in row if c]
    return xs if xs and set(xs) <= SUBHEAD and ("Toplam" in xs or "TOPLAM" in xs) else None


def parse_table(rows: list[list[str]], kind: str) -> dict:
    cols = _cols(rows[0], kind)
    sub = _subhead(rows[1]) if len(rows) > 1 else None
    if sub:                                   # her dönem TP/YP/Toplam; yalnız Toplam sütunları alınır
        n_sub = len(sub)
        keep = [i for i, c in enumerate(sub) if c.lower() == "toplam"]
        seen: dict[str, int] = {}
        out: dict[str, list] = {}
        for cells in rows[2:]:
            if len(cells) < n_sub + 1:
                continue
            label = next((c for c in cells[:2] if c), "")
            if not label or NUM.match(label):
                continue
            tail = cells[-n_sub:]
            vals = [parse_num(tail[i]) for i in keep]
            seen[label] = seen.get(label, 0) + 1
            key = label if seen[label] == 1 else f"{label}#{seen[label]}"
            if any(v is not None for v in vals):
                out[key] = vals
        return {"cols": cols[:len(keep)], "rows": out}
    n = len(cols)
    seen: dict[str, int] = {}
    out: dict[str, list] = {}
    for cells in rows[2:]:
        if len(cells) < n + 1:
            continue
        label = next((c for c in cells[:2] if c), "")
        if not label or NUM.match(label):
            continue
        vals = [parse_num(c) for c in cells[-n:]]
        seen[label] = seen.get(label, 0) + 1
        key = label if seen[label] == 1 else f"{label}#{seen[label]}"
        if any(v is not None for v in vals):
            out[key] = vals
    return {"cols": cols, "rows": out}


def parse_export(content: bytes | str) -> dict:
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    doc = LH.fromstring(text)
    flat = re.sub(r"\s+", " ", doc.text_content())
    rep: dict = {}
    m = re.search(r"Yıl:\s*(\d{4})\s*Periyot:\s*(\d)", flat)
    if m:
        rep["year"], rep["period"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"Finansal Tablo Niteliği\s*(Konsolide Olmayan|Konsolide)", flat)
    rep["consolidated"] = bool(m) and m.group(1) == "Konsolide"
    rep["currency"], rep["scale"] = parse_scale(flat)
    for tb in doc.xpath("//table"):
        trs = tb.xpath("./tr|./tbody/tr")
        if len(trs) < 10:
            continue
        rows = [_cells(tr) for tr in trs]
        title = next((c for c in rows[1] if c), "") if len(rows) > 1 else ""
        if len(rows) > 1 and _subhead(rows[1]):
            # Banka: başlıksız TP/YP tablosu; varlık+yükümlülük olan bilançodur (bilanço dışı tablo atlanır)
            body = " ".join(r[1] if len(r) > 1 else "" for r in rows[2:])
            if "bs" not in rep and "VARLIKLAR TOPLAMI" in body:
                rep["bs"] = parse_table(rows, "bs")
                rep["bs"]["title"] = "Bilanço (Finansal Durum Tablosu)"
            continue
        for kind, rx in KINDS:
            if kind not in rep and rx.match(title):
                rep[kind] = parse_table(rows, kind)
                rep[kind]["title"] = title
    rep["template"] = template_of(rep)
    return rep


def template_of(rep: dict) -> str:
    is_rows = rep.get("is", {}).get("rows", {})
    title = rep.get("is", {}).get("title", "")
    labels = {k.split("#")[0].strip().upper() for k in is_rows}
    if "NET FAİZ GELİRİ VEYA GİDERİ" in labels or "NET FAİZ GELİRİ/GİDERİ" in labels:
        return "banka"
    if any("TEKNİK BÖLÜM DENGESİ" in l for l in labels):
        return "sigorta"
    if "Hasılat" in is_rows and "TFRS 9" not in title:
        return "sanayi"
    return "finansal"


def fetch_export(idx: int) -> dict | None:
    global EXPORTS
    EXPORTS += 1
    r = _kap("GET", EXPORT_URL.format(idx=idx), timeout=120)
    if r is None:
        return None
    try:
        rep = parse_export(r.content)
    except Exception as e:  # bozuk/boş dosya
        log.warning("KAP export %s ayrıştırılamadı: %s", idx, e)
        return None
    rep["idx"] = idx
    return rep


# ---- Bildirim listesi ----

def is_fr(row: dict) -> bool:
    return row.get("disclosureClass") == "FR" and \
        (row.get("subject") or "").strip() in ("Finansal Rapor", "Finansal Rapor Bildirimi")


DIV_SUBJECTS = ("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim", "Kar Payı Bildirimi")


def is_div(row: dict) -> bool:
    return (row.get("subject") or "").strip() in DIV_SUBJECTS


def wanted(row: dict) -> bool:
    return is_fr(row) or is_div(row)


def list_reports(oid: str, start: date, end: date) -> list[dict] | None:
    """Bir şirketin [start, end] arasındaki finansal rapor bildirimleri (KAP bir yıllık pencere kabul ediyor)."""
    out: list[dict] = []
    frm = start
    while frm <= end:
        to = min(end, frm + timedelta(days=364))
        r = _kap("POST", LIST_URL, json={"fromDate": frm.isoformat(), "toDate": to.isoformat(),
                                         "mkkMemberOidList": [oid], "subjectList": []}, headers=HEADERS)
        if r is None:
            return None   # eksik liste kaydedilmesin; sonra yeniden denenir
        if r is not None:
            try:
                out += [x for x in r.json() if wanted(x)]
            except ValueError:
                log.warning("KAP liste JSON dönmedi (%s)", oid)
                return None
        frm = to + timedelta(days=1)
        time.sleep(LIST_GAP)
    return out


def recent_reports(days: int = 3) -> list[dict]:
    """Son günlerin tüm finansal rapor bildirimleri (gün gün; KAP tek istekte en fazla 2000 satır döner)."""
    out: list[dict] = []
    today = date.today()
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        r = _kap("POST", LIST_URL, json={"fromDate": d.isoformat(), "toDate": d.isoformat(),
                                         "mkkMemberOidList": [], "subjectList": []}, headers=HEADERS)
        if r is not None:
            try:
                out += [x for x in r.json() if wanted(x)]
            except ValueError:
                pass
    return out


def codes_of(row: dict) -> list[str]:
    raw = row.get("stockCodes") or row.get("relatedStocks") or ""
    return [c.strip().upper() for c in str(raw).replace(";", ",").split(",") if c.strip()]


def period_key(year: int, period: int) -> str:
    return f"{year}/{period * 3:02d}"


# ---- Endeks üyeleri ----

def parse_indices(text: str) -> dict[str, list[dict]]:
    """KAP Endeksler sayfasındaki gömülü veriden {'XU100': [{'code','title','oid'}, ...]}."""
    t = text.replace('\\"', '"')
    out: dict[str, list[dict]] = {}
    for m in re.finditer(r'\{"code":"(X[A-Z0-9]+)","content":\[(.*?)\]', t):
        members = [{"code": a, "title": b, "oid": c} for a, b, c in
                   re.findall(r'"stockCode":"([A-Z0-9]+)","title":"([^"]*)","mkkMemberOid":"([0-9a-f]+)"', m.group(2))]
        if members and m.group(1) not in out:
            out[m.group(1)] = members
    return out


def fetch_indices() -> dict[str, list[dict]]:
    r = http.get(INDEX_URL, timeout=60)
    return parse_indices(r.text) if r is not None else {}


# ---- Sektörler ----

def parse_sectors(text: str) -> dict[str, dict]:
    """KAP Sektörler sayfasından {kod: {'sector': alt sektör, 'main': ana sektör}}. İlk görülen alt sektör esas alınır."""
    t = text.replace('\\"', '"')
    out: dict[str, dict] = {}
    # Birden çok kodu olan şirketler "GARAN, TGB" biçiminde gelir
    for name, codes in re.findall(r'"sectorName":"([^"]+)","sectorOid":"[^"]*","sectorNo":"[^"]*",'
                                  r'"mkkMemberOid":"[^"]*","stockCode":"([A-Z0-9, ]+)"', t):
        for code in (c.strip() for c in codes.split(",") if c.strip()):
            out.setdefault(code, {})["sector"] = out.get(code, {}).get("sector") or name
    for name, codes in re.findall(r'"mainSectorName":"([^"]+)","mainSectorOid":"[^"]*","mainSectorNo":"[^"]*",'
                                  r'"mkkMemberOid":"[^"]*","stockCode":"([A-Z0-9, ]+)"', t):
        for code in (c.strip() for c in codes.split(",") if c.strip()):
            out.setdefault(code, {})["main"] = out.get(code, {}).get("main") or name
    return out


def fetch_sectors() -> dict[str, dict]:
    r = http.get(SECTOR_URL, timeout=60)
    return parse_sectors(r.text) if r is not None else {}
