"""KAP "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim"lerinden temettü bilgisi.

Bildirim sayfası Next.js akışı içinde kaçışlı HTML taşır; çözülünce tablolar düzenli:
  Özet Bilgi · Karar/Genel Kurul tarihi, ödeme şekli · pay grubu başına brüt/net (taksitli olabilir)
  · taksit tarihleri (hak kullanım, ödeme, kayıt) · kâr dağıtım tablosu toplamları.
Yalnız yapılandırılmış alanlar saklanır.
"""
from __future__ import annotations

import logging
import re

from lxml import html as LH

from . import kapfin

log = logging.getLogger("radar.fundamentals.div")

DETAIL_URL = "https://www.kap.org.tr/tr/Bildirim/{idx}"
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


is_div = kapfin.is_div


def _iso(s: str) -> str | None:
    m = DATE.search(s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def decode_page(text: str) -> str:
    """Akıştaki \\u003c… kaçışlarını ve \\" tırnaklarını çözer."""
    if "\\u003c" in text:
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
    return text.replace('\\"', '"').replace("\\n", " ")


def _cells(tr) -> list[str]:
    return [re.sub(r"\s+", " ", td.text_content()).strip() for td in tr.xpath("./td|./th")]


def parse(text: str, code: str | None = None) -> dict | None:
    doc = LH.fromstring(decode_page(text))
    out: dict = {"installments": []}
    groups: list[dict] = []
    for tb in doc.xpath("//table"):
        if tb.xpath(".//table"):
            continue
        rows = [_cells(tr) for tr in tb.xpath(".//tr")]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        head = " ".join(rows[0])
        if rows[0][0] == "Özet Bilgi" and len(rows[0]) > 1:
            out["summary"] = rows[0][1]
        elif rows[0][0] == "Karar Tarihi" or any(r[0] == "Nakit Kar Payı Ödeme Şekli" for r in rows):
            kv = {r[0]: r[1] for r in rows if len(r) >= 2}
            out["decision"] = _iso(kv.get("Karar Tarihi", ""))
            out["gm"] = _iso(kv.get("Konunun Gündemde Yer Aldığı Genel Kurul Tarihi", ""))
            out["method"] = kv.get("Nakit Kar Payı Ödeme Şekli")
            out["currency"] = kv.get("Para Birimi") or "TRY"
        elif "Nakit Kar Payı - Brüt(TL)" in head:
            for r in rows[1:]:
                if len(r) < 7:
                    continue
                groups.append({"group": r[0], "pay": r[1], "gross": kapfin.parse_num(r[2]),
                               "stopaj": kapfin.parse_num(r[4]), "net": kapfin.parse_num(r[5])})
        elif head.startswith("Ödeme") and "Hak Kullanım" in head:
            for r in rows[1:]:
                if len(r) >= 5:
                    out["installments"].append({"label": r[0], "ex_proposed": _iso(r[1]), "ex": _iso(r[2]) or _iso(r[1]),
                                                "pay": _iso(r[3]), "record": _iso(r[4])})
        elif "NET DAĞITILABİLİR DÖNEM KARI (%)" in head:
            tot = next((r for r in rows[1:] if r[0].upper() == "TOPLAM"), None)
            if tot and len(tot) >= 4:
                out["total_net"] = kapfin.parse_num(tot[1])
                out["payout"] = kapfin.parse_num(tot[3])
    if "summary" not in out:
        return None
    # İşlem gören grup: kodu geçen satırlar, yoksa ilk grup
    traded = [g for g in groups if code and code in g["group"]] or [g for g in groups if "İşlem Görmüyor" not in g["group"]] or groups
    name = traded[0]["group"] if traded else None
    mine = [g for g in groups if g["group"] == name]
    total = next((g for g in mine if g["pay"].upper() == "TOPLAM"), None)
    parts = [g for g in mine if g["pay"].upper() != "TOPLAM"]
    if total is None and parts:
        total = {"gross": sum(g["gross"] or 0 for g in parts), "net": sum(g["net"] or 0 for g in parts),
                 "stopaj": parts[0]["stopaj"]}
    out["gross"] = total["gross"] if total else None
    out["net"] = total["net"] if total else None
    out["stopaj"] = total["stopaj"] if total else None
    for inst in out["installments"]:
        g = next((p for p in parts if p["pay"] == inst["label"]), None)
        if g:
            inst["gross"], inst["net"] = g["gross"], g["net"]
    none = (out.get("method") or "").startswith("Ödenmeyecek") or not out["gross"]
    s = (out.get("summary") or "").lower()
    out["status"] = "yok" if none else ("kesin" if ("sonuc" in s or "onaylan" in s or "genel kurul" in s and "öneri" not in s) else "öneri")
    return out


def fetch(idx: int, code: str) -> dict | None:
    r = kapfin._kap("GET", DETAIL_URL.format(idx=idx), timeout=60)
    if r is None:
        return None
    try:
        d = parse(r.text, code)
    except Exception as e:
        log.warning("Kar payı bildirimi %s ayrıştırılamadı: %s", idx, e)
        return None
    if d:
        d["idx"] = idx
    return d


def calendar_events(divs: dict[str, list[dict]], lo: str, hi: str) -> list[dict]:
    """Takvim için: hak kullanım ve ödeme günleri (calendar_events.extra_events biçimi)."""
    out = []
    for code, evs in divs.items():
        for d in evs:
            if d.get("status") == "yok":
                continue
            for inst in d.get("installments") or []:
                g, n = inst.get("gross") or d.get("gross"), inst.get("net") or d.get("net")
                amt = (f"pay başına brüt {g:.4f} TL".replace(".", ",") + (f", net {n:.4f} TL".replace(".", ",") if n else "")) if g else ""
                tag = "" if d.get("status") == "kesin" else " (öneri, genel kurul onayı bekleniyor)"
                label = f" · {inst['label']}" if inst.get("label") and "Taksit" in inst["label"] else ""
                if inst.get("ex") and lo <= inst["ex"] <= hi:
                    out.append({"kind": "dividend", "date": inst["ex"], "market": "BIST", "ticker": code,
                                "title": f"{code} temettü hak kullanım", "importance": 2,
                                "detail": f"KAP{label}: {amt}{tag}; bu tarihte ve sonrasında alınan payda hak yoktur"
                                          + (f" · ödeme {inst['pay']}" if inst.get("pay") else ""),
                                "url": DETAIL_URL.format(idx=d.get("idx", ""))})
    return out
