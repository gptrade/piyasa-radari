"""Geri alım sonrası performans: olay çalışması (BIST 100'e göre fazla getiri).

Olay: bir şirketin "geri alım dalgası"nın ilk işlem bildirimi. Aynı hissede 30 günden uzun ara verilmeden gelen
işlem bildirimleri tek dalga sayılır (aksi halde her gün alım yapan şirketler sonucu domine eder).
Giriş (yayın anına göre, ileriye bakmadan): bildirim 09:55'ten önce yayımlandıysa o günün kapanışı, sonra yayımlandıysa
bir sonraki işlem gününün kapanışı. Fazla getiri = hisse getirisi − XU100 getirisi (aynı pencere, düzeltilmiş fiyat).
Ufuklar: 5, 20, 60 işlem günü. Öncesi: girişten önceki 20 işlem günü (şirketler genelde düşüşten sonra alır).
Anlamlılık: olaylar takvimde kümelendiği için olaylar giriş ayına göre ortalanır, aylık ortalamalar üzerinden t.
Veri: KAP geri alım bildirimleri (gptrade/kap-geri-alim-takibi), fiyat guc/px.parquet (Yahoo; ham fiyat yayımlanmaz,
yalnız olay pencerelerinin yüzde getirileri).
Çıktı: site/data/guc/bb.json (guc.yml, piyasa gücüyle birlikte).
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, time, timezone

import numpy as np
import pandas as pd

from . import http
from .guc import BENCH, OUT, PX, clean_index, clean_prices, wide

log = logging.getLogger("radar.bbstudy")

SRC = "https://raw.githubusercontent.com/gptrade/kap-geri-alim-takibi/main/site/kap-buybacks.json"
GAP_DAYS = 30
H = (5, 20, 60)
PRE = 20
PATH = (-20, 60)
OPEN_CUT = time(9, 55)
DROP = -0.10   # öncesinde endekse göre ≥ %10 geride kalan dalgalar ayrıca


def _pub(s: str) -> datetime | None:
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y %H:%M:%S")
    except (AttributeError, ValueError):
        return None


def episodes(raw: list[dict]) -> list[dict]:
    """İşlem bildirimlerini hisse bazında dalgalara ayır."""
    tx = []
    for r in raw:
        if not r.get("quantity"):
            continue
        t = (r.get("tickers") or "").replace(",", " ").split()
        p = _pub(r.get("publish_date") or "")
        if t and p:
            tx.append((t[0].upper(), p, r.get("pct_this_transaction"), (r.get("price") or 0) * (r.get("quantity") or 0)))
    tx.sort(key=lambda x: (x[0], x[1]))
    out, cur = [], None
    for t, p, pct, amt in tx:
        if cur and cur["t"] == t and (p - cur["last"]).days <= GAP_DAYS:
            cur["last"] = p
            cur["n"] += 1
            cur["pct"] += pct or 0
            cur["amt"] += amt or 0
            continue
        cur = {"t": t, "pub": p, "last": p, "n": 1, "pct": pct or 0, "amt": amt or 0}
        out.append(cur)
    return out


def entry_index(dates: pd.DatetimeIndex, pub: datetime) -> int | None:
    d = pd.Timestamp(pub.date())
    i = int(dates.searchsorted(d))
    if i >= len(dates):
        return None
    if dates[i] == d and pub.time() >= OPEN_CUT:
        i += 1
    return i if i < len(dates) else None


def _t(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 6:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m / (sd / math.sqrt(n)), 2) if sd else None


def summarize(evs: list[dict], key: str) -> dict | None:
    xs = [e for e in evs if e.get(key) is not None]
    if len(xs) < 8:
        return None
    v = np.array([e[key] for e in xs])
    by = {}
    for e in xs:
        by.setdefault(e["entry"][:7], []).append(e[key])
    months = [float(np.mean(a)) for a in by.values()]
    return {"n": len(xs), "mean": round(float(v.mean()) * 100, 2), "med": round(float(np.median(v)) * 100, 2),
            "hit": round(float((v > 0).mean()), 2), "t": _t(months), "months": len(months)}


def study(clean: pd.DataFrame, bench: pd.Series, eps: list[dict], today: pd.Timestamp | None = None) -> dict:
    dates = clean.index
    b = bench.reindex(dates).ffill()
    today = today or dates[-1]
    evs, paths = [], []
    for e in eps:
        if e["t"] not in clean.columns:
            continue
        s = clean[e["t"]]
        i = entry_index(dates, e["pub"])
        if i is None or pd.isna(s.iloc[i]):
            continue
        p0, b0 = s.iloc[i], b.iloc[i]
        row = {"t": e["t"], "pub": e["pub"].strftime("%Y-%m-%d %H:%M"), "entry": dates[i].date().isoformat(), "n": e["n"],
               "pct": round(e["pct"], 3) if e["pct"] else None, "amt": round(e["amt"] / 1e6, 2)}
        for h in H:
            j = i + h
            if j < len(dates) and pd.notna(s.iloc[j]):
                row[f"a{h}"] = round(float(s.iloc[j] / p0 - b.iloc[j] / b0), 4)
        if i - PRE >= 0 and pd.notna(s.iloc[i - PRE]):
            row["pre"] = round(float(p0 / s.iloc[i - PRE] - b0 / b.iloc[i - PRE]), 4)
        last = s.iloc[i:].last_valid_index()
        if last is not None:
            row["since"] = round(float(s.loc[last] / p0 - b.loc[last] / b0), 4)
            row["days"] = int(dates.get_loc(last) - i)
        evs.append(row)
        lo, hi = i + PATH[0], i + PATH[1]
        if lo >= 0 and hi < len(dates):
            w = s.iloc[lo: hi + 1].values / p0 - b.iloc[lo: hi + 1].values / b0
            if np.isfinite(w).all():
                paths.append(w)
    path = None
    if len(paths) >= 8:
        a = np.vstack(paths)
        m, se = a.mean(axis=0), a.std(axis=0, ddof=1) / math.sqrt(len(a))
        path = {"from": PATH[0], "n": len(a), "mean": [round(float(x) * 100, 2) for x in m],
                "lo": [round(float(x) * 100, 2) for x in m - 1.96 * se], "hi": [round(float(x) * 100, 2) for x in m + 1.96 * se]}
    res = {f"a{h}": summarize(evs, f"a{h}") for h in H}
    res["pre"] = summarize(evs, "pre")
    drop = [e for e in evs if e.get("pre") is not None and e["pre"] <= DROP]
    rest = [e for e in evs if e.get("pre") is not None and e["pre"] > DROP]
    split = {"drop": {f"a{h}": summarize(drop, f"a{h}") for h in H}, "rest": {f"a{h}": summarize(rest, f"a{h}") for h in H},
             "n_drop": len(drop), "n_rest": len(rest)}
    recent = sorted([e for e in evs if e["entry"] >= (today - pd.Timedelta(days=120)).date().isoformat()], key=lambda e: e["entry"], reverse=True)
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "asof": dates[-1].date().isoformat(),
            "first": min((e["entry"] for e in evs), default=None), "n_events": len(evs), "gap_days": GAP_DAYS, "drop": DROP,
            "res": res, "split": split, "path": path,
            "recent": [{k: e.get(k) for k in ("t", "entry", "n", "pct", "amt", "pre", "since", "days", "a5", "a20")} for e in recent[:40]]}


def run() -> dict | None:
    if not PX.exists():
        log.warning("px.parquet yok")
        return None
    r = http.get(SRC, timeout=60)
    try:
        raw = r.json() if r is not None else None
    except ValueError:
        raw = None
    if not isinstance(raw, list):
        log.warning("Geri alım verisi alınamadı")
        return None
    px = pd.read_parquet(PX)
    adj = wide(px, "adj")
    if BENCH not in adj:
        return None
    bench = clean_index(adj[BENCH])
    stocks = adj.drop(columns=[c for c in (BENCH, "USDTRY") if c in adj])
    cnt = stocks.notna().sum(axis=1)
    stocks = stocks[cnt >= 0.5 * cnt.rolling(20, min_periods=1).median()]
    clean, _ = clean_prices(stocks.loc["2024-06-01":])
    doc = study(clean, bench, episodes(raw))
    (OUT / "bb.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Geri alım olay çalışması: %d dalga, 20 gün fazla getiri %s", doc["n_events"], (doc["res"].get("a20") or {}).get("mean"))
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
