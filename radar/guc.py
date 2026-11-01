"""Piyasa Gücü — BIST'in iç gücü (genişlik), sektör rotasyonu ve güçlü sektörlerin güçlü hisseleri.

Girdi: BIST Tüm evreni (fin dalı _universe.json; KAP sektörleri) ve Yahoo günlük kapanış/hacim (2010'dan bugüne;
`guc` dalında Parquet olarak saklanır, yayımlanmaz). Çıktı yalnız türetilmiş göstergeler: site/data/guc/guc.json.

Katmanlar
  1. Genişlik: 20/50/200 günlük ortalamanın üstündeki hisse oranı, 52 haftalık yeni zirve/dip, yükselen–düşen çizgisi,
     McClellan osilatörü (oran ayarlı), yükselen hacim oranı, %90 günleri, genişlik sıçraması (Zweig), eşit ağırlıklı
     endeks / XU100, fiyat–genişlik diverjansı ve bunlardan kurallı bir piyasa rejimi.
  2. Sektör: KAP alt sektörü başına eşit ağırlıklı endeks; XU100'e göre göreli güç oranı ve ivmesi (haftalık; RRG benzeri
     dört bölge), sektör içi genişlik, hacim akışı, 0–100 sektör skoru.
  3. Hisse: göreli güç puanı (1–99; 3/6/9/12 ay ağırlıklı getiri sırası), trend şablonu (8 madde), 50 günlük yükselen/düşen
     gün hacmi oranı, likidite.

Fiyat temizliği: Yahoo bazı bedelsiz/bölünmeleri düzeltmez. ±%25'i aşan tek gün hareketi (BIST fiyat sınırı ±%10) sıfır
getiri sayılarak temiz bir seri zincirlenir; ortalamalar ve zirve/dip bu seriyle hesaplanır.
Sınır: borsadan çıkmış hisseler Yahoo'da yok (eski yıllarda evren daha küçük ve hayatta kalanlardan oluşur); bu yüzden
sayılar yerine oranlar esas alınır.

`python -m radar.guc [--full]` (guc.yml, hafta içi kapanıştan sonra).
"""
from __future__ import annotations

import json
import logging
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA

log = logging.getLogger("radar.guc")

OUT = DATA / "guc"
PX = OUT / "px.parquet"
FIN = DATA / "fin"
START = "2010-01-01"
JUMP = 0.25
BENCH = "XU100"
YF = {"XU100": "XU100.IS"}
HIST_DAYS = 3 * 252          # grafiklerde gösterilen geçmiş
MIN_SECTOR = 3
RRG_N = 10                   # hafta: göreli güç oranının ortalaması
RRG_M = 4                    # hafta: ivme farkı
TAIL = 8                     # hafta: rotasyon kuyruğu
LIQ_TL = 5e6                 # günlük medyan TL hacim eşiği (liste için)


# ───────────────────────────── veri

def universe() -> list[dict]:
    p = FIN / "_universe.json"
    return json.loads(p.read_text(encoding="utf-8")).get("members", []) if p.exists() else []


def _download(yf, yfs: dict[str, str], start: str, size: int = 50) -> list[pd.DataFrame]:
    import time as _t
    frames, items = [], list(yfs.items())
    for i in range(0, len(items), size):
        if i:
            _t.sleep(1.5)
        part = dict(items[i:i + size])
        try:
            df = yf.download(" ".join(part.values()), start=start, interval="1d", group_by="ticker",
                             auto_adjust=False, actions=False, threads=True, progress=False)
        except Exception as e:  # noqa: BLE001
            log.warning("Fiyat indirilemedi: %s", e)
            continue
        for sym, y in part.items():
            try:
                g = df[y] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            g = g.dropna(subset=["Close"])
            if g.empty:
                continue
            frames.append(pd.DataFrame({"sym": sym, "date": pd.to_datetime(g.index).date, "close": g["Close"].astype(float).round(4).values,
                                        "adj": g["Adj Close"].astype(float).round(4).values,
                                        "volume": g["Volume"].fillna(0).astype("int64").values}))
    return frames


def update_px(symbols: list[str], old: pd.DataFrame | None, full: bool) -> pd.DataFrame | None:
    import yfinance as yf
    have = set() if old is None or old.empty else set(old.sym.unique())
    new_syms = [s for s in symbols if s not in have]
    yfs = {s: YF.get(s, f"{s}.IS") for s in symbols}
    frames = []
    if full or old is None or old.empty:
        frames += _download(yf, yfs, START)
    else:
        frames += _download(yf, {s: yfs[s] for s in symbols if s in have}, (date.today() - pd.Timedelta(days=40)).isoformat(), size=80)
        if new_syms:
            frames += _download(yf, {s: yfs[s] for s in new_syms}, START)
    got = {f.sym.iloc[0] for f in frames}
    miss = {s: y for s, y in yfs.items() if s not in got}
    if miss:                                            # Yahoo hız sınırı: eksikleri küçük parçalarla bir kez daha
        import time as _t
        _t.sleep(30)
        recent = (date.today() - pd.Timedelta(days=40)).isoformat()
        fresh = {s: y for s, y in miss.items() if full or s not in have}
        frames += _download(yf, fresh, START, size=10) if fresh else []
        rest = {s: y for s, y in miss.items() if s not in fresh}
        frames += _download(yf, rest, recent, size=10) if rest else []
    if not frames:
        return old
    new = pd.concat(frames, ignore_index=True)
    if old is None or old.empty:
        out = new
    else:
        old = old.assign(date=pd.to_datetime(old["date"]).dt.date)
        # yeni temettü düzeltmesi eski satırları değiştirir: çakışan son tarihteki oranla eski düzeltilmiş kapanışı ölçekle
        ref = new.sort_values("date").groupby("sym").first()
        k = old.set_index(["sym", "date"])["adj"]
        for s, r in ref.iterrows():
            try:
                o = k.loc[(s, r["date"])]
            except KeyError:
                continue
            if o and r["adj"] and abs(r["adj"] / o - 1) > 1e-4:
                old.loc[old.sym.eq(s), "adj"] *= r["adj"] / o
        out = pd.concat([old, new], ignore_index=True)
    return out.drop_duplicates(["sym", "date"], keep="last").sort_values(["sym", "date"]).reset_index(drop=True)


def wide(px: pd.DataFrame, col: str) -> pd.DataFrame:
    w = px.pivot_table(index="date", columns="sym", values=col, aggfunc="last").sort_index()
    w.index = pd.to_datetime(w.index)
    return w


def clean_index(s: pd.Series) -> pd.Series:
    """Endeks ölçek kırılması (XU100 2020'de 100'e bölündü): ×50'den büyük günlük kırılmada önceki kısmı ölçekle."""
    s = s.dropna().copy()
    r = s / s.shift(1)
    for d in r.index[(r < 0.05) | (r > 20)]:
        f = r.loc[d]
        s.loc[s.index < d] *= f
    return s


def clean_prices(adj: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(temiz fiyat, günlük getiri). Getiri: ±%25 üstü tek gün hareketi 0 (düzeltilmemiş bölünme/bedelsiz)."""
    r = adj.pct_change(fill_method=None)
    r = r.mask(r.abs() > JUMP, 0.0)
    first = adj.notna() & adj.ffill().shift(1).isna()       # her hissenin ilk günü
    level = (1 + r.fillna(0)).cumprod()
    level = level.where(adj.ffill().notna())
    base = adj.where(first).ffill()                         # ilk fiyat düzeyine oturt (okunabilir değerler)
    lv0 = level.where(first).ffill()
    clean = level / lv0 * base
    clean = clean.where(adj.notna())                        # işlem olmayan günler boş
    return clean, r.where(adj.notna())


# ───────────────────────────── 1. genişlik

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def breadth(clean: pd.DataFrame, ret: pd.DataFrame, tlv: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    traded = clean.notna()
    hist = traded.cumsum()
    out = pd.DataFrame(index=clean.index)
    adv, dec = (ret > 0).sum(axis=1), (ret < 0).sum(axis=1)
    out["adv"], out["dec"] = adv, dec
    out["n"] = traded.sum(axis=1)
    tot = (adv + dec).replace(0, np.nan)
    out["adr"] = adv / tot                                    # yükselen oranı
    out["ad_line"] = (adv - dec).cumsum()
    net_ratio = ((adv - dec) / tot * 1000).fillna(0)          # oran ayarlı (evren büyüklüğünden bağımsız)
    out["mco"] = ema(net_ratio, 19) - ema(net_ratio, 39)
    out["msi"] = out["mco"].cumsum()
    ff = clean.ffill(limit=5)
    for n in (20, 50, 200):
        ma = ff.rolling(n, min_periods=n).mean()
        ok = ma.notna() & traded
        out[f"p{n}"] = ((clean > ma) & ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan)
    hi = ff.rolling(252, min_periods=230).max().shift(1)
    lo = ff.rolling(252, min_periods=230).min().shift(1)
    ok = hi.notna() & traded
    out["nh"] = ((clean > hi) & ok).sum(axis=1)
    out["nl"] = ((clean < lo) & ok).sum(axis=1)
    out["nhl_n"] = ok.sum(axis=1)
    upv = tlv.where(ret > 0).sum(axis=1)
    dnv = tlv.where(ret < 0).sum(axis=1)
    out["upv"] = upv / (upv + dnv).replace(0, np.nan)
    out["tlv"] = tlv.sum(axis=1)
    ew = (1 + ret.mean(axis=1).fillna(0)).cumprod() * 100
    out["ew"] = ew
    b = bench.reindex(out.index).ffill()
    out["bench"] = b
    out["ew_rel"] = ew / b
    # yeterli genişlik verisi olmayan ilk dönemi at
    return out[out["n"] >= 30]


def thrusts(b: pd.DataFrame) -> list[str]:
    """Zweig genişlik sıçraması: yükselen oranının 10 günlük EMA'sı 10 seans içinde < 0,40'tan > 0,615'e."""
    e = ema(b["adr"].fillna(0.5), 10)
    out, last = [], None
    vals, idx = e.values, e.index
    for i in range(len(vals)):
        if vals[i] > 0.615 and (vals[max(0, i - 10):i] < 0.40).any():
            if last is None or (idx[i] - last).days > 30:
                out.append(idx[i].date().isoformat())
            last = idx[i]
    return out


def ninety_days(b: pd.DataFrame) -> list[dict]:
    """%90 günleri: yükselen (ya da düşen) hisselerin hacmi toplam hacmin ≥ %90'ı."""
    out = []
    for d, v in b["upv"].items():
        if v is None or not np.isfinite(v):
            continue
        if v >= 0.9:
            out.append({"d": d.date().isoformat(), "k": "up"})
        elif v <= 0.1:
            out.append({"d": d.date().isoformat(), "k": "down"})
    return out


def divergences(b: pd.DataFrame, win: int = 63) -> list[dict]:
    """Endeks yeni 63 günlük dip yaparken yeni 52 haftalık dibe düşen hisse sayısı pencere zirvesinin yarısından azsa
    pozitif; endeks 63 günlük zirvedeyken yeni zirve sayısı pencere zirvesinin yarısından azsa negatif diverjans."""
    out, last = [], {}
    x, nh, nl = b["bench"], b["nh"], b["nl"]
    lo, hi = x.rolling(win).min(), x.rolling(win).max()
    for i in range(win, len(b)):
        d = b.index[i]
        for k, cond, cnt in (("pos", x.iloc[i] <= lo.iloc[i] * 1.0001, nl), ("neg", x.iloc[i] >= hi.iloc[i] * 0.9999, nh)):
            if not cond:
                continue
            peak = cnt.iloc[i - win:i].max()
            if peak >= 20 and cnt.iloc[i] < peak / 2 and (k not in last or (d - last[k]).days > 20):
                out.append({"d": d.date().isoformat(), "k": k, "now": int(cnt.iloc[i]), "peak": int(peak)})
                last[k] = d
    return out


def regime(b: pd.DataFrame, events: dict) -> dict:
    """Kurallı piyasa rejimi. Koşullar açıkça listelenir (kara kutu yok)."""
    x = b["bench"]
    s50, s200 = x.rolling(50).mean(), x.rolling(200).mean()
    t = b.index[-1]
    last = b.iloc[-1]
    nhl50 = (b["nh"] - b["nl"]).rolling(50).mean().iloc[-1]
    c = {
        "above200": bool(x.iloc[-1] > s200.iloc[-1]),
        "above50": bool(x.iloc[-1] > s50.iloc[-1]),
        "golden": bool(s50.iloc[-1] > s200.iloc[-1]),
        "rising200": bool(s200.iloc[-1] > s200.iloc[-22]),
        "br200": float(last["p200"]), "br50": float(last["p50"]), "br20": float(last["p20"]),
        "nhl50": float(nhl50), "mco": float(last["mco"]),
    }
    recent = lambda lst, days, k=None: [e for e in lst if (t - pd.Timestamp(e["d"] if isinstance(e, dict) else e)).days <= days and (k is None or e.get("k") == k)]  # noqa: E731
    thrust = recent(events["thrust"], 30)
    down90 = recent(events["ninety"], 15, "down")
    up90 = recent(events["ninety"], 15, "up")
    posdiv = recent(events["div"], 30, "pos")
    negdiv = recent(events["div"], 30, "neg")
    oversold = c["br20"] < 0.15 or c["br50"] < 0.15
    if thrust or (not c["above200"] and up90 and down90):
        state, why = "toparlanma", "Genişlik sıçraması ya da panik satışının ardından güçlü alım günü: yükselişin tabana yayıldığı erken işaret."
    elif c["above200"] and c["golden"] and c["br200"] >= 0.5 and nhl50 > 0:
        state, why = "boga", "Endeks yükselen 200 günlük ortalamanın üstünde, hisselerin çoğu da öyle; yeni zirveler yeni diplerden fazla."
    elif not c["above200"] and c["br200"] < 0.4 and nhl50 < 0:
        state = "dip" if (oversold or down90 or posdiv) else "ayi"
        why = ("Düşüş trendi sürüyor ama aşırı satım, panik satışı ya da pozitif diverjans var: dip arayışı. Teyit için genişlik sıçraması ya da %90 alım günü beklenir."
               if state == "dip" else "Endeks 200 günlük ortalamanın altında, hisselerin çoğu da öyle; yeni dipler yeni zirvelerden fazla.")
    else:
        state = "duzeltme"
        why = "Karışık tablo: endeks ile genişlik aynı yönü göstermiyor ya da kısa vadeli ortalamanın altına inildi."
    return {"state": state, "why": why, "asof": t.date().isoformat(), "c": c,
            "flags": {"thrust": thrust[-1] if thrust else None, "down90": len(down90), "up90": len(up90),
                      "posdiv": posdiv[-1] if posdiv else None, "negdiv": negdiv[-1] if negdiv else None, "oversold": oversold}}


def regime_history(b: pd.DataFrame, events: dict, step: int = 5) -> list[list]:
    """Geçmişte rejim (her 5 seansta bir) — grafikte arka plan şeridi için."""
    out = []
    start = max(250, len(b) - HIST_DAYS)
    for i in range(start, len(b), step):
        sub = b.iloc[: i + 1]
        t = sub.index[-1]
        ev = {k: [e for e in v if pd.Timestamp(e["d"] if isinstance(e, dict) else e) <= t] for k, v in events.items()}
        out.append([t.date().isoformat(), regime(sub, ev)["state"]])
    return out


# ───────────────────────────── 2. sektör

def sector_index(ret: pd.DataFrame, members: list[str]) -> pd.Series:
    cols = [c for c in members if c in ret.columns]
    return (1 + ret[cols].mean(axis=1).fillna(0)).cumprod() * 100


def rrg(idx: pd.Series, bench: pd.Series) -> pd.DataFrame:
    """Haftalık göreli güç oranı ve ivmesi (RRG benzeri; kendi formülümüz):
    oran = 100 × RS / EMA10(RS), ivme = 100 + (oran − 4 hafta önceki oran)."""
    wk = pd.concat([idx, bench], axis=1).dropna().resample("W-FRI").last().dropna()
    rs = wk.iloc[:, 0] / wk.iloc[:, 1]
    ratio = 100 * rs / ema(rs, RRG_N)
    mom = 100 + (ratio - ratio.shift(RRG_M))
    return pd.DataFrame({"ratio": ratio, "mom": mom}).dropna()


def quad(r: float, m: float) -> str:
    return "lider" if r >= 100 and m >= 100 else "zayif" if r >= 100 else "geride" if m < 100 else "iyilesen"


PERIODS = {"1G": 1, "1H": 5, "1A": 21, "3A": 63, "6A": 126, "1Y": 252}


def period_ret(level: pd.DataFrame | pd.Series, n: int) -> pd.Series | float:
    return level.iloc[-1] / level.iloc[-1 - n] - 1 if len(level) > n else None


def ytd_ret(level):
    y = level.index[-1].year
    prev = level[level.index.year < y]
    return level.iloc[-1] / prev.iloc[-1] - 1 if len(prev) else None


# ───────────────────────────── 3. hisse

def rs_rating(clean: pd.DataFrame) -> pd.Series:
    """IBD benzeri: 0,4·3A + 0,2·6A + 0,2·9A + 0,2·12A getiri; evren içinde 1–99 yüzdelik."""
    ff = clean.ffill(limit=5)
    last = ff.iloc[-1]
    def r(n):
        return last / ff.iloc[-1 - n] - 1 if len(ff) > n else pd.Series(np.nan, index=ff.columns)
    r3, r6, r9, r12 = r(63), r(126), r(189), r(252)
    score = 0.4 * r3 + 0.2 * r6.fillna(r3) + 0.2 * r9.fillna(r6.fillna(r3)) + 0.2 * r12.fillna(r9.fillna(r6.fillna(r3)))
    score = score[last.notna() & r3.notna()]
    return (score.rank(pct=True) * 98 + 1).round()


def trend_template(c: pd.Series) -> tuple[int, list[bool]] | None:
    """Minervini trend şablonu (8 madde; 8. madde göreli güç ayrı verilir)."""
    c = c.dropna()
    if len(c) < 260:
        return None
    p = c.iloc[-1]
    s50, s150, s200 = c.rolling(50).mean(), c.rolling(150).mean(), c.rolling(200).mean()
    hi, lo = c.iloc[-252:].max(), c.iloc[-252:].min()
    items = [p > s150.iloc[-1] and p > s200.iloc[-1], s150.iloc[-1] > s200.iloc[-1], s200.iloc[-1] > s200.iloc[-22],
             s50.iloc[-1] > s150.iloc[-1] and s50.iloc[-1] > s200.iloc[-1], p > s50.iloc[-1],
             p >= lo * 1.3, p >= hi * 0.75]
    items = [bool(x) for x in items]
    return sum(items), items


# ───────────────────────────── birleştir

def _r(v, k=4):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, k) if math.isfinite(f) else None


def series_out(b: pd.DataFrame) -> dict:
    t = b.iloc[-HIST_DAYS:]
    cols = {"bench": 2, "ew": 2, "ew_rel": 5, "p20": 3, "p50": 3, "p200": 3, "nh": 0, "nl": 0, "adv": 0, "dec": 0,
            "ad_line": 0, "mco": 1, "msi": 0, "upv": 3, "adr": 3, "nhl_n": 0}
    out = {"d": [d.date().isoformat() for d in t.index]}
    for k, nd in cols.items():
        out[k] = [None if not np.isfinite(v) else (int(v) if nd == 0 else round(float(v), nd)) for v in t[k].astype(float).values]
    return out


def build(px: pd.DataFrame, members: list[dict], screen: dict | None = None) -> dict:
    codes = {m["code"] for m in members}
    adj = wide(px, "adj")
    close = wide(px, "close")
    vol = wide(px, "volume")
    bench = clean_index(adj[BENCH]) if BENCH in adj else None
    stocks = [c for c in adj.columns if c in codes]
    adj, close, vol = adj[stocks], close[stocks], vol[stocks]
    # tatil artığı satırlar (yalnız birkaç hissede kayıt): getirileri bozmasın diye at
    cnt = adj.notna().sum(axis=1)
    keep = cnt >= 0.5 * cnt.rolling(20, min_periods=1).median()
    adj, close, vol = adj[keep], close[keep], vol[keep]
    clean, ret = clean_prices(adj)
    tlv = (close * vol).where(close.notna())
    b = breadth(clean, ret, tlv, bench)
    clean, ret, tlv = clean.loc[b.index[0]:], ret.loc[b.index[0]:], tlv.loc[b.index[0]:]
    events = {"thrust": thrusts(b), "ninety": ninety_days(b), "div": divergences(b)}
    reg = regime(b, events)
    since = b.index[-HIST_DAYS] if len(b) > HIST_DAYS else b.index[0]
    ev_out = {"thrust": [e for e in events["thrust"] if pd.Timestamp(e) >= since],
              "ninety": [e for e in events["ninety"] if pd.Timestamp(e["d"]) >= since],
              "div": [e for e in events["div"] if pd.Timestamp(e["d"]) >= since]}

    # ── sektörler
    sec_of = {m["code"]: m.get("sector") or "DİĞER" for m in members}
    by: dict[str, list[str]] = {}
    for c in clean.columns:
        by.setdefault(sec_of.get(c, "DİĞER"), []).append(c)
    ff = clean.ffill(limit=5)
    ma50 = ff.rolling(50, min_periods=50).mean()
    tv20, tv60 = tlv.iloc[-20:].sum(), tlv.iloc[-60:].sum()
    tot20, tot60 = tv20.sum(), tv60.sum()
    rsr = rs_rating(clean)
    ok_last = clean.iloc[-1].notna()
    sectors = []
    bw = b["bench"]
    for name, cols in by.items():
        live = [c for c in cols if ok_last.get(c, False)]
        if len(live) < MIN_SECTOR:
            continue
        idx = sector_index(ret, cols)
        rr = rrg(idx, bw)
        if len(rr) < TAIL + 1:
            continue
        rets = {k: _r(period_ret(idx, n)) for k, n in PERIODS.items()}
        rets["YBB"] = _r(ytd_ret(idx))
        med = {k: _r(float((ff[live].iloc[-1] / ff[live].iloc[-1 - n] - 1).median())) if len(ff) > n else None for k, n in PERIODS.items()}
        yb = ff[live][ff.index.year < ff.index[-1].year]
        med["YBB"] = _r(float((ff[live].iloc[-1] / yb.iloc[-1] - 1).median())) if len(yb) else None
        ma_ok = ma50[live].iloc[-1].notna()
        br50 = float((ff[live].iloc[-1] > ma50[live].iloc[-1])[ma_ok].mean()) if ma_ok.any() else None
        br50_prev = None
        if len(ff) > 6:
            m_prev = ma50[live].iloc[-6]
            okp = m_prev.notna()
            br50_prev = float((ff[live].iloc[-6] > m_prev)[okp].mean()) if okp.any() else None
        s20, s60 = float(tv20[live].sum()), float(tv60[live].sum())
        vflow = (s20 / 20) / (s60 / 60) if s60 > 0 else None
        share, share60 = (s20 / tot20 if tot20 else None), (s60 / tot60 if tot60 else None)
        vshare = share / share60 if share and share60 else None      # piyasa hacmindeki payın 20g / 60g oranı (göreli para akışı)
        lead = sorted(((float(rsr[c]), c) for c in live if c in rsr.index), reverse=True)
        r_last = rr.iloc[-1]
        sectors.append({"name": name, "n": len(live), "ret": rets, "med": med,
                        "ratio": _r(r_last["ratio"], 2), "mom": _r(r_last["mom"], 2), "quad": quad(r_last["ratio"], r_last["mom"]),
                        "tail": [[_r(a, 2), _r(m, 2)] for a, m in rr[["ratio", "mom"]].iloc[-TAIL:].values],
                        "quad_prev": quad(*rr[["ratio", "mom"]].iloc[-2].values),
                        "br50": _r(br50, 3), "br50_prev": _r(br50_prev, 3), "vflow": _r(vflow, 3), "vshare": _r(vshare, 3),
                        "share": _r(share, 4), "share_chg": _r(share - share60, 4) if share is not None and share60 is not None else None,
                        "leaders": [c for _, c in lead[:5]], "rs_med": _r(float(np.median([v for v, _ in lead])) if lead else None, 1)})
    # sektör skoru: göreli güç (3A medyan getiri), oran, ivme, genişlik, hacim akışı → yüzdelik ortalaması
    if sectors:
        W = pd.Series({"r3": 0.25, "ratio": 0.25, "mom": 0.2, "br": 0.15, "vf": 0.15})
        score = lambda d: (d.rank(pct=True).fillna(0.5) * W).sum(axis=1) / W.sum() * 100  # noqa: E731
        df = pd.DataFrame([{"name": s["name"], "r3": s["med"].get("3A"), "ratio": s["ratio"], "mom": s["mom"], "br": s["br50"],
                            "vf": s["vshare"]} for s in sectors]).set_index("name")
        sc = score(df)
        # bir hafta önceki skor (sıra değişimi için)
        prev = {}
        for s in sectors:
            t = s["tail"]
            prev[s["name"]] = {"ratio": t[-2][0] if len(t) > 1 else None, "mom": t[-2][1] if len(t) > 1 else None}
        dp = df.copy()
        dp["ratio"] = [prev[n]["ratio"] for n in dp.index]
        dp["mom"] = [prev[n]["mom"] for n in dp.index]
        dp["br"] = [next(x["br50_prev"] for x in sectors if x["name"] == n) for n in dp.index]
        scp = score(dp)
        rk, rkp = sc.rank(ascending=False, method="min"), scp.rank(ascending=False, method="min")
        for s in sectors:
            s["score"] = _r(sc[s["name"]], 0)
            s["rank"], s["rank_prev"] = int(rk[s["name"]]), int(rkp[s["name"]])
        sectors.sort(key=lambda s: s["rank"])

    # ── hisseler
    sec_by = {s["name"]: s for s in sectors}
    scr = {r["code"]: r for r in (screen or {}).get("rows", [])}
    rows = []
    up_d = (ret > 0)
    v50 = tlv.iloc[-50:]
    udv = (v50.where(up_d.iloc[-50:]).sum() / v50.where(ret.iloc[-50:] < 0).sum().replace(0, np.nan))
    med_tv = tlv.iloc[-20:].median()
    hi52 = ff.iloc[-252:].max()
    for c in clean.columns:
        if not ok_last.get(c, False) or c not in rsr.index:
            continue
        tt = trend_template(clean[c])
        s = sec_of.get(c, "DİĞER")
        sd = sec_by.get(s)
        last = ff[c].iloc[-1]
        sr = scr.get(c, {})
        rows.append({"code": c, "sector": s, "quad": sd["quad"] if sd else None, "srank": sd["rank"] if sd else None,
                     "rs": int(rsr[c]), "tt": tt[0] if tt else None, "tti": tt[1] if tt else None,
                     "udv": _r(udv.get(c), 2), "tv": _r(med_tv.get(c), 0),
                     "liq": bool((med_tv.get(c) or 0) >= LIQ_TL),
                     "hi": _r(last / hi52[c] - 1, 4) if hi52.get(c) else None,
                     "r1a": _r(period_ret(ff[c].dropna(), 21)), "r3a": _r(period_ret(ff[c].dropna(), 63)),
                     "f": sr.get("f"), "grade": sr.get("grade")})
    rows.sort(key=lambda r: -r["rs"])
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "asof": b.index[-1].date().isoformat(), "start": b.index[0].date().isoformat(),
        "universe": int(b["n"].iloc[-1]), "liq_tl": LIQ_TL,
        "regime": reg, "regime_hist": regime_history(b, events), "events": ev_out,
        "series": series_out(b), "sectors": sectors, "stocks": rows,
    }


def run(full: bool = False, offline: bool = False) -> dict:
    members = universe()
    if not members:
        raise SystemExit("Evren yok (fin/_universe.json)")
    OUT.mkdir(parents=True, exist_ok=True)
    old = pd.read_parquet(PX) if PX.exists() else None
    if not offline:
        px = update_px([BENCH] + sorted(m["code"] for m in members), old, full)
        if px is None:
            raise SystemExit("Fiyat alınamadı")
        px.to_parquet(PX, compression="zstd", index=False)
    else:
        px = old
    screen = json.loads((FIN / "_screen.json").read_text(encoding="utf-8")) if (FIN / "_screen.json").exists() else None
    doc = build(px, members, screen)
    (OUT / "guc.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Piyasa gücü: %s · rejim %s · %d sektör · %d hisse", doc["asof"], doc["regime"]["state"], len(doc["sectors"]), len(doc["stocks"]))
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run(full="--full" in sys.argv, offline="--offline" in sys.argv)
