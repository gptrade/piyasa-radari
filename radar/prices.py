"""Fiyat verisi (Yahoo Finance üzerinden yfinance), teknik göstergeler ve haber sonrası fiyat tepkisi.

Bar biçimi: [unix_saniye, kapanış, hacim]  (hacim olmayan eski dosyalarda sadece ilk iki alan olabilir)
"""
from __future__ import annotations

import bisect
import json
import logging
from datetime import timedelta

from .config import DATA, Stock
from .models import iso, now_utc, parse_iso

log = logging.getLogger("radar.prices")

PRICE_DIR = DATA / "prices"
HORIZONS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
# Tepkiyi piyasa hareketinden ayırmak için karşılaştırma endeksleri
INDEXES = {"BIST": Stock("_XU100", "BIST 100", "BIST", []), "US": Stock("_SPX", "S&P 500", "US", [])}
INDEX_YAHOO = {"_XU100": "XU100.IS", "_SPX": "^GSPC"}


def _series(df) -> list[list[float]]:
    if df is None or df.empty:
        return []
    close = df["Close"]
    if hasattr(close, "columns"):          # yfinance çoklu sütun döndürebilir
        close = close.iloc[:, 0]
    vol = df["Volume"] if "Volume" in df else None
    if vol is not None and hasattr(vol, "columns"):
        vol = vol.iloc[:, 0]
    out = []
    for ts, v in close.items():
        if v != v:                          # NaN
            continue
        row = [int(ts.timestamp()), round(float(v), 4)]
        if vol is not None:
            x = vol.get(ts)
            row.append(int(x) if x == x and x is not None else 0)
        out.append(row)
    return out


# ------------------------------------------------------------------ teknik göstergeler
def _sma(xs: list[float], n: int) -> float | None:
    return sum(xs[-n:]) / n if len(xs) >= n else None


def _ema_series(xs: list[float], n: int) -> list[float]:
    if not xs:
        return []
    k, out = 2 / (n + 1), [xs[0]]
    for x in xs[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _rsi(xs: list[float], n: int = 14) -> float | None:
    if len(xs) <= n:
        return None
    gains = [max(0.0, b - a) for a, b in zip(xs, xs[1:])]
    losses = [max(0.0, a - b) for a, b in zip(xs, xs[1:])]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):      # Wilder yumuşatması
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def technicals(daily: list[list[float]], live: bool = False) -> dict | None:
    """live=True: son günlük bar süren seansa ait (hacmi eksik); hacim oranı son tamamlanmış günden."""
    closes = [b[1] for b in daily]
    if len(closes) < 30:
        return None
    last = closes[-1]
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    rsi = _rsi(closes)
    e12, e26 = _ema_series(closes, 12), _ema_series(closes, 26)
    macd = [a - b for a, b in zip(e12, e26)]
    sig = _ema_series(macd, 9)
    hist = [a - b for a, b in zip(macd, sig)]
    cross = None
    for k in range(1, min(4, len(hist))):            # son 3 günde kesişim
        if hist[-k] > 0 >= hist[-k - 1]:
            cross = "al"
            break
        if hist[-k] < 0 <= hist[-k - 1]:
            cross = "sat"
            break
    window = closes[-252:]
    hi, lo = max(window), min(window)
    vols = [b[2] for b in daily if len(b) > 2 and b[2]]
    if live and len(vols) > 1:
        vols = vols[:-1]
    vol_ratio = round(vols[-1] / (sum(vols[-21:-1]) / 20), 2) if len(vols) >= 21 and sum(vols[-21:-1]) else None

    if sma20 and sma50 and last > sma20 > sma50:
        trend = "yukarı"
    elif sma20 and sma50 and last < sma20 < sma50:
        trend = "aşağı"
    else:
        trend = "yatay"
    signals = []
    if rsi is not None and rsi >= 70:
        signals.append(f"RSI {rsi:.0f}: aşırı alım")
    elif rsi is not None and rsi <= 30:
        signals.append(f"RSI {rsi:.0f}: aşırı satım")
    if cross == "al":
        signals.append("MACD yukarı kesti")
    elif cross == "sat":
        signals.append("MACD aşağı kesti")
    if sma50 and len(closes) > 1:
        prev_above, now_above = closes[-2] > sma50, last > sma50
        if now_above != prev_above:
            signals.append("50 günlük ortalamanın " + ("üstüne çıktı" if now_above else "altına indi"))
    if hi != lo and (hi - last) / (hi - lo) < 0.03:
        signals.append("52 hafta zirvesine yakın")
    elif hi != lo and (last - lo) / (hi - lo) < 0.03:
        signals.append("52 hafta dibine yakın")
    if vol_ratio and vol_ratio >= 2:
        signals.append(f"Hacim ortalamanın {vol_ratio:.1f} katı")

    score = 0                                           # -3..+3 kaba teknik görünüm
    score += {"yukarı": 1, "aşağı": -1}.get(trend, 0)
    score += 1 if macd[-1] > sig[-1] else -1
    if rsi is not None:
        score += 1 if 50 < rsi < 70 else -1 if 30 < rsi < 50 else 0
    r = lambda x, d=2: round(x, d) if x is not None else None
    return {
        "trend": trend, "score": score, "rsi": r(rsi, 1), "sma20": r(sma20), "sma50": r(sma50),
        "sma200": r(sma200), "macd": r(macd[-1], 3), "macd_signal": r(sig[-1], 3), "macd_cross": cross,
        "hi52": hi, "lo52": lo, "pos52": r((last - lo) / (hi - lo) * 100, 0) if hi != lo else None,
        "vol_ratio": vol_ratio, "signals": signals,
    }


def ta_context(p: dict | None) -> str:
    ta = (p or {}).get("ta")
    if not ta:
        return ""
    return (f"trend {ta['trend']}, RSI {ta['rsi']}, 52h konum %{ta['pos52']}, "
            f"hacim/ort {ta['vol_ratio']}; " + "; ".join(ta["signals"][:3]))


# ------------------------------------------------------------------ indirme
def fetch(stock: Stock, yahoo: str | None = None) -> dict | None:
    import yfinance as yf
    try:
        tk = yf.Ticker(yahoo or stock.yahoo)
        intraday = _series(tk.history(period="5d", interval="5m", auto_adjust=False))
        daily = _series(tk.history(period="1y", interval="1d", auto_adjust=False))
        try:
            currency = tk.fast_info.get("currency")
        except Exception:
            currency = None
    except Exception as e:
        log.warning("%s fiyat alınamadı: %s", yahoo or stock.yahoo, e)
        return None
    if not daily and not intraday:
        return None
    last = (intraday or daily)[-1][1]
    prev = daily[-2][1] if len(daily) >= 2 else None
    return {
        "symbol": stock.symbol, "yahoo": yahoo or stock.yahoo, "market": stock.market,
        "currency": currency or ("TRY" if stock.market == "BIST" else "USD"),
        "last": last, "prev_close": prev,
        "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "ta": technicals(daily, live=bool(intraday) and now_utc().timestamp() - intraday[-1][0] < 20 * 60),
        # Panel için: gün içi 5 gün, günlük son ~6 ay yeter (dosya boyutu)
        "intraday": intraday, "daily": daily[-130:], "updated": iso(now_utc()),
    }


def _store(st: Stock, p: dict | None) -> dict | None:
    path = PRICE_DIR / f"{st.symbol}.json"
    if p is None and path.exists():          # bu tur başarısızsa eski veriyi koru
        p = json.loads(path.read_text())
        if p.get("demo"):                    # ...ama örnek fiyatı değil
            path.unlink()
            p = None
    if p is None:
        return None
    path.write_text(json.dumps(p, separators=(",", ":")))
    return p


def update_all(stocks: list[Stock]) -> dict[str, dict]:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for st in stocks:
        p = _store(st, fetch(st))
        if p:
            out[st.symbol] = p
    markets = {s.market for s in stocks}
    for m, idx in INDEXES.items():
        if m in markets:
            p = _store(idx, fetch(idx, INDEX_YAHOO[idx.symbol]))
            if p:
                out[idx.symbol] = p
    log.info("Fiyat: %d sembol güncellendi", len(out))
    return out


# ------------------------------------------------------------------ tepki
def reaction(published: str, price: dict, index: dict | None = None) -> dict | None:
    """Haber anındaki son fiyata göre sonraki ufuklardaki getiri (%).

    p0 = haberden önceki son fiyat. Ufuk h için: haber+h anındaki veya sonraki ilk bar.
    Seans dışı haberlerde p0 önceki kapanış olur; bu, gap dahil tepkiyi ölçer.
    Ek alanlar: `vol_x` haber günü hacmi / önceki 20 gün ortalaması,
    `index_since` aynı aralıkta endeksin getirisi, `excess` = since − index_since.
    """
    bars = price.get("intraday") or []
    daily = price.get("daily") or []
    ts = int(parse_iso(published).timestamp())
    series = bars if bars and bars[0][0] <= ts else daily
    if not series:
        return None
    times = [b[0] for b in series]
    i0 = bisect.bisect_right(times, ts) - 1
    if i0 < 0:
        return None
    p0 = series[i0][1]
    out: dict = {"base": p0, "base_time": series[i0][0]}
    for name, delta in HORIZONS.items():
        src = daily if name == "1d" and daily else series
        st = [b[0] for b in src]
        j = bisect.bisect_left(st, ts + int(delta.total_seconds()))
        out[name] = round((src[j][1] / p0 - 1) * 100, 2) if j < len(src) else None
    last = (bars or daily)[-1][1]
    out["since"] = round((last / p0 - 1) * 100, 2)
    out["n_after"] = len(series) - 1 - i0          # haberden sonra oluşan bar sayısı (0 = henüz işlem yok)

    # Hacim: haber günü ve ertesi işlem gününün büyüğü / haberden önceki 20 günün ortalaması.
    # (Günlük barlar gün başıyla damgalı; seans sonrası haberin tepkisi ertesi gün görülür.)
    dts = [b[0] for b in daily]
    k0 = bisect.bisect_right(dts, ts) - 1
    if k0 >= 20 and len(daily[k0]) > 2:
        prev = [b[2] for b in daily[k0 - 20:k0] if len(b) > 2]
        avg = sum(prev) / len(prev) if prev else 0
        if avg:
            vols = [daily[j][2] for j in (k0, k0 + 1) if j < len(daily) and len(daily[j]) > 2]
            out["vol_x"] = round(max(vols) / avg, 1)

    if index:
        ir = reaction(published, index)
        if ir and ir.get("since") is not None:
            out["index_since"] = ir["since"]
            out["excess"] = round(out["since"] - ir["since"], 2)
    return out
