"""Kâğıt portföy: olay veritabanındaki kurallı stratejilerin geriye dönük ve ileriye doğru (canlı) izlenmesi.

İlk strateji, bilanço sürprizi (PEAD): finansal rapor olayı (küme başı), BIST, sürpriz yönü belli.
  • Giriş: olayın getiri başlangıç seansının (ts_eff) kapanışı — seans içi yayımlandıysa aynı gün, seans dışıysa sonraki
    seans kapanış seansı. Açılışta değil kapanışta girildiği için ilk günün tepkisinin bir kısmı kaçırılır (gerçekçi taraf).
  • Elde tutma: H seans (5 ve 20 değişkeleri), sonra kapanışta çıkış.
  • Ağırlık: açık pozisyonlar arasında eşit, her gün yeniden dengelenir (takvim zamanı portföyü). En az MIN_POS açık
    pozisyon yoksa o gün nakit (getiri 0; TL mevduat getirisi eklenmez): bilanço sezonu dışında kalan birkaç hisse
    portföyü tek hisse riskine çevirmesin.
  • Maliyet: alım ve satımda ayrı ayrı COST_SIDE (komisyon + kayma), net ve brüt ayrı raporlanır.
  • Bacaklar: olumlu sürpriz uzun; olumsuz sürpriz ayrıca izlenir; "uzun − kısa" teorik (BIST'te açığa satış kısıtlı).
Kıyas: eşit ağırlıklı BIST Tüm (aynı günler) ve XU100. Fiyat: Yahoo düzeltilmiş kapanış (temettü dahil).
Sıçrama (düzeltilmemiş bölünme izi) görülen pozisyon o günden itibaren kapatılmış sayılır.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

COST_SIDE = 0.002            # tek yön %0,20 (komisyon ~%0,05–0,1 + kayma)
HOLDS = (5, 20)
MIN_POS = 10                 # bundan az açık pozisyonlu günlerde nakitte kalınır: tek tük hisse portföyü tek hisse riskine çevirir
MIN_DAYS = 10


def _calendar(px: pd.DataFrame, universe: list[str]):
    from .eventdb import JUMP, ew_index
    px = px.assign(date=pd.to_datetime(px["date"]).dt.date)
    wide = px.pivot_table(index="date", columns="sym", values="adj_close", aggfunc="last").sort_index()
    cal = wide["XU100"].dropna()
    W = wide.reindex(cal.index)
    R = W.pct_change(fill_method=None)
    R = R.where(R.abs() <= JUMP)                     # sıçrama günü getirisi yok sayılır (pozisyon o gün kapanır)
    ew = ew_index(wide, universe).reindex(cal.index)
    return list(cal.index), R, cal, ew


def trades(ev: pd.DataFrame, dates: list[date], R: pd.DataFrame, hold: int) -> list[dict]:
    """ev: id, sym, ts_eff, dir, mag, period. Dönen: giriş/çıkış endeksleri ve pozisyon getirisi."""
    from .eventdb import SESS
    pos = {d: i for i, d in enumerate(dates)}
    out = []
    for r in ev.itertuples(index=False):
        if r.sym not in R.columns:
            continue
        de = pd.Timestamp(r.ts_eff).tz_convert(SESS["BIST"][0]).date()
        e = pos.get(de)
        if e is None:
            nxt = [k for k, d in enumerate(dates) if d >= de]
            if not nxt:
                continue
            e = nxt[0]
        x = e + hold
        rets = R[r.sym].to_numpy()[e + 1:min(x, len(dates) - 1) + 1]
        cut = np.argmax(np.isnan(rets)) if np.isnan(rets).any() else len(rets)
        rets = rets[:cut]
        closed = x <= len(dates) - 1 and cut == hold
        out.append({"id": r.id, "sym": r.sym, "dir": int(r.dir), "su": None if pd.isna(r.mag) else float(r.mag),
                    "period": getattr(r, "period", None), "e": e, "x": e + len(rets), "open": not closed and x > len(dates) - 1,
                    "gross": float(np.prod(1 + rets) - 1) if len(rets) else 0.0})
    return out


def nav(trs: list[dict], dates: list[date], R: pd.DataFrame, cost: float) -> np.ndarray:
    """Günlük portföy getirisi (eşit ağırlık, günlük dengeleme). Maliyet giriş ve çıkış gününün getirisinden düşülür."""
    n = len(dates)
    num, cnt = np.zeros(n), np.zeros(n)
    Rn = {s: R[s].to_numpy() for s in {t["sym"] for t in trs}}
    for t in trs:
        rs = Rn[t["sym"]]
        for k in range(t["e"] + 1, t["x"] + 1):
            v = rs[k]
            if np.isnan(v):
                break
            if k == t["e"] + 1:
                v -= cost
            if k == t["x"] and not t["open"]:
                v -= cost
            num[k] += v
            cnt[k] += 1
    ok = cnt >= MIN_POS
    daily = np.divide(num, cnt, out=np.zeros(n), where=ok)
    return daily, np.where(ok, cnt, 0)


def stats(daily: np.ndarray, active: np.ndarray | None = None) -> dict:
    d = daily if active is None else daily[active > 0]
    if len(d) < 2:
        return {}
    eq = np.cumprod(1 + daily)
    peak = np.maximum.accumulate(eq)
    sd = d.std(ddof=1)
    return {"total": round(float(eq[-1] - 1) * 100, 2), "ann_vol": round(float(sd * math.sqrt(252)) * 100, 1),
            "sharpe": round(float(d.mean() / sd * math.sqrt(252)), 2) if sd > 0 else None,
            "maxdd": round(float((eq / peak - 1).min()) * 100, 2), "days": int(len(d))}


def build(ev: pd.DataFrame, px: pd.DataFrame | None, universe: list[str], now: pd.Timestamp) -> dict:
    if px is None or px.empty or "XU100" not in set(px.sym):
        return {}
    import json as _json
    dates, R, cal, ew = _calendar(px, universe)
    f = ev[(ev.type == "finansal") & (ev.market == "BIST") & (ev.cluster == ev.id) & ev["dir"].isin([1, -1])].copy()
    f["period"] = f["payload"].map(lambda p: (_json.loads(p) if isinstance(p, str) else {}).get("period"))
    # aynı hisse + dönem için tek olay (düzeltme bildirimleri vb.)
    f = f.sort_values("ts").drop_duplicates(["sym", "period"], keep="first")
    first = None
    out = {"generated": now.isoformat(timespec="seconds"), "cost_side": COST_SIDE, "strategies": {}}
    for H in HOLDS:
        legs = {}
        for leg, d in (("long", 1), ("short", -1)):
            legs[leg] = trades(f[f["dir"] == d], dates, R, H)
        if not legs["long"] and not legs["short"]:
            continue
        lg_n, lg_c = nav(legs["long"], dates, R, COST_SIDE)
        lg_g, _ = nav(legs["long"], dates, R, 0.0)
        sh_n, sh_c = nav(legs["short"], dates, R, COST_SIDE)
        sh_g, _ = nav(legs["short"], dates, R, 0.0)
        start = min([t["e"] for t in legs["long"] + legs["short"]], default=0)
        first = start if first is None else min(first, start)
        ewr = ew.pct_change().fillna(0).to_numpy()
        xur = cal.pct_change().fillna(0).to_numpy()
        # teorik uzun − kısa (her bacak sermayenin %100'ü): kısa bacağın net getirisi = −brüt − maliyet = sh_n − 2·sh_g;
        # yalnız iki bacak birlikte açıkken; ödünç pay maliyeti yok sayılır
        both = (lg_c > 0) & (sh_c > 0)
        ls = np.where(both, lg_n + sh_n - 2 * sh_g, 0.0)
        sl = slice(start, None)
        long_x = np.where(lg_c > 0, lg_n - ewr, 0.0)             # yalnız yatırımda olunan günlerde kıyasa göre fark
        short_x = np.where(sh_c > 0, sh_n - ewr, 0.0)
        series = {"long": lg_n, "long_gross": lg_g, "short": sh_n, "ls": ls, "long_x": long_x, "short_x": short_x, "ew": ewr, "xu100": xur}
        act_of = {"long": lg_c, "long_gross": lg_c, "short": sh_c, "ls": both.astype(int), "long_x": lg_c, "short_x": sh_c}
        st = {k: stats(v[sl], act_of[k][sl] if k in act_of else None) for k, v in series.items()}
        # bacağın aktif günlerinde kıyasa göre fark (nakitte beklenen günler hariç)
        act = lg_c[sl] > 0
        st["long_vs_ew"] = round(float((lg_n[sl][act] - ewr[sl][act]).mean() * 252) * 100, 1) if act.sum() > 5 else None
        tr = []
        for leg, ts_ in legs.items():
            for t in ts_:
                tr.append({"sym": t["sym"], "leg": leg, "su": None if t["su"] is None else round(t["su"], 2), "period": t["period"],
                           "in": str(dates[t["e"]]), "out": None if t["open"] else str(dates[t["x"]]),
                           "ret": round(t["gross"] * 100, 2), "ret_net": round((t["gross"] - (COST_SIDE if t["open"] else 2 * COST_SIDE)) * 100, 2),
                           "open": t["open"]})
        closed = [t for t in tr if not t["open"]]
        hit = {leg: (round(sum(1 for t in closed if t["leg"] == leg and (t["ret_net"] > 0)) / max(1, sum(1 for t in closed if t["leg"] == leg)) * 100, 1),
                     sum(1 for t in closed if t["leg"] == leg)) for leg in ("long", "short")}
        out["strategies"][f"pead_{H}"] = {
            "label": f"Bilanço sürprizi · {H} seans", "hold": H,
            "nav": {k: [round(float(x), 5) for x in np.cumprod(1 + v[sl])] for k, v in series.items()},
            "npos": {"long": [int(x) for x in lg_c[sl]], "short": [int(x) for x in sh_c[sl]]},
            "stats": st, "hit": hit,
            "trades": sorted(tr, key=lambda t: t["in"], reverse=True)[:400],
            "n_trades": {leg: len(v) for leg, v in legs.items()},
        }
        out["strategies"][f"pead_{H}"]["dates"] = [str(d) for d in dates[sl]]
    return out
