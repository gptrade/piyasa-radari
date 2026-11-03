"""Makro sürpriz: TÜFE gerçekleşmesi − TCMB Piyasa Katılımcıları Anketi beklentisi.

Kaynak (EVDS, resmi API):
  * TP.PKAUO.S01.A.U  Cari ayın aylık TÜFE beklentisi (anket ayın ortasında yayımlanır, o ayın TÜFE'sini sorar)
  * TP.PKAUO.S01.B.U  1 ay sonrasının aylık TÜFE beklentisi (bir sonraki ay için ilk okuma)
  * TP.TUKFIY2025.GENEL  TÜFE (2025=100, 2013'e zincirlenmiş) → aylık % değişim
Sürpriz(ay) = gerçekleşen aylık TÜFE − o ayın anketindeki cari ay beklentisi (yüzde puan).
Pozitif sürpriz = enflasyon beklenenden yüksek.

Piyasa tepkisi: açıklama günü (TÜİK ayın 3'ünde 10:00'da açıklar; hafta sonuna denk gelirse ilk iş günü) BIST 100 ve
BIST Banka endeksinin günlük getirisi (Yahoo; ham fiyat yayımlanmaz, yalnız o günün yüzde değişimi). Açıklama tarihi
kurala göre hesaplandığı için tatil kaymalarında birkaç ay bir gün sapabilir.
Çıktı: site/data/surprise.json (radar turunda; 6 saatte bir, açıklama günlerinde saatte bir yenilenir).
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone

from . import http
from .config import DATA

log = logging.getLogger("radar.surprise")

OUT = DATA / "surprise.json"
EVDS = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
S_EXP, S_EXP1, S_CPI = "TP.PKAUO.S01.A.U", "TP.PKAUO.S01.B.U", "TP.TUKFIY2025.GENEL"
START = date(2013, 1, 1)
AY = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
BAND = 0.25  # |sürpriz| ≥ 0,25 puan: "belirgin"


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _ym(s: str) -> str:
    y, m = s.split("-")[:2]
    return f"{int(y):04d}-{int(m):02d}"


def _next_month(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def release_date(ym: str) -> date:
    """Ayın TÜFE'sinin açıklanma günü: sonraki ayın 3'ü, hafta sonuysa pazartesi."""
    y, m = map(int, _next_month(ym).split("-"))
    d = date(y, m, 3)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{AY[int(m)]} {y}"


def fetch_evds(key: str) -> list[dict]:
    end = datetime.now(timezone.utc)
    url = (f"{EVDS}series={S_EXP}-{S_EXP1}-{S_CPI}&startDate={START:%d-%m-%Y}&endDate={end:%d-%m-%Y}"
           f"&type=json&frequency=5")
    r = http.get(url, headers={"key": key}, timeout=60)
    if r is None:
        return []
    try:
        return r.json().get("items") or []
    except ValueError:
        return []


def series(items: list[dict]) -> tuple[dict, dict, dict]:
    """→ (beklenti, 1 ay sonrası beklenti, aylık TÜFE % değişim) ay → değer."""
    exp, exp1, idx = {}, {}, {}
    for it in items:
        t = it.get("Tarih")
        if not t:
            continue
        ym = _ym(t)
        for d, code in ((exp, S_EXP), (exp1, S_EXP1), (idx, S_CPI)):
            v = _num(it.get(code.replace(".", "_")))
            if v is not None:
                d[ym] = v
    mom = {}
    ks = sorted(idx)
    for a, b in zip(ks, ks[1:]):
        if idx[a] and _next_month(a) == b:
            mom[b] = round((idx[b] / idx[a] - 1) * 100, 2)
    return exp, exp1, mom


def reactions(days: list[date]) -> dict[str, dict[str, float]]:
    """Açıklama günü getirileri (ilk işlem günü ≥ açıklama günü): {'2026-10-03': {'xu': %, 'xb': %}}."""
    if not days:
        return {}
    import yfinance as yf
    df = yf.download("XU100.IS XBANK.IS", start=(min(days) - timedelta(days=10)).isoformat(), interval="1d",
                     group_by="ticker", auto_adjust=False, progress=False, threads=True)
    out: dict[str, dict[str, float]] = {}
    for tk, k in (("XU100.IS", "xu"), ("XBANK.IS", "xb")):
        try:
            s = df[tk]["Close"].dropna()
        except Exception:  # noqa: BLE001
            continue
        r = (s / s.shift(1) - 1) * 100
        r = r[(r.abs() < 25)]                 # 2020 ölçek kırılması gibi uç değerler
        idx = [d.date() for d in r.index]
        for d in days:
            j = next((i for i, x in enumerate(idx) if x >= d), None)
            if j is None or (idx[j] - d).days > 5:
                continue
            out.setdefault(d.isoformat(), {})[k] = round(float(r.iloc[j]), 2)
    return out


def _ols(xs, ys):
    n = len(xs)
    if n < 12:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = [y - a - b * x for x, y in zip(xs, ys)]
    s2 = sum(e * e for e in res) / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else None
    return {"b": round(b, 2), "t": round(b / se, 2) if se else None, "n": n}


def build(exp: dict, exp1: dict, mom: dict, react: dict | None = None, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    react = react or {}
    rows = []
    for ym in sorted(set(exp) & set(mom)):
        rel = release_date(ym)
        rx = react.get(rel.isoformat(), {})
        rows.append({"m": ym, "exp": exp[ym], "act": mom[ym], "sur": round(mom[ym] - exp[ym], 2),
                     "rel": rel.isoformat(), **rx})
    # bekleyen ay(lar): beklentisi olan, gerçekleşmesi gelmemiş en yakın ay; anket henüz yoksa önceki ayın "1 ay sonrası"
    last_act = max(mom) if mom else None
    nxt = _next_month(last_act) if last_act else None
    pending = None
    if nxt:
        e, src = exp.get(nxt), "anket"
        if e is None and last_act in exp1:
            e, src = exp1[last_act], "önceki anket (1 ay sonrası)"
        if e is not None:
            pending = {"m": nxt, "label": label(nxt), "exp": e, "src": src, "rel": release_date(nxt).isoformat()}
    stats = {}
    for win in (12, 36):
        xs = rows[-win:]
        if xs:
            stats[f"w{win}"] = {"n": len(xs), "above": sum(r["sur"] >= BAND for r in xs), "below": sum(r["sur"] <= -BAND for r in xs),
                                "mean": round(sum(r["sur"] for r in xs) / len(xs), 2),
                                "mae": round(sum(abs(r["sur"]) for r in xs) / len(xs), 2)}
    react_stats = {}
    for k in ("xu", "xb"):
        pts = [(r["sur"], r[k]) for r in rows if k in r]
        if not pts:
            continue
        ols = _ols([p[0] for p in pts], [p[1] for p in pts])
        grp = {}
        for g, f in (("hi", lambda s: s >= BAND), ("mid", lambda s: -BAND < s < BAND), ("lo", lambda s: s <= -BAND)):
            v = [y for s, y in pts if f(s)]
            if v:
                grp[g] = {"n": len(v), "mean": round(sum(v) / len(v), 2), "up": round(sum(y > 0 for y in v) / len(v), 2)}
        react_stats[k] = {"ols": ols, "groups": grp, "since": next(r["m"] for r in rows if k in r)}
    roll = []
    for i in range(len(rows)):
        w = rows[max(0, i - 5): i + 1]
        roll.append(round(sum(r["sur"] for r in w), 2))
    for r, v in zip(rows, roll):
        r["c6"] = v
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "band": BAND,
            "rows": rows, "pending": pending, "stats": stats, "react": react_stats,
            "source": "EVDS: TÜFE (TÜİK) ve Piyasa Katılımcıları Anketi (TCMB); tepki: Yahoo, açıklama günü getirisi"}


def due(prev: dict | None, now: datetime) -> bool:
    if not prev or not prev.get("generated"):
        return True
    age = now - datetime.fromisoformat(prev["generated"])
    pend = (prev.get("pending") or {}).get("rel")
    on_release = bool(pend) and pend <= now.date().isoformat()   # açıklama günü geldi ama gerçekleşme henüz yok
    return age > timedelta(hours=1 if on_release else 6)


def update(force: bool = False) -> dict | None:
    key = os.environ.get("EVDS_API_KEY")
    prev = None
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            prev = None
    now = datetime.now(timezone.utc)
    if not key or not (force or due(prev, now)):
        return prev
    items = fetch_evds(key)
    if not items:
        log.warning("Makro sürpriz: EVDS boş döndü")
        return prev
    exp, exp1, mom = series(items)
    days = [release_date(m) for m in sorted(set(exp) & set(mom))]
    try:
        react = reactions(days)
    except Exception as e:  # noqa: BLE001
        log.warning("Makro sürpriz: tepki verisi alınamadı: %s", e)
        react = {r["rel"]: {k: r[k] for k in ("xu", "xb") if k in r} for r in (prev or {}).get("rows", [])}
    doc = build(exp, exp1, mom, react)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Makro sürpriz: %d ay, son %s", len(doc["rows"]), doc["rows"][-1]["m"] if doc["rows"] else "—")
    return doc


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    update(force="--force" in sys.argv)
