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
        title = f"{', '.join(codes) or row.get('kapTitle', '')}: {subject}"
        if row.get("modifyStatus"):
            title += " (düzeltme)"
        items.append(Item(
            source="KAP", source_type="disclosure", market="BIST",
            title=title, summary=summary,
            url=DETAIL_URL.format(idx=idx) if idx else "https://www.kap.org.tr",
            published=iso(published), tickers=tickers or codes[:3], lang="tr",
            extra={"subject": subject, "filer": row.get("kapTitle"),
                   "class": row.get("disclosureClass"), "index": idx, "watch": bool(tickers)},
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
