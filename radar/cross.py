"""Varlıklar arası görünüm: piyasa şeridi ve küresel risk rejimi.

İki çıktı:
  * `strip()`  → site/data/piyasa.json  (radar turunda, 15 dk): USD/TRY, EUR/TRY, XU100 (TL ve USD), gram altın, ons altın,
    Brent, bakır, ABD 10Y, DXY, S&P 500, VIX, BTC — son değer, günlük değişim, son 3 ayın eğilim çizgisi.
  * `regime()` → site/data/guc/cross.json (guc.yml, hafta içi akşam): 2010'dan bugüne günlük seriden kurallı rejim
    ve BIST'teki geçmiş karşılığı (rejim günlerinden sonraki 1 aylık XU100 getirisi, USD ve TL).

Rejim (açık kurallar; her bileşen 20 günlük değişimin son 1 yıldaki dağılımına göre z-puanı):
    risk iştahı = ortalama( +S&P 500, +bakır, +BTC, −VIX, −DXY, −ABD 10Y )   (eksik seri ortalamaya girmez)
    ≥ +0,5 "Risk iştahı yüksek" · ≤ −0,5 "Risk iştahı düşük" · arası "Karışık"
  Alt etiketler: dolar (DXY z ±0,5), küresel faiz (ABD 10Y 20 günde ±20 baz puan), TL (USD/TRY 20 günlük değişimi,
  son 1 yılın 80. yüzdeliğinin üstünde ise "değer kaybı hızlanıyor"), altın (z ±0,5).
Kaynak: Yahoo Finance (kişisel kullanım; ham fiyat geçmişi yayımlanmaz, yalnız son değer ve seyreltilmiş eğilim çizgisi).
"""
from __future__ import annotations

import json
import logging
import math
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .config import DATA

log = logging.getLogger("radar.cross")

GRAM = 31.1034768
# anahtar: (Yahoo, ad, birim, ondalık)
ASSETS = {
    "usdtry": ("USDTRY=X", "USD/TRY", "", 4),
    "eurtry": ("EURTRY=X", "EUR/TRY", "", 4),
    "xu100": ("XU100.IS", "BIST 100", "", 0),
    "xu100usd": (None, "BIST 100 ($)", "$", 1),
    "gram": (None, "Gram altın", "₺", 0),
    "gold": ("GC=F", "Ons altın", "$", 0),
    "brent": ("BZ=F", "Brent", "$", 2),
    "copper": ("HG=F", "Bakır", "$", 2),
    "us10y": ("^TNX", "ABD 10Y", "%", 2),
    "dxy": ("DX-Y.NYB", "DXY", "", 2),
    "spx": ("^GSPC", "S&P 500", "", 0),
    "vix": ("^VIX", "VIX", "", 1),
    "btc": ("BTC-USD", "Bitcoin", "$", 0),
}
RISK = {"spx": 1, "copper": 1, "btc": 1, "vix": -1, "dxy": -1, "us10y": -1}
STRIP_ORDER = ["usdtry", "xu100", "xu100usd", "gram", "brent", "us10y", "dxy", "spx", "vix", "btc", "eurtry", "gold", "copper"]
LOOK = 20


def _download(period: str | None = None, start: str | None = None) -> pd.DataFrame:
    import yfinance as yf
    tick = {k: v[0] for k, v in ASSETS.items() if v[0]}
    df = yf.download(" ".join(tick.values()), period=period, start=start, interval="1d", group_by="ticker",
                     auto_adjust=False, threads=True, progress=False)
    out = {}
    for k, y in tick.items():
        try:
            s = df[y]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if len(s):
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            out[k] = s[~s.index.duplicated(keep="last")]
    return pd.DataFrame(out).sort_index()


def derive(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "xu100" in df:                                  # 27.07.2020 XU100 100'e bölündü
        s = df["xu100"].dropna()
        r = s / s.shift(1)
        for d in r.index[(r < 0.05) | (r > 20)]:
            s.loc[s.index < d] *= r.loc[d]
        df["xu100"] = s
    f = df.ffill(limit=5)
    if {"xu100", "usdtry"} <= set(df):
        df["xu100usd"] = (f["xu100"] / f["usdtry"]).where(df["xu100"].notna())
    if {"gold", "usdtry"} <= set(df):
        df["gram"] = (f["gold"] * f["usdtry"] / GRAM).where(df["gold"].notna() | df["usdtry"].notna())
    return df


def _r(v, k=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, k) if math.isfinite(f) else None


def strip_doc(df: pd.DataFrame) -> dict:
    items = []
    for k in STRIP_ORDER:
        if k not in df:
            continue
        s = df[k].dropna()
        if len(s) < 2:
            continue
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        chg = (last - prev) if k == "us10y" else (last / prev - 1)
        tail = s.iloc[-66:]                            # ~3 ay
        step = max(1, len(tail) // 44)
        sp = tail.iloc[::-1][::step][::-1]
        m1 = s.iloc[-22] if len(s) > 22 else None
        items.append({"k": k, "label": ASSETS[k][1], "unit": ASSETS[k][2], "dec": ASSETS[k][3],
                      "last": _r(last, 6), "chg": _r(chg, 5), "chg_kind": "bp" if k == "us10y" else "pct",
                      "m1": _r((last - m1) if k == "us10y" else (last / m1 - 1), 5) if m1 else None,
                      "asof": s.index[-1].date().isoformat(), "spark": [_r(v, 6) for v in sp.values]})
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items}


def zscores(df: pd.DataFrame) -> pd.DataFrame:
    f = df.ffill(limit=5)
    out = {}
    for k in set(RISK) | {"gold", "usdtry"}:
        if k not in f:
            continue
        ch = (f[k] - f[k].shift(LOOK)) if k == "us10y" else np.log(f[k] / f[k].shift(LOOK))
        sd = ch.rolling(252, min_periods=120).std()
        out[k] = ch / sd
    return pd.DataFrame(out)


def label_at(z: pd.Series, f: pd.Series, usd_pct: float | None) -> dict:
    comps = {k: float(z[k]) * w for k, w in RISK.items() if k in z and pd.notna(z[k])}
    score = sum(comps.values()) / len(comps) if comps else None
    state = None if score is None else "on" if score >= 0.5 else "off" if score <= -0.5 else "mixed"
    tags = {}
    if pd.notna(z.get("dxy")):
        tags["dolar"] = "güçleniyor" if z["dxy"] >= 0.5 else "zayıflıyor" if z["dxy"] <= -0.5 else "yatay"
    if pd.notna(f.get("us10y_d")):
        tags["faiz"] = "yükseliyor" if f["us10y_d"] >= 0.20 else "düşüyor" if f["us10y_d"] <= -0.20 else "yatay"
    if usd_pct is not None:
        tags["tl"] = usd_pct
    if pd.notna(z.get("gold")):
        tags["altin"] = "yükseliyor" if z["gold"] >= 0.5 else "düşüyor" if z["gold"] <= -0.5 else "yatay"
    return {"score": score, "state": state, "comps": comps, "tags": tags}


def regime_doc(df: pd.DataFrame) -> dict:
    df = derive(df)
    f = df.ffill(limit=5)
    z = zscores(df)
    us10y_d = (f["us10y"] - f["us10y"].shift(LOOK)) if "us10y" in f else pd.Series(index=f.index, dtype=float)
    usd_ch = np.log(f["usdtry"] / f["usdtry"].shift(LOOK)) if "usdtry" in f else None
    usd_p80 = usd_ch.rolling(252, min_periods=120).quantile(0.8) if usd_ch is not None else None
    comp = pd.DataFrame({k: z[k] * w for k, w in RISK.items() if k in z})
    score = comp.mean(axis=1, skipna=True).where(comp.notna().sum(axis=1) >= 3)
    state = pd.Series(np.where(score >= 0.5, "on", np.where(score <= -0.5, "off", "mixed")), index=score.index).where(score.notna())
    # BIST karşılığı: rejim gününden sonraki 21 seans XU100 getirisi (USD ve TL); örtüşmesin diye 21 günde bir örnek
    fwd = {}
    for col in ("xu100usd", "xu100"):
        if col in f:
            fwd[col] = f[col].shift(-21) / f[col] - 1
    bt = {}
    idx = state.dropna().index
    sample = idx[::21]
    for st_ in ("on", "mixed", "off"):
        days = [d for d in sample if state.get(d) == st_]
        row = {"n": len(days)}
        for col, s in fwd.items():
            v = s.reindex(days).dropna()
            if len(v):
                row[col] = {"mean": _r(v.mean()), "median": _r(v.median()), "hit": _r((v > 0).mean(), 3), "n": int(len(v))}
        bt[st_] = row
    last = score.dropna().index[-1]
    zl, fl = z.loc[last], {"us10y_d": us10y_d.get(last)}
    tl = None
    if usd_ch is not None and pd.notna(usd_ch.get(last)):
        tl = {"m1": _r(math.exp(usd_ch[last]) - 1), "fast": bool(pd.notna(usd_p80.get(last)) and usd_ch[last] > usd_p80[last])}
    cur = label_at(zl, fl, None)
    hist = state.dropna()
    hist = hist[hist.index >= hist.index[-1] - pd.Timedelta(days=3 * 365)]
    # rejim şeridi: haftalık son değer
    wk = hist.resample("W-FRI").last().dropna()
    since = None
    for d in reversed(hist.index):
        if hist[d] != cur["state"]:
            break
        since = d
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": last.date().isoformat(), "state": cur["state"], "score": _r(cur["score"], 3),
        "since": since.date().isoformat() if since is not None else None,
        "comps": {k: _r(v, 2) for k, v in cur["comps"].items()},
        "z": {k: _r(zl.get(k), 2) for k in z.columns},
        "tags": {**cur["tags"], "tl": tl}, "us10y_d": _r(fl["us10y_d"], 3),
        "backtest": bt, "from": idx[0].date().isoformat() if len(idx) else None,
        "hist": [[d.date().isoformat(), s] for d, s in wk.items()],
        "score_hist": [[d.date().isoformat(), _r(v, 2)] for d, v in score.dropna().resample("W-FRI").last().dropna().iloc[-156:].items()],
    }


def strip(path=None) -> dict | None:
    try:
        df = derive(_download(period="6mo"))
    except Exception as e:  # noqa: BLE001
        log.warning("Piyasa şeridi alınamadı: %s", e)
        return None
    if df.empty:
        return None
    doc = strip_doc(df)
    p = path or DATA / "piyasa.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Piyasa şeridi: %d varlık", len(doc["items"]))
    return doc


def regime(path=None) -> dict | None:
    df = _download(start="2009-01-01")
    if df.empty:
        return None
    doc = regime_doc(df)
    p = path or DATA / "guc" / "cross.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Varlıklar arası rejim: %s (%.2f)", doc["state"], doc["score"] or 0)
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    regime() if "--regime" in sys.argv else strip()
