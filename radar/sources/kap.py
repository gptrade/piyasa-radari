"""KAP (Kamuyu Aydınlatma Platformu) bildirimleri."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import http
from ..models import Item, iso
from . import Context

log = logging.getLogger("radar.kap")

IST = ZoneInfo("Europe/Istanbul")
LIST_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
DETAIL_URL = "https://www.kap.org.tr/tr/Bildirim/{idx}"


def parse_kap_date(s: str) -> datetime:
    """'27.09.2026 18:42:10' (İstanbul saati) -> aware datetime."""
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValueError(f"KAP tarihi çözülemedi: {s!r}")


def _codes(row: dict) -> list[str]:
    raw = row.get("relatedStocks") or row.get("stockCodes") or ""
    return [c.strip().upper() for c in str(raw).replace(";", ",").split(",") if c.strip()]


# Borsa İstanbul'un KAP'ta yayımladığı pay bazlı tedbir/duyuru türleri (anahtar kelime → etiket).
# Sıra önemli: daha özel ifade önce.
BIST_MEASURES = [
    ("kaldırıl", "Tedbir kaldırıldı"),
    ("sona er", "Tedbir kaldırıldı"),
    ("brüt takas", "Brüt takas"),
    ("tek fiyat", "Tek fiyat yöntemi"),
    ("emir paketi", "Emir paketi tedbiri"),
    ("kredili işlem", "Kredili işlem yasağı"),
    ("açığa satış", "Açığa satış yasağı"),
    ("internet", "İnternet/mobil emir yasağı"),
    ("işlem yasağı", "İşlem yasağı"),
    ("devre kesici", "Devre kesici"),
    ("işlem sırası durdur", "İşlem sırası durduruldu"),
    ("işlem sırası kapat", "İşlem sırası durduruldu"),
    ("işleme açıl", "İşleme açıldı"),
    ("pazar", "Pazar değişikliği"),
    ("endeks", "Endeks değişikliği"),
    ("fiyat adımı", "Fiyat adımı/marj"),
]


def is_bist_row(row: dict) -> bool:
    return "BORSA İSTANBUL" in (row.get("kapTitle") or "").upper() or \
        "BORSA İSTANBUL" in (row.get("subject") or "").upper()


def bist_measure(text: str) -> str:
    t = text.replace("İ", "i").replace("I", "ı").lower()
    for key, label in BIST_MEASURES:
        if key in t:
            return label
    return "Borsa İstanbul duyurusu"


def parse_rows(rows: list[dict], watch: set[str], scope: str) -> list[Item]:
    items: list[Item] = []
    for row in rows:
        try:
            published = parse_kap_date(row["publishDate"])
        except (KeyError, ValueError):
            continue
        codes = _codes(row)
        tickers = [c for c in codes if c in watch]
        if scope != "all" and not tickers:
            continue
        idx = row.get("disclosureIndex")
        subject = row.get("subject") or "Bildirim"
        summary = row.get("summary") or row.get("kapTitle") or ""
        extra = {"subject": subject, "filer": row.get("kapTitle"),
                 "class": row.get("disclosureClass"), "index": idx, "watch": bool(tickers),
                 "att": int(row.get("attachmentCount") or 0)}
        source = "KAP"
        if is_bist_row(row):
            measure = bist_measure(f"{summary} {subject}")
            extra["bist_measure"] = measure
            source = "Borsa İstanbul · KAP"
            title = f"{', '.join(codes) or 'Pay Piyasası'}: {measure}"
        else:
            title = f"{', '.join(codes) or row.get('kapTitle', '')}: {subject}"
        if row.get("modifyStatus"):
            title += " (düzeltme)"
        items.append(Item(
            source=source, source_type="disclosure", market="BIST",
            title=title, summary=summary,
            url=DETAIL_URL.format(idx=idx) if idx else "https://www.kap.org.tr",
            published=iso(published), tickers=tickers or codes[:3], lang="tr", extra=extra,
        ))
    return items


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("kap")
    if not cfg.get("enabled", True):
        return []
    today = datetime.now(IST).date()
    frm = max(ctx.since.astimezone(IST).date(), today - timedelta(days=7))
    r = http.post(LIST_URL, json={
        "fromDate": frm.isoformat(), "toDate": today.isoformat(),
        "mkkMemberOidList": [], "subjectList": [],
    }, headers={"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu",
                "Accept": "application/json", "Content-Type": "application/json"})
    if r is None:
        return []
    try:
        rows = r.json()
    except ValueError:
        log.warning("KAP JSON dönmedi")
        return []
    watch = {s.symbol for s in ctx.market("BIST")}
    items = [i for i in parse_rows(rows, watch, cfg.get("scope", "watchlist"))
             if i.published >= iso(ctx.since)]
    log.info("KAP: %d bildirim", len(items))
    return items
