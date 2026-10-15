"""KAP sözleşme/ihale bildirimlerinin büyüklüğü: tutar / son 12 ay hasılat.

"Yeni iş ilişkisi", sözleşme, ihale ve sipariş bildirimlerinde bildirim sayfası okunur, metindeki para tutarları
çıkarılır, en büyüğü TCMB kuruyla TL'ye çevrilir ve şirketin son 12 aylık hasılatına (temel analiz verisi) bölünür.
Sonuç `extra["deal"]`a yazılır: AI değerlendirmesi bunu görür ve önem derecesi orana göre ayarlanır.
Cirosunun %1'i olan iş ile %35'i olan iş aynı ağırlıkta gösterilmez.
"""
from __future__ import annotations

import json
import logging
import re

from . import http
from .config import DATA
from .documents import _low, kap_body
from .models import Item

log = logging.getLogger("radar.deals")

SUBJECT = re.compile(r"yeni iş ilişkisi|(?<!esas )sözleşme|ihale|sipariş|anlaşma imza", re.I)
NOT_DEAL = re.compile(r"esas sözleşme|ana sözleşme", re.I)
CUR = {"tl": "TRY", "try": "TRY", "₺": "TRY", "türk lirası": "TRY", "usd": "USD", "$": "USD", "abd doları": "USD",
       "amerikan doları": "USD", "dolar": "USD", "eur": "EUR", "€": "EUR", "avro": "EUR", "euro": "EUR"}
MULT = {"bin": 1e3, "milyon": 1e6, "mn": 1e6, "milyar": 1e9, "mr": 1e9, "mlr": 1e9, "million": 1e6, "billion": 1e9}
_NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
_MUL = r"(?:\s*(bin|milyon|milyar|mn|mlr|mr|million|billion)\b)?"
_CUR = r"(TL|TRY|₺|USD|\$|EUR|€|ABD Doları|Amerikan Doları|Türk Lirası|Dolar|Avro|Euro)"
_SEP = r"\s*[-‑–]?\s*"
AMOUNT = [re.compile(_NUM + _MUL + _SEP + _CUR, re.I),             # 12,5 milyon USD · 10.200.000-ABD Doları
          re.compile(_CUR + r"\s*" + _NUM + _MUL, re.I)]           # USD 12.500.000
# KAP ihale formu alanları: ortaklık payı ve şirketin kendi hesapladığı ciroya oran
SHARE_FIELD = re.compile(r"Share of Company in Tender Value[\s|]*([^|]+?)\s*\|", re.I)
RATIO_FIELD = re.compile(r"Gross Sales Revenue On Publicly Disclosed The Latest Financial Statement Of Company \(%\)[\s|]*([\d.,]+)\s*\|", re.I)


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def amounts(text: str) -> list[tuple[float, str]]:
    """Metindeki para tutarları: [(değer, para birimi)]. Yüzdeler ve yıllar dışarıda kalır."""
    out = []
    for i, rx in enumerate(AMOUNT):
        for m in rx.finditer(text):
            if i == 0:
                num, mul, cur = m.group(1), m.group(2), m.group(3)
            else:
                cur, num, mul = m.group(1), m.group(2), m.group(3)
            try:
                v = _num(num) * MULT.get((mul or "").lower(), 1)
            except ValueError:
                continue
            c = CUR.get(_low(cur).strip())
            if c and v >= 1000:                     # "1 TL nominal" gibi pay değerlerini atla
                out.append((v, c))
    return out


def fx_rates(macro: dict | None) -> dict:
    rates = {"TRY": 1.0}
    for s in (macro or {}).get("series") or []:
        if s.get("code") in ("TP.DK.USD.A.YTL", "TP.DK.EUR.A.YTL") and s.get("history"):
            rates["USD" if "USD" in s["code"] else "EUR"] = float(s["history"][-1][1])
    return rates


def ttm_revenue(code: str) -> float | None:
    try:
        doc = json.loads((DATA / "fin" / f"{code}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    rev = ((doc.get("series") or {}).get("ttm") or {}).get("revenue") or []
    vals = [v for v in rev if v]
    return vals[-1] if vals else None


def size(text: str, rates: dict, revenue: float | None) -> dict | None:
    """En büyük tutar (ihalede ortaklık payı varsa o); şirket ciroya oranı kendisi bildirdiyse o kullanılır."""
    share = SHARE_FIELD.search(text)
    pool = amounts(share.group(1)) if share and share.group(1).strip() not in ("-", "") else []
    found = [(v * rates[c], v, c) for v, c in (pool or amounts(text)) if c in rates]
    if not found:
        return None
    tl, v, c = max(found)
    out = {"amount": v, "cur": c, "tl": round(tl)}
    if revenue and revenue > 0:
        out["rev"] = round(revenue)
        out["ratio"] = round(tl / revenue, 4)
    rf = RATIO_FIELD.search(text)
    if rf:
        try:
            out["ratio"], out["src"] = round(float(rf.group(1).replace(".", "").replace(",", ".")) / 100, 4), "KAP"
        except ValueError:
            pass
    return out


def materiality(ratio: float | None, current: str | None) -> str | None:
    """Ciroya orana göre önem: ≥%10 yüksek, ≥%3 en az orta, <%1 düşük."""
    if ratio is None:
        return current
    if ratio >= 0.10:
        return "high"
    if ratio >= 0.03:
        return "high" if current == "high" else "medium"
    if ratio < 0.01:
        return "low"
    return current


def attach(items: list[Item], watch: set[str], macro: dict | None, limit: int = 6) -> int:
    """Sözleşme bildirimlerine `extra['deal']` ekler (AI değerlendirmesinden önce). Döner: işlenen sayı."""
    rates = fx_rates(macro)
    n = 0
    for it in items:
        if n >= limit:
            break
        if it.source != "KAP" or not (set(it.tickers) & watch) or "deal" in it.extra:
            continue
        subj = f"{it.extra.get('subject') or ''} {it.summary}"
        if not SUBJECT.search(subj) or NOT_DEAL.search(subj):
            continue
        r = http.get(it.url, timeout=45, retries=1)
        if r is None:
            continue
        n += 1
        code = next(t for t in it.tickers if t in watch)
        d = size(kap_body(r.text, it.extra.get("filer")), rates, ttm_revenue(code))
        if d:
            it.extra["deal"] = d
            log.info("%s sözleşme: %s %s (ciroya oran %s)", code, d["amount"], d["cur"], d.get("ratio"))
    return n


def adjust(it: Item) -> None:
    """AI değerlendirmesi sonrası önemi ciroya orana göre düzelt."""
    d = it.extra.get("deal")
    if d and it.analysis:
        it.analysis["materiality"] = materiality(d.get("ratio"), it.analysis.get("materiality"))
