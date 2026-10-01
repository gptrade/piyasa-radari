"""Sinyal arşivi ve karnesi.

Her turda yönlü (olumlu/olumsuz) sinyaller arşive yazılır; yayın anındaki hisse ve endeks fiyatı saklanır.
Sonraki turlarda sinyal, yayından sonraki 1. ve 5. tam seans kapanışında notlanır:
  getiri = kapanış / yayın anı fiyatı − 1, fazla getiri = getiri − aynı aralıkta endeks getirisi,
  isabet = sinyal yönü ile fazla getirinin işareti aynı.
Karne (scorecard.json) piyasa × dönem × ufuk × boyut (kaynak türü, olay, güven, önem, hisse, kaynak, değerlendiren)
kırılımında isabet oranı ve ortalama fazla getiriyi verir.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import prices
from .config import DATA
from .models import iso, now_utc, parse_iso

log = logging.getLogger("radar.scorecard")

ARCHIVE = DATA / "signals.json"
SCORE = DATA / "scorecard.json"
KEEP_DAYS = 180
HORIZONS = (1, 5)
WINDOWS = {"30": 30, "90": 90, "all": None}
EX_TZ = {"BIST": ZoneInfo("Europe/Istanbul"), "US": ZoneInfo("America/New_York")}
SENT = {"bullish": 1, "bearish": -1}
MIN_OUTLET = 5          # bundan az sinyali olan kaynaklar "Diğer" altında toplanır


def kind(d: dict) -> str:
    st = d.get("source_type")
    if st == "disclosure":
        return "Resmi bildirim (KAP/SEC)"
    if st == "regulator":
        return "Düzenleyici (SPK/TCMB)"
    if (d.get("extra") or {}).get("anomaly"):
        return "Habersiz hareket"
    if (d.get("extra") or {}).get("short_flow"):
        return "Açığa satış (BIST)"
    if st == "technical":
        return "Teknik olay"
    if st == "report":
        return "Aracı kurum raporu"
    if st == "social":
        return "Sosyal medya"
    if (d.get("extra") or {}).get("analyst"):
        return "Analist notu (Yahoo)"
    return {1: "Haber ① birincil", 2: "Haber ② finans medyası"}.get(d.get("tier"), "Haber ③ diğer")


def conf_bucket(c) -> str:
    c = c or 0
    return "%85+" if c >= 85 else "%70–84" if c >= 70 else "%50–69" if c >= 50 else "<%50"


def price_at(published: str, p: dict | None, tz) -> float | None:
    """Yayın anında bilinen son fiyat (ileriye bakmadan): gün içi barlar kapsıyorsa yayından önceki son bar,
    yoksa yayın gününden ÖNCEKİ son günlük kapanış (günlük bar o günün kapanışını taşıdığı için)."""
    if not p:
        return None
    ts = int(parse_iso(published).timestamp())
    bars = p.get("intraday") or []
    if bars and bars[0][0] <= ts:
        prev = [b for b in bars if b[0] <= ts]
        return prev[-1][1] if prev else None
    day = datetime.fromtimestamp(ts, tz).date()
    prev = [b for b in p.get("daily") or [] if datetime.fromtimestamp(b[0], tz).date() < day]
    return prev[-1][1] if prev else None


def record(d: dict, px: dict, watch: set[str]) -> dict | None:
    """Akış kaydından arşiv kaydı (yönsüz, hissesiz ya da fiyatsız kayıtlar için None)."""
    a = d.get("analysis") or {}
    k = SENT.get(a.get("sentiment"))
    t = next((x for x in d.get("tickers") or [] if x in watch), None)
    if not k or not t or not px.get(t):
        return None
    p = px[t]
    m = p.get("market") or d.get("market") or "US"
    tz = EX_TZ.get(m, EX_TZ["US"])
    p0 = price_at(d["published"], p, tz)
    if not p0:
        return None
    idx = px.get(prices.INDEXES[m].symbol) if m in prices.INDEXES else None
    label = (a.get("event_label") or d.get("event") or "").lower()
    return {
        "id": d["id"], "k": f"{t}|{label}|{k}",                    # aynı hisse+olay+yön 12 saat içinde bir kez sayılır
        "t": t, "m": m, "ts": d["published"], "title": (a.get("headline_tr") or d.get("title") or "")[:140],
        "src": (d.get("source") or "").split(" · ")[0], "kind": kind(d), "ev": d.get("event") or "news",
        "d": k, "c": a.get("confidence"), "mat": a.get("materiality") or "low",
        "pv": "kural" if str(a.get("provider", "")).startswith("kural") else "AI",
        "p0": p0, "i0": price_at(d["published"], idx, tz),
    }


MX_MIN = 0.2          # Marketaux skoru bu mutlak değerin altındaysa yönsüz sayılır


def mx_records(d: dict, px: dict, watch: set[str]) -> list[dict]:
    """Marketaux'nun kendi duygu skorundan ikinci değerlendirici kaydı (karnede 'Değerlendiren: Marketaux')."""
    out = []
    for t, score in ((d.get("extra") or {}).get("mx") or {}).items():
        if t not in watch or not px.get(t) or abs(score) < MX_MIN:
            continue
        p = px[t]
        m = p.get("market") or d.get("market") or "US"
        tz = EX_TZ.get(m, EX_TZ["US"])
        p0 = price_at(d["published"], p, tz)
        if not p0:
            continue
        idx = px.get(prices.INDEXES[m].symbol) if m in prices.INDEXES else None
        k = 1 if score > 0 else -1
        out.append({"id": f"{d['id']}|mx|{t}", "k": f"mx|{t}|{k}", "t": t, "m": m, "ts": d["published"],
                    "title": (d.get("title") or "")[:140], "src": (d.get("source") or "").split(" · ")[0],
                    "kind": kind(d), "ev": d.get("event") or "news", "d": k, "c": round(abs(score) * 100),
                    "mat": "low", "pv": "Marketaux", "p0": p0, "i0": price_at(d["published"], idx, tz)})
    return out


def _close_after(daily: list, pub_date, k: int, tz, today):
    """Yayın gününden sonraki k. tam seans kapanışı: (tarih, kapanış) ya da None (henüz yok)."""
    seen = 0
    for b in daily:
        day = datetime.fromtimestamp(b[0], tz).date()
        if day <= pub_date:
            continue
        if day >= today:            # bugünün barı henüz kapanmamış olabilir
            return None
        seen += 1
        if seen == k:
            return day, b[1]
    return None


def _close_on(daily: list, day, tz):
    for b in daily:
        if datetime.fromtimestamp(b[0], tz).date() == day:
            return b[1]
    return None


def grade(rec: dict, px: dict) -> bool:
    """Eksik ufukları notlar; değişiklik olduysa True."""
    p = px.get(rec["t"])
    if not p:
        return False
    tz = EX_TZ.get(rec["m"], EX_TZ["US"])
    today = now_utc().astimezone(tz).date()
    pub = parse_iso(rec["ts"]).astimezone(tz).date()
    idx = px.get(prices.INDEXES[rec["m"]].symbol) if rec["m"] in prices.INDEXES else None
    changed = False
    for h in HORIZONS:
        if f"r{h}" in rec:
            continue
        hit = _close_after(p.get("daily") or [], pub, h, tz, today)
        if not hit:
            continue
        day, close = hit
        ret = (close / rec["p0"] - 1) * 100
        rec[f"r{h}"] = round(ret, 2)
        ic = _close_on(idx.get("daily") or [], day, tz) if idx and rec.get("i0") else None
        rec[f"x{h}"] = round(ret - (ic / rec["i0"] - 1) * 100, 2) if ic else rec[f"r{h}"]
        changed = True
    return changed


def _stats(recs: list[dict], h: int) -> dict:
    g = [r for r in recs if f"x{h}" in r]
    n = len(g)
    if not n:
        return {"n": 0}
    hits = sum(1 for r in g if r["d"] * r[f"x{h}"] > 0)
    p = hits / n
    return {"n": n, "hit": round(p * 100, 1), "moe": round(196 * math.sqrt(p * (1 - p) / n), 1),
            "ex": round(sum(r["d"] * r[f"x{h}"] for r in g) / n, 2),
            "raw": round(sum(r["d"] * r[f"r{h}"] for r in g) / n, 2)}


DIMS = {
    "kind": lambda r: r["kind"], "ev": lambda r: r["ev"], "conf": lambda r: conf_bucket(r.get("c")),
    "mat": lambda r: r["mat"], "dir": lambda r: "olumlu" if r["d"] > 0 else "olumsuz",
    "t": lambda r: r["t"], "src": lambda r: r["src"] or "?", "pv": lambda r: r["pv"],
}


def aggregate(recs: list[dict], now: datetime | None = None) -> dict:
    now = now or now_utc()
    outlets = {}
    for r in recs:
        outlets[r["src"]] = outlets.get(r["src"], 0) + 1
    out: dict = {"generated": iso(now), "horizons": list(HORIZONS), "scopes": {}}
    for scope in ("ALL", "BIST", "US"):
        sc = {}
        for wk, days in WINDOWS.items():
            lo = iso(now - timedelta(days=days)) if days else ""
            every = [r for r in recs if (scope == "ALL" or r["m"] == scope) and r["ts"] >= lo]
            rs = [r for r in every if r.get("pv") != "Marketaux"]      # dış skor ana toplamlara karışmaz
            w = {"total": {f"h{h}": _stats(rs, h) for h in HORIZONS},
                 "pending": sum(1 for r in rs if "x1" not in r), "dims": {}}
            for dk, fn in DIMS.items():
                groups: dict[str, list] = {}
                for r in (every if dk == "pv" else rs):
                    key = fn(r)
                    if dk == "src" and outlets.get(key, 0) < MIN_OUTLET:
                        key = "Diğer"
                    groups.setdefault(key, []).append(r)
                w["dims"][dk] = sorted(({"g": key, **{f"h{h}": _stats(g, h) for h in HORIZONS}, "count": len(g)}
                                        for key, g in groups.items()), key=lambda x: -x["count"])
            sc[wk] = w
        out["scopes"][scope] = sc
    graded = sorted((r for r in recs if "x1" in r and r.get("pv") != "Marketaux"), key=lambda r: r["ts"], reverse=True)[:60]
    out["recent"] = [{k: r.get(k) for k in ("id", "t", "m", "ts", "title", "kind", "d", "c", "r1", "x1", "r5", "x5")}
                     for r in graded]
    return out


def load() -> list[dict]:
    try:
        return json.loads(ARCHIVE.read_text(encoding="utf-8")).get("items", [])
    except (FileNotFoundError, ValueError):
        return []


def update(items: list[dict], px: dict, watch: set[str]) -> dict:
    """Arşive yeni sinyalleri ekle, bekleyenleri notla, karneyi yaz."""
    recs = load()
    ids = {r["id"] for r in recs}
    seen: dict[str, list[float]] = {}
    for r in recs:
        seen.setdefault(r["k"], []).append(parse_iso(r["ts"]).timestamp())
    added = 0
    for d in sorted(items, key=lambda x: x.get("published", "")):
        if d["id"] in ids:
            continue
        for r in [record(d, px, watch), *mx_records(d, px, watch)]:
            if not r or r["id"] in ids:
                continue
            ts = parse_iso(r["ts"]).timestamp()
            if any(abs(ts - x) < 12 * 3600 for x in seen.get(r["k"], [])):
                continue
            recs.append(r)
            ids.add(r["id"])
            seen.setdefault(r["k"], []).append(ts)
            added += 1
    graded = sum(grade(r, px) for r in recs if "x5" not in r)
    lo = iso(now_utc() - timedelta(days=KEEP_DAYS))
    recs = sorted((r for r in recs if r["ts"] >= lo), key=lambda r: r["ts"])
    ARCHIVE.write_text(json.dumps({"version": 1, "items": recs}, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    sc = aggregate(recs)
    SCORE.write_text(json.dumps(sc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Karne: %d yeni sinyal, %d notlandı, arşivde %d", added, graded, len(recs))
    return {"added": added, "graded": graded, "total": len(recs)}
