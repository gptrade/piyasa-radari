"""BIST Korku–Açgözlülük Endeksi (Lyra): CNN Fear & Greed mantığıyla, yalnız BIST'te gözlenen fiyat ve genişlik
verisinden, 0 (aşırı korku) – 100 (aşırı açgözlülük).

Bileşenler (her biri son 3 yılın — 756 işlem günü — dağılımı içinde yüzdelik sıraya çevrilir; endeks mevcut
bileşenlerin eşit ağırlıklı ortalamasıdır):
  1. Piyasa momentumu   XU100'ün 125 günlük ortalamasından uzaklığı
  2. Fiyat gücü         52 haftalık net yeni zirve (zirve − dip) / izlenen hisse, 10 gün ortalaması (BIST Tüm)
  3. Hacim genişliği    yükselen hisselerin TL işlem hacmi payı, 10 gün ortalaması (McClellan hacim benzeri)
  4. Oynaklık           XU100 20 günlük gerçekleşen oynaklığının 1 yıllık ortalamasına oranı (ters: yüksek = korku)
  5. Güvenli liman      XU100'ün 20 günlük getirisi − TL gram altının 20 günlük getirisi
  6. Banka risk iştahı  XBANK'ın XU100'e göre 20 günlük göreli getirisi (yüksek betalı, yabancı akışına duyarlı)
  7. Kur baskısı        USD/TRY 20 günlük değişimi (ters: hızlı değer kaybı = korku)
  8. Kaldıraç           aracı kurumların kredili işlem bakiyesinin 3 aylık büyümesi − XU100 getirisi (TSPB; aylık,
                        yayım tarihinden itibaren)

Nominal TL eğilimi (enflasyon) yüzdelik sıra ile büyük ölçüde nötrlenir: her gösterge kendi son 3 yılıyla kıyaslanır.
Geçmiş: aynı kurallarla geriye doğru hesaplanır; bölge bazında ileri getiriler (USD bazlı XU100) şeffaflık için verilir.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

WINDOW = 756
MIN_HIST = 252
ZONES = [(25, "Aşırı korku"), (45, "Korku"), (55, "Nötr"), (75, "Açgözlülük"), (101, "Aşırı açgözlülük")]
COMP = [
    ("mom", "Piyasa momentumu", "XU100'ün 125 günlük ortalamasından uzaklığı"),
    ("nhl", "Fiyat gücü", "52 haftalık net yeni zirve oranı (BIST Tüm, 10 gün)"),
    ("upv", "Hacim genişliği", "Yükselen hisselerin TL hacim payı (10 gün)"),
    ("vol", "Oynaklık", "XU100 20 günlük oynaklığı / 1 yıllık ortalama (ters)"),
    ("safe", "Güvenli liman", "XU100 − gram altın, 20 günlük getiri farkı"),
    ("bank", "Banka risk iştahı", "XBANK'ın XU100'e göre 20 günlük göreli getirisi"),
    ("fx", "Kur baskısı", "USD/TRY 20 günlük değişimi (ters)"),
    ("lev", "Kaldıraç", "Kredili işlem bakiyesinin son 3 aydaki büyümesi − XU100 getirisi (TSPB, aylık)"),
]


def zone(v: float | None) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return next(lbl for hi, lbl in ZONES if v < hi)


def pct_rank(s: pd.Series, window: int = WINDOW, min_periods: int = MIN_HIST) -> pd.Series:
    """Son değerin, kendinden önceki pencere içindeki yüzdelik sırası (0–100; eşitler yarım sayılır)."""
    def f(x):
        h, last = x[:-1], x[-1]
        h = h[~np.isnan(h)]
        if np.isnan(last) or len(h) < min_periods - 1:
            return np.nan
        return ((h < last).mean() + 0.5 * (h == last).mean()) * 100
    return s.rolling(window, min_periods=min_periods).apply(f, raw=True)


def raw_components(b: pd.DataFrame, bench: pd.Series, extra: dict[str, pd.Series]) -> pd.DataFrame:
    """b: guc.breadth çıktısı (nh, nl, nhl_n, upv); bench: XU100; extra: GOLDTRY, XBANK, USDTRY (eksik olabilir)."""
    ix = b.index
    x = bench.reindex(ix).ffill()
    lr = np.log(x).diff()
    out = pd.DataFrame(index=ix)
    out["mom"] = x / x.rolling(125, min_periods=120).mean() - 1
    out["nhl"] = ((b["nh"] - b["nl"]) / b["nhl_n"].replace(0, np.nan)).rolling(10, min_periods=8).mean()
    out["upv"] = b["upv"].rolling(10, min_periods=8).mean()
    out["vol"] = -(lr.rolling(20, min_periods=18).std() / lr.rolling(252, min_periods=200).std())
    r20 = x / x.shift(20) - 1
    g = extra.get("GOLDTRY")
    if g is not None and g.notna().sum() > MIN_HIST:
        g = g.reindex(ix).ffill()
        out["safe"] = r20 - (g / g.shift(20) - 1)
    k = extra.get("XBANK")
    if k is not None and k.notna().sum() > MIN_HIST:
        k = k.reindex(ix).ffill()
        out["bank"] = (k / k.shift(20)) / (x / x.shift(20)) - 1
    u = extra.get("USDTRY")
    if u is not None and u.notna().sum() > MIN_HIST:
        u = u.reindex(ix).ffill()
        out["fx"] = -(u / u.shift(20) - 1)
    lv = extra.get("MARGIN")
    if lv is not None and lv.notna().sum() > MIN_HIST:
        out["lev"] = lv.reindex(ix).ffill()
    return out


def compute(b: pd.DataFrame, bench: pd.Series, extra: dict[str, pd.Series]) -> tuple[pd.Series, pd.DataFrame]:
    raw = raw_components(b, bench, extra)
    sc = raw.apply(pct_rank)
    need = max(3, math.ceil(0.6 * sc.shape[1]))
    idx = sc.mean(axis=1, skipna=True).where(sc.notna().sum(axis=1) >= need)
    return idx, sc


def forward_by_zone(idx: pd.Series, bench: pd.Series, usd: pd.Series | None, start: str = "2013-01-01") -> list[dict]:
    """Bölge başına ileri 1 ay / 3 ay XU100 getirisi (USD bazlı: TL'nin enflasyon eğilimi ayıklanır). Örtüşen pencereler:
    gözlemler bağımsız değildir, sayılar yönü gösterir, anlamlılık iddiası taşımaz."""
    x = bench.reindex(idx.index).ffill()
    if usd is not None:
        x = x / usd.reindex(idx.index).ffill()
    f21, f63 = x.shift(-21) / x - 1, x.shift(-63) / x - 1
    z = idx.map(zone)
    df = pd.DataFrame({"z": z, "f21": f21, "f63": f63}).loc[start:].dropna(subset=["z"])
    out = []
    for _, lbl in ZONES:
        d = df[df.z == lbl]
        d63 = d.f63.dropna()
        out.append({"zone": lbl, "days": int(len(d)), "share": round(len(d) / max(1, len(df)), 3),
                    "f21": _r(d.f21.dropna().median()), "f63": _r(d63.median()),
                    "hit63": _r((d63 > 0).mean() if len(d63) else None, 3)})
    return out


def _r(v, k=4):
    try:
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), k)
    except (TypeError, ValueError):
        return None


def build(b: pd.DataFrame, bench: pd.Series, extra: dict[str, pd.Series], hist_days: int = 3 * 252,
          margin: dict | None = None) -> dict | None:
    idx, sc = compute(b, bench, extra)
    ok = idx.dropna()
    if ok.empty:
        return None
    last = ok.index[-1]
    raw = raw_components(b, bench, extra)

    def ago(n):
        i = ok.index.get_loc(last) - n
        return _r(ok.iloc[i], 1) if i >= 0 else None
    comps = []
    for k, lbl, desc in COMP:
        if k not in sc:
            continue
        s = sc[k].loc[:last].dropna()
        if s.empty:
            continue
        v = float(s.iloc[-1])
        comps.append({"key": k, "label": lbl, "desc": desc, "score": _r(v, 1), "zone": zone(v),
                      "raw": _r(raw[k].loc[s.index[-1]], 4), "w1": _r(s.iloc[-6], 1) if len(s) > 5 else None})
    h = ok.iloc[-hist_days:]
    v = float(ok.iloc[-1])
    yr = ok.iloc[-252:]
    return {
        "asof": last.date().isoformat(), "value": _r(v, 1), "zone": zone(v),
        "prev": {"1G": ago(1), "1H": ago(5), "1A": ago(21), "1Y": ago(252)},
        "year": {"min": _r(yr.min(), 1), "min_d": yr.idxmin().date().isoformat(), "max": _r(yr.max(), 1),
                 "max_d": yr.idxmax().date().isoformat()},
        "components": comps,
        "hist": [[d.date().isoformat(), _r(x, 1)] for d, x in h.items()],
        "zones": forward_by_zone(idx, bench, extra.get("USDTRY")),
        "since": ok.index[0].date().isoformat(), "window": WINDOW, "margin": margin,
    }
