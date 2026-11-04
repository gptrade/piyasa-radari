"""ABD ısı haritası verisi: S&P 500 hisselerinin piyasa değeri ve getirileri (1G, 1H, 1A, YBB).

* Fiyat: Yahoo (yfinance), tek toplu günlük indirme (1 yıl). Ham fiyat yayımlanmaz; yalnız yüzde getiriler ve
  piyasa değeri (dolaşımdaki pay × son fiyat) yazılır.
* Pay sayısı: Yahoo fast_info.shares; data/us_shares.json önbelleğinde, her turda en eski 120 hisse yenilenir (7 gün).
* Sıklık: ABD seansında (13:30–20:15 UTC, hafta içi) 30 dakikada bir, diğer saatlerde günde bir (son seans gelmediyse).
Bileşenler: config/sp500.csv (sembol, ad, GICS sektörü).
Çıktı: site/data/us_map.json.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import DATA, ROOT

log = logging.getLogger("radar.usmap")

OUT = DATA / "us_map.json"
SHARES = DATA / "us_shares.json"
SP500 = ROOT / "config" / "sp500.csv"
SHARE_TTL = timedelta(days=7)
SHARE_BATCH = 120
SESSION = (13 * 60 + 30, 20 * 60 + 15)   # UTC dakika (yaz saatinde de geniş kalır)


def members() -> list[dict]:
    rows = []
    with SP500.open(encoding="utf-8") as f:
        for r in csv.DictReader(line for line in f if not line.startswith("#")):
            s = (r.get("symbol") or "").strip()
            if s:
                rows.append({"code": s, "yf": s.replace(".", "-"), "name": (r.get("name") or "").strip(), "sector": (r.get("sector") or "").strip()})
    return rows


def due(prev: dict | None, now: datetime) -> bool:
    if not prev or not prev.get("generated"):
        return True
    age = now - datetime.fromisoformat(prev["generated"])
    m = now.hour * 60 + now.minute
    if now.weekday() < 5 and SESSION[0] <= m <= SESSION[1]:
        return age >= timedelta(minutes=30)
    return age >= timedelta(hours=20) or (now.weekday() < 5 and m > SESSION[1] and
                                         datetime.fromisoformat(prev["generated"]).date() < now.date())


def _load(p) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def refresh_shares(ms: list[dict], now: datetime, batch: int = SHARE_BATCH) -> dict:
    cache = _load(SHARES)
    sh = cache.get("shares", {})
    stale = [m for m in ms if not sh.get(m["code"]) or now - datetime.fromisoformat(sh[m["code"]]["at"]) > SHARE_TTL]
    stale.sort(key=lambda m: sh.get(m["code"], {}).get("at", ""))
    if len(sh) < 0.5 * len(ms):                   # ilk doldurma: hepsini bir seferde
        batch = len(ms)
    todo = stale[:batch]
    if todo:
        import yfinance as yf

        def one(m):
            try:
                n = yf.Ticker(m["yf"]).fast_info.get("shares")
                return m["code"], float(n) if n and n > 0 else None
            except Exception:  # noqa: BLE001
                return m["code"], None
        with ThreadPoolExecutor(8) as ex:
            for code, n in ex.map(one, todo):
                if n:
                    sh[code] = {"n": n, "at": now.isoformat(timespec="seconds")}
        SHARES.write_text(json.dumps({"shares": sh}, separators=(",", ":")), encoding="utf-8")
        log.info("ABD pay sayısı: %d yenilendi, %d eksik", len(todo), sum(1 for m in ms if m["code"] not in sh))
    return sh


def prices(ms: list[dict]) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(" ".join(m["yf"] for m in ms), period="1y", interval="1d", group_by="ticker",
                     auto_adjust=True, threads=True, progress=False)
    out = {}
    for m in ms:
        try:
            s = df[m["yf"]]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if len(s) > 1:
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            out[m["code"]] = s[~s.index.duplicated(keep="last")]
    return pd.DataFrame(out).sort_index()


def _r(v, k=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, k) if math.isfinite(f) else None


def build(px: pd.DataFrame, ms: list[dict], shares: dict) -> dict:
    px = px.dropna(how="all")
    asof = px.index[-1]
    prev_year = px[px.index.year < asof.year]
    rows = []
    for m in ms:
        if m["code"] not in px:
            continue
        s = px[m["code"]].dropna()
        if len(s) < 2:
            continue
        last = float(s.iloc[-1])

        def back(n):
            return float(s.iloc[-1 - n]) if len(s) > n else None
        ye = prev_year[m["code"]].dropna() if m["code"] in prev_year else None
        y0 = float(ye.iloc[-1]) if ye is not None and len(ye) else None
        n = (shares.get(m["code"]) or {}).get("n")
        rows.append({"code": m["code"], "name": m["name"], "sector": m["sector"],
                     "mcap": _r(n * last, 0) if n else None,
                     "d1": _r(last / back(1) - 1) if back(1) else None, "w1": _r(last / back(5) - 1) if back(5) else None,
                     "r1a": _r(last / back(21) - 1) if back(21) else None, "ytd": _r(last / y0 - 1) if y0 else None,
                     "stale": s.index[-1] < asof or None})
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "asof": asof.date().isoformat(),
            "n": len(rows), "with_mcap": sum(1 for r in rows if r["mcap"]), "stocks": rows,
            "source": "Yahoo (kişisel kullanım; yalnız yüzde getiri ve piyasa değeri)"}


def update(force: bool = False) -> dict | None:
    now = datetime.now(timezone.utc)
    prev = _load(OUT) or None
    if not force and not due(prev, now):
        return prev
    ms = members()
    sh = refresh_shares(ms, now)
    try:
        px = prices(ms)
    except Exception as e:  # noqa: BLE001
        log.warning("ABD fiyatları alınamadı: %s", e)
        return prev
    if px.empty:
        return prev
    doc = build(px, ms, sh)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("ABD ısı haritası: %d hisse (%d piyasa değerli), %s", doc["n"], doc["with_mcap"], doc["asof"])
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    update(force="--force" in sys.argv)
