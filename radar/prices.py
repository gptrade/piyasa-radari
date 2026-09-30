"""Fiyat verisi (Yahoo Finance üzerinden yfinance) ve haber sonrası fiyat tepkisi."""
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


def _series(df) -> list[list[float]]:
    if df is None or df.empty:
        return []
    col = df["Close"]
    if hasattr(col, "columns"):          # yfinance çoklu sütun döndürebilir
        col = col.iloc[:, 0]
    col = col.dropna()
    return [[int(ts.timestamp()), round(float(v), 4)] for ts, v in col.items()]


def fetch(stock: Stock) -> dict | None:
    import yfinance as yf
    try:
        tk = yf.Ticker(stock.yahoo)
        intraday = _series(tk.history(period="5d", interval="5m", auto_adjust=False))
        daily = _series(tk.history(period="6mo", interval="1d", auto_adjust=False))
        try:
            currency = tk.fast_info.get("currency")
        except Exception:
            currency = None
    except Exception as e:
        log.warning("%s fiyat alınamadı: %s", stock.yahoo, e)
        return None
    if not daily and not intraday:
        return None
    last = (intraday or daily)[-1][1]
    prev = daily[-2][1] if len(daily) >= 2 else None
    return {
        "symbol": stock.symbol, "yahoo": stock.yahoo, "market": stock.market,
        "currency": currency or ("TRY" if stock.market == "BIST" else "USD"),
        "last": last, "prev_close": prev,
        "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "intraday": intraday, "daily": daily, "updated": iso(now_utc()),
    }


def update_all(stocks: list[Stock]) -> dict[str, dict]:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for st in stocks:
        p = fetch(st)
        path = PRICE_DIR / f"{st.symbol}.json"
        if p is None and path.exists():          # bu tur başarısızsa eski veriyi koru
            p = json.loads(path.read_text())
            if p.get("demo"):                    # ...ama örnek fiyatı değil
                path.unlink()
                p = None
        if p is None:
            continue
        path.write_text(json.dumps(p, separators=(",", ":")))
        out[st.symbol] = p
    log.info("Fiyat: %d sembol güncellendi", len(out))
    return out


def reaction(published: str, price: dict) -> dict | None:
    """Haber anındaki son fiyata göre sonraki ufuklardaki getiri (%).

    p0 = haberden önceki son fiyat. Ufuk h için: haber+h anındaki veya sonraki ilk bar.
    Seans dışı haberlerde p0 önceki kapanış olur; bu, gap dahil tepkiyi ölçer.
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
    return out
