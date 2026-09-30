"""TCMB: PPK kararları, basın duyuruları, başkan konuşmaları (RSS) ve EVDS makro serileri."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from .. import http
from ..config import DATA
from ..models import Item, iso, now_utc
from . import Context
from .feeds import entries_to_items, fetch_feed

log = logging.getLogger("radar.tcmb")

RSS_BASE = "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Bottom+Menu/Diger/RSS/"
FEEDS = {
    "PPK Kararları": "PPK+Kararlari",
    "Basın Duyuruları": "Basin+Duyurulari",
    "Başkanın Konuşmaları": "Baskanin+Konusmalari",
}

EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
MACRO_FILE = DATA / "macro.json"


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("tcmb")
    if not cfg.get("enabled", True):
        return []
    out = []
    for name in cfg.get("feeds") or list(FEEDS):
        path = FEEDS.get(name)
        if not path:
            continue
        items = entries_to_items(fetch_feed(RSS_BASE + path), source=f"TCMB · {name}",
                                 source_type="macro", market="BIST", since=ctx.since, lang="tr",
                                 allow_empty=True, extra={"tcmb": name})
        if name == "PPK Kararları":
            for it in items:
                it.extra["high_impact"] = True
        out += items
    log.info("TCMB: %d duyuru", len(out))
    return out


# ------------------------------------------------------------------ EVDS
def evds_url(codes: list[str], start: datetime, end: datetime) -> str:
    """EVDS3 parametreleri query string değil, yol olarak ister (`?` kabul etmez)."""
    return (f"{EVDS_URL}series={'-'.join(codes)}&startDate={start:%d-%m-%Y}"
            f"&endDate={end:%d-%m-%Y}&type=json")


def _num(v) -> float | None:
    if v in (None, "", "null"):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def parse_evds(payload: dict, series: list[dict]) -> list[dict]:
    rows = payload.get("items") or []
    out = []
    for s in series:
        key = s["code"].replace(".", "_")
        pts = [(r.get("Tarih"), _num(r.get(key))) for r in rows]
        pts = [(d, v) for d, v in pts if v is not None]
        if not pts:
            continue
        (d1, v1) = pts[-1]
        v0 = pts[-2][1] if len(pts) >= 2 else None
        out.append({
            "code": s["code"], "name": s.get("name", s["code"]), "unit": s.get("unit", ""),
            "date": d1, "last": v1, "prev": v0,
            "change": round(v1 - v0, 4) if v0 is not None else None,
            "change_pct": round((v1 / v0 - 1) * 100, 2) if v0 else None,
            "history": [[d, v] for d, v in pts[-60:]],
        })
    return out


def update_macro(settings: dict) -> dict | None:
    cfg = (settings.get("sources") or {}).get("evds") or {}
    key = os.environ.get("EVDS_API_KEY")
    if MACRO_FILE.exists() and json.loads(MACRO_FILE.read_text() or "{}").get("demo"):
        MACRO_FILE.unlink()                      # örnek veri gerçek panelde kalmasın
    if not cfg.get("enabled", True) or not key:
        return None
    series = cfg.get("series") or []
    if not series:
        return None
    end = now_utc()
    start = end - timedelta(days=int(cfg.get("lookback_days", 400)))
    r = http.get(evds_url([s["code"] for s in series], start, end), headers={"key": key})
    data = None
    if r is not None:
        try:
            data = {"updated": iso(end), "series": parse_evds(r.json(), series)}
        except ValueError:
            log.warning("EVDS JSON dönmedi (anahtar ya da seri kodu hatalı olabilir)")
    if data is None and MACRO_FILE.exists():
        return json.loads(MACRO_FILE.read_text())
    if data:
        MACRO_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        log.info("EVDS: %d seri", len(data["series"]))
    return data


def macro_context(macro: dict | None) -> str:
    if not macro:
        return ""
    return "; ".join(f"{s['name']}: {s['last']}{s['unit']} ({s['date']}, önceki {s['prev']})"
                     for s in macro.get("series", []))
