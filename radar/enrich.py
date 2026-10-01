"""Kayıt zenginleştirme: olay türü, kaynak kalitesi (①②③) ve gürültü ölçütleri."""
from __future__ import annotations

import re

# Olay türleri: panelde simge + kısa ad
EVENTS = {
    "measure": "Borsa tedbiri",
    "buyback": "Geri alım",
    "insider": "İçeriden işlem",
    "earnings": "Finansal sonuç",
    "analyst": "Analist",
    "dividend": "Temettü / sermaye",
    "deal": "Anlaşma / ihale",
    "regulator": "Düzenleyici",
    "macro": "Makro",
    "legal": "Hukuki",
    "news": "Haber",
    "social": "Sosyal",
    "report": "Rapor",
}

_RULES = [
    ("buyback", r"geri al[ıi]m|repurchase|buyback|payların geri alınması"),
    ("insider", r"pay al[ıi]m sat[ıi]m bildirimi|form 4\b|insider|içeriden"),
    ("earnings", r"finansal rapor|bilanço|kâr|kar açıkla|10-q|10-k|earnings|quarterly results|revenue|gelir tablosu|faaliyet raporu"),
    ("analyst", r"hedef fiyat|tavsiye|upgrade|downgrade|price target|analist|analyst|rating|model portföy|\bal tavsiyesi|outperform|overweight"),
    ("dividend", r"temettü|kâr payı|kar payı|dividend|bedelsiz|bedelli|sermaye artırımı|stock split"),
    ("deal", r"yeni iş ilişkisi|sözleşme|ihale|anlaşma|agreement|contract|partnership|acquisition|satın al|merger|birleşme"),
    ("legal", r"dava|ceza|soruşturma|lawsuit|class action|probe|sec charges|idari para"),
]

# ① birincil / resmi kaynak, ② yerleşik finans medyası, ③ diğer / sosyal
TIER1_SOURCES = ("KAP", "Borsa İstanbul", "SEC EDGAR", "SPK", "TCMB", "PR Newswire", "GlobeNewswire",
                 "Rapor kutusu", "Kazanç takvimi")
TIER2_OUTLETS = ("reuters", "bloomberg", "financial times", "ft.com", "wall street journal", "wsj",
                 "cnbc", "yahoo finance", "marketwatch", "barron", "seeking alpha", "investing.com",
                 "associated press", "ap news", "anadolu", "aa ", "aa ekonomi", "dünya", "ekonomim",
                 "para analiz", "bloomberght", "bloomberg ht", "forbes", "the economist", "nikkei",
                 "morningstar", "zacks", "benzinga", "motley fool", "tipranks", "barchart", "investing")


def source_tier(item: dict) -> int:
    src = (item.get("source") or "")
    if item.get("source_type") in ("disclosure", "regulator", "macro", "report", "technical") or src.startswith(TIER1_SOURCES):
        return 1
    if item.get("extra", {}).get("press_release"):
        return 1
    if item.get("source_type") == "social":
        return 3
    low = src.lower()
    return 2 if any(o in low for o in TIER2_OUTLETS) else 3


def classify_event(item: dict) -> str:
    extra = item.get("extra") or {}
    if extra.get("bist_measure"):
        return "measure"
    st = item.get("source_type")
    if st == "technical":
        return "technical"
    if st == "macro":
        return "macro"
    if st == "report":
        return "report"
    a = item.get("analysis") or {}
    text = " ".join([item.get("title", ""), extra.get("subject") or "", extra.get("form") or "",
                     a.get("category", ""), a.get("event_label", "")]).lower()
    if extra.get("earnings_date"):
        return "earnings"
    if (extra.get("form") or "") == "4":
        return "insider"
    for key, rx in _RULES:
        if re.search(rx, text):
            return key
    if st == "regulator":
        return "regulator"
    if st == "social":
        return "social"
    return "news"


def enrich(item: dict) -> dict:
    item["tier"] = source_tier(item)
    item["event"] = classify_event(item)
    return item
