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


EMA_PERIODS = (14, 34, 55, 200)


def ema_tv(xs: list[float], n: int) -> list[float | None]:
    """TradingView ta.ema ile aynı: ilk n barın basit ortalamasıyla başlar, öncesi None."""
    if len(xs) < n:
        return [None] * len(xs)
    k = 2 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    e = sum(xs[:n]) / n
    out.append(e)
    for x in xs[n:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def _atr(daily: list[list[float]], n: int = 14) -> float | None:
    """Yalnız kapanış verisi var: gerçek aralık yerine kapanıştan kapanışa mutlak değişimin Wilder ortalaması."""
    closes = [b[1] for b in daily]
    if len(closes) <= n:
        return None
    tr = [abs(b - a) for a, b in zip(closes, closes[1:])]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def _weekly(daily: list[list[float]]) -> list[float]:
    """Günlük kapanışları haftalık kapanışa çevir (ISO hafta)."""
    from datetime import datetime, timezone
    weeks: dict[tuple, float] = {}
    for b in daily:
        d = datetime.fromtimestamp(b[0], tz=timezone.utc).isocalendar()
        weeks[(d[0], d[1])] = b[1]
    return [weeks[k] for k in sorted(weeks)]


def _cross(a: list, b: list, lookback: int = 5) -> str | None:
    """Son `lookback` barda a, b'yi yukarı ('up') ya da aşağı ('down') kesti mi?"""
    for k in range(1, min(lookback + 1, len(a))):
        a1, b1, a0, b0 = a[-k], b[-k], a[-k - 1], b[-k - 1]
        if None in (a1, b1, a0, b0):
            return None
        if a1 > b1 and a0 <= b0:
            return "up"
        if a1 < b1 and a0 >= b0:
            return "down"
    return None


def technicals(daily: list[list[float]], live: bool = False, periods=EMA_PERIODS) -> dict | None:
    """live=True: son günlük bar süren seansa ait (hacmi eksik); hacim oranı son tamamlanmış günden."""
    closes = [b[1] for b in daily]
    if len(closes) < 30:
        return None
    last = closes[-1]
    r = lambda x, d=2: round(x, d) if x is not None else None
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

    # ── EMA'lar (TradingView ile aynı hesap)
    emas = {n: ema_tv(closes, n) for n in periods}
    ema_last = {n: s[-1] for n, s in emas.items()}
    ema_info = {str(n): {"v": r(v), "dist": r((last / v - 1) * 100, 1) if v else None,
                         "above": (last > v) if v else None}
                for n, v in ema_last.items()}
    ps = sorted(periods)
    vals = [ema_last[n] for n in ps]
    if all(v is not None for v in vals) and last > vals[0] and all(a > b for a, b in zip(vals, vals[1:])):
        align = "boğa"          # fiyat > EMA14 > EMA34 > EMA55 > EMA200
    elif all(v is not None for v in vals) and last < vals[0] and all(a < b for a, b in zip(vals, vals[1:])):
        align = "ayı"
    else:
        align = "karışık"
    crosses = []
    def add_cross(a, b, name_up, name_down, lb=5):
        c = _cross(a, b, lb)
        if c:
            crosses.append(name_up if c == "up" else name_down)
    if 55 in emas and 200 in emas:
        add_cross(emas[55], emas[200], "EMA55, EMA200'ü yukarı kesti (altın kesişim)",
                  "EMA55, EMA200'ü aşağı kesti (ölüm kesişimi)", 10)
    if 14 in emas and 34 in emas:
        add_cross(emas[14], emas[34], "EMA14, EMA34'ü yukarı kesti", "EMA14, EMA34'ü aşağı kesti")
    for n in (55, 200):
        if n in emas:
            add_cross(closes, emas[n], f"Fiyat EMA{n} üstüne çıktı", f"Fiyat EMA{n} altına indi", 3)

    # ── oynaklık, bant, haftalık görünüm
    atr = _atr(daily)
    mid = sma20
    sd = (sum((c - mid) ** 2 for c in closes[-20:]) / 20) ** 0.5 if mid else None
    pct_b = ((last - (mid - 2 * sd)) / (4 * sd) * 100) if sd else None
    wk = _weekly(daily)
    w10, w30 = ema_tv(wk, 10), ema_tv(wk, 30)
    if w10[-1] and w30[-1]:
        wtrend = "yukarı" if wk[-1] > w10[-1] > w30[-1] else "aşağı" if wk[-1] < w10[-1] < w30[-1] else "yatay"
    else:
        wtrend = None
    hi20, lo20 = max(closes[-20:]), min(closes[-20:])

    if ema_last.get(55) and ema_last.get(200):
        trend = "yukarı" if last > ema_last[55] > ema_last[200] else "aşağı" if last < ema_last[55] < ema_last[200] else "yatay"
    elif sma20 and sma50:
        trend = "yukarı" if last > sma20 > sma50 else "aşağı" if last < sma20 < sma50 else "yatay"
    else:
        trend = "yatay"

    signals = list(crosses)
    if align != "karışık":
        signals.append(f"EMA dizilimi: {align} (fiyat ve 14/34/55/200 sıralı)")
    if rsi is not None and rsi >= 70:
        signals.append(f"RSI {rsi:.0f}: aşırı alım")
    elif rsi is not None and rsi <= 30:
        signals.append(f"RSI {rsi:.0f}: aşırı satım")
    if cross == "al":
        signals.append("MACD yukarı kesti")
    elif cross == "sat":
        signals.append("MACD aşağı kesti")
    if pct_b is not None and pct_b > 100:
        signals.append("Bollinger üst bandının üstünde")
    elif pct_b is not None and pct_b < 0:
        signals.append("Bollinger alt bandının altında")
    if hi != lo and (hi - last) / (hi - lo) < 0.03:
        signals.append("52 hafta zirvesine yakın")
    elif hi != lo and (last - lo) / (hi - lo) < 0.03:
        signals.append("52 hafta dibine yakın")
    if vol_ratio and vol_ratio >= 2:
        signals.append(f"Hacim ortalamanın {vol_ratio:.1f} katı")

    score = 0                                           # -5..+5 kaba teknik görünüm
    score += {"yukarı": 1, "aşağı": -1}.get(trend, 0)
    score += {"boğa": 1, "ayı": -1}.get(align, 0)
    score += {"yukarı": 1, "aşağı": -1}.get(wtrend, 0)
    score += 1 if macd[-1] > sig[-1] else -1
    if rsi is not None:
        score += 1 if 50 < rsi < 70 else -1 if 30 < rsi < 50 else 0
    view = "güçlü al" if score >= 4 else "al" if score >= 2 else "güçlü sat" if score <= -4 else "sat" if score <= -2 else "nötr"
    return {
        "trend": trend, "weekly_trend": wtrend, "score": score, "view": view,
        "ema": ema_info, "ema_align": align,
        "rsi": r(rsi, 1), "sma20": r(sma20), "sma50": r(sma50), "sma200": r(sma200),
        "macd": r(macd[-1], 3), "macd_signal": r(sig[-1], 3), "macd_hist": r(hist[-1], 3), "macd_cross": cross,
        "atr_pct": r(atr / last * 100, 2) if atr else None, "bb_pct": r(pct_b, 0),
        "hi20": hi20, "lo20": lo20, "hi52": hi, "lo52": lo,
        "pos52": r((last - lo) / (hi - lo) * 100, 0) if hi != lo else None,
        "vol_ratio": vol_ratio, "signals": signals,
    }


# ------------------------------------------------------------------ teknik olaylar
def tech_events(daily: list[list[float]], live: bool = False) -> list[dict]:
    """Son bara ait *yeni* teknik olaylar (önceki barda olmayan). Haber olmasa da akışa düşer.

    Her olay: key (aynı gün tekrar etmesin diye), dir (+1/−1/0), title, what, why, risk,
    materiality, confidence, bar (YYYY-AA-GG). Kesişimler son barla bir önceki bar karşılaştırılarak
    bulunur; seans sürerken son bar gün içi olduğundan olaya "gün içi" notu eklenir."""
    from datetime import datetime, timezone
    closes = [b[1] for b in daily]
    if len(closes) < 60:
        return []
    bar = datetime.fromtimestamp(daily[-1][0], tz=timezone.utc).strftime("%Y-%m-%d")
    note = " (gün içi, kapanışta değişebilir)" if live else ""
    ev = []

    def add(key, d, title, what, why, risk, mat="medium", conf=70, label=None):
        ev.append({"key": key, "dir": d, "title": title, "label": label or title, "what": what + note, "why": why, "risk": risk,
                   "materiality": mat, "confidence": conf, "bar": bar, "live": live})

    def crossed(a, b):                                   # +1 yukarı, −1 aşağı, 0 yok
        if None in (a[-1], a[-2], b[-1], b[-2]):
            return 0
        if a[-2] <= b[-2] and a[-1] > b[-1]:
            return 1
        if a[-2] >= b[-2] and a[-1] < b[-1]:
            return -1
        return 0

    e55, e200 = ema_tv(closes, 55), ema_tv(closes, 200)
    c = crossed(e55, e200)
    if c:
        add("x55_200", c, "Altın kesişim: EMA55, EMA200'ü yukarı kesti" if c > 0 else "Ölüm kesişimi: EMA55, EMA200'ü aşağı kesti",
            "Orta vadeli ortalama uzun vadeliyi " + ("yukarı" if c > 0 else "aşağı") + " kesti",
            "Uzun vadeli trend dönüşü sinyali olarak izlenir", "Gecikmeli bir göstergedir; yatay piyasada yanıltabilir", "high", 80,
            "Altın kesişim" if c > 0 else "Ölüm kesişimi")
    for n, e, conf in ((200, e200, 75), (55, e55, 70)):
        c = crossed(closes, e)
        if c:
            add(f"p{n}", c, f"Fiyat EMA{n} {'üstüne çıktı' if c > 0 else 'altına indi'}",
                f"Kapanış EMA{n} ({e[-1]:.2f}) {'üstüne çıktı' if c > 0 else 'altına indi'}",
                ("Uzun" if n == 200 else "Orta") + " vadeli trend desteği/direnci kırıldı",
                "Tek günlük kırılım; teyit için birkaç kapanış beklenir", "medium", conf, f"EMA{n} kırılımı")
    r_now, r_prev = _rsi(closes), _rsi(closes[:-1])
    if r_now is not None and r_prev is not None:
        if r_prev < 70 <= r_now:
            add("rsi", 0, f"RSI {r_now:.0f}: aşırı alım bölgesine girdi", f"RSI 14, 70'in üstüne çıktı ({r_prev:.0f} → {r_now:.0f})",
                "Güçlü yükselişin ardından düzeltme riski artar", "Güçlü trendlerde RSI uzun süre 70 üstünde kalabilir", label="RSI aşırı alım")
        elif r_prev > 30 >= r_now:
            add("rsi", 0, f"RSI {r_now:.0f}: aşırı satım bölgesine indi", f"RSI 14, 30'un altına indi ({r_prev:.0f} → {r_now:.0f})",
                "Sert düşüşün ardından tepki yükselişi olasılığı artar", "Düşüş trendinde RSI uzun süre 30 altında kalabilir", label="RSI aşırı satım")
        elif r_prev >= 70 > r_now:
            add("rsi", -1, f"RSI {r_now:.0f}: aşırı alımdan çıktı", f"RSI 14, 70'in altına döndü ({r_prev:.0f} → {r_now:.0f})",
                "Yükseliş ivmesi zayıflıyor olabilir", "Kısa süreli soluklanma da olabilir", label="RSI aşırı alımdan çıkış")
        elif r_prev <= 30 < r_now:
            add("rsi", 1, f"RSI {r_now:.0f}: aşırı satımdan çıktı", f"RSI 14, 30'un üstüne döndü ({r_prev:.0f} → {r_now:.0f})",
                "Satış baskısı azalıyor olabilir", "Düşüş trendi sürebilir", label="RSI aşırı satımdan çıkış")
    if len(closes) >= 254:
        hi_prev, lo_prev = max(closes[-253:-1]), min(closes[-253:-1])
        hi_prev2, lo_prev2 = max(closes[-254:-2]), min(closes[-254:-2])
        if closes[-1] > hi_prev and closes[-2] <= hi_prev2:
            add("h52", 1, "52 haftanın en yüksek kapanışı", f"Fiyat ({closes[-1]:.2f}) son bir yılın zirvesini ({hi_prev:.2f}) aştı",
                "Zirve kırılımı güçlü talebe işaret eder", "Kırılım başarısız olursa geri çekilme görülebilir", "medium", 72, "52 hafta zirvesi")
        elif closes[-1] < lo_prev and closes[-2] >= lo_prev2:
            add("l52", -1, "52 haftanın en düşük kapanışı", f"Fiyat ({closes[-1]:.2f}) son bir yılın dibinin ({lo_prev:.2f}) altına indi",
                "Destek kırılımı satış baskısına işaret eder", "Aşırı satımdan tepki gelebilir", "medium", 72, "52 hafta dibi")
    vols = [(b[0], b[1], b[2]) for b in daily if len(b) > 2 and b[2]]
    if live and len(vols) > 1:
        vols = vols[:-1]                                  # süren seansın hacmi eksik: son tamamlanmış gün
    if len(vols) >= 22:
        avg = sum(v[2] for v in vols[-21:-1]) / 20
        if avg and vols[-1][2] >= 3 * avg:
            chg = (vols[-1][1] / vols[-2][1] - 1) * 100
            d = 1 if chg > 0.3 else -1 if chg < -0.3 else 0
            vbar = datetime.fromtimestamp(vols[-1][0], tz=timezone.utc).strftime("%Y-%m-%d")
            ev.append({"key": "vol", "dir": d, "label": "Hacim patlaması", "title": f"Hacim patlaması: ortalamanın {vols[-1][2] / avg:.1f} katı",
                       "what": f"{vbar[8:10]}.{vbar[5:7]} işlem hacmi 20 günlük ortalamanın {vols[-1][2] / avg:.1f} katı, fiyat %{chg:+.1f}",
                       "why": "Olağandışı hacim, kurumsal alım/satım ya da habere işaret edebilir",
                       "risk": "Endeks değişikliği, blok satış gibi tek seferlik nedenler olabilir",
                       "materiality": "medium", "confidence": 65, "bar": vbar, "live": False})
    return ev


def ta_context(p: dict | None) -> str:
    ta = (p or {}).get("ta")
    if not ta:
        return ""
    em = ", ".join(f"EMA{k} %{v['dist']:+.1f}" for k, v in (ta.get("ema") or {}).items() if v.get("dist") is not None)
    return (f"günlük trend {ta['trend']}, haftalık {ta.get('weekly_trend')}, görünüm {ta.get('view')}, "
            f"EMA dizilimi {ta.get('ema_align')} ({em}), RSI {ta['rsi']}, 52h konum %{ta['pos52']}, "
            f"hacim/ort {ta['vol_ratio']}; " + "; ".join(ta["signals"][:4]))


# ------------------------------------------------------------------ indirme
def _next_dividend(cal) -> dict | None:
    """Yahoo takviminden yaklaşan hak kullanım (ex-dividend) ve ödeme tarihi (geçmişse None)."""
    if not isinstance(cal, dict):
        return None
    today = now_utc().date()
    ex, pay = cal.get("Ex-Dividend Date"), cal.get("Dividend Date")
    ex = ex if hasattr(ex, "isoformat") and ex >= today else None
    pay = pay if hasattr(pay, "isoformat") and pay >= today else None
    if not ex and not pay:
        return None
    return {"ex": ex.isoformat() if ex else None, "pay": pay.isoformat() if pay else None}


def _next_earnings(tk, cal=None) -> dict | None:
    """Yahoo takviminden bir sonraki bilanço tarihi ve beklentiler (yoksa None)."""
    if cal is None:
        try:
            cal = tk.calendar
        except Exception:
            return None
    if not isinstance(cal, dict):
        return None
    dates = cal.get("Earnings Date") or []
    if not isinstance(dates, (list, tuple)):
        dates = [dates]
    today = now_utc().date()
    fut = sorted(d for d in dates if hasattr(d, "isoformat") and d >= today)
    if not fut:
        return None
    num = lambda v: round(float(v), 4) if isinstance(v, (int, float)) and v == v else None
    return {"date": fut[0].isoformat(), "eps_est": num(cal.get("Earnings Average")),
            "rev_est": num(cal.get("Revenue Average"))}


ACTION_TR = {"up": "yükseltti", "down": "düşürdü", "init": "kapsama aldı", "main": "korudu", "reit": "yineledi"}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if f == f and f != 0 else None


def analyst_data(tk, max_changes: int = 12) -> dict | None:
    """Yahoo analist verisi: hedef fiyatlar, tavsiye dağılımı, son not değişiklikleri (yoksa None)."""
    out: dict = {"updated": iso(now_utc())}
    try:
        t = tk.analyst_price_targets or {}
        tg = {k: _num(t.get(k)) for k in ("mean", "median", "high", "low")}
        if any(tg.values()):
            out["targets"] = tg
    except Exception:
        pass
    try:
        rec = tk.recommendations
        if rec is not None and len(rec):
            row = rec.iloc[0]
            dist = {k: int(row.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
            if sum(dist.values()):
                out["rec"] = dist
    except Exception:
        pass
    try:
        ud = tk.upgrades_downgrades
        if ud is not None and len(ud):
            ch = []
            for ts, r in ud.sort_index(ascending=False).head(max_changes).iterrows():
                d = ts.date().isoformat() if hasattr(ts, "date") else str(ts)[:10]
                ch.append({"date": d, "firm": str(r.get("Firm") or ""), "to": str(r.get("ToGrade") or ""),
                           "from": str(r.get("FromGrade") or ""), "action": str(r.get("Action") or ""),
                           "pt": _num(r.get("currentPriceTarget")), "pt_prev": _num(r.get("priorPriceTarget"))})
            out["changes"] = ch
    except Exception:
        pass
    return out if len(out) > 1 else None


VAL_FIELDS = {   # panel adı → Yahoo alanı
    "pe": "trailingPE", "fpe": "forwardPE", "pb": "priceToBook", "ps": "priceToSalesTrailing12Months",
    "ev_ebitda": "enterpriseToEbitda", "peg": "trailingPegRatio", "dy": "dividendYield", "mcap": "marketCap",
    "ev": "enterpriseValue", "roe": "returnOnEquity", "margin": "profitMargins", "de": "debtToEquity",
    "rev_g": "revenueGrowth", "eps_g": "earningsGrowth", "beta": "beta", "eps": "trailingEps", "feps": "forwardEps",
}
PRICE_BASED = ("pe", "fpe", "pb", "ps", "ev_ebitda", "peg", "ev")


def valuation_data(tk, currency: str | None = None) -> dict | None:
    """Yahoo değerleme çarpanları ve kârlılık. Finansal tablo para birimi fiyatınkinden farklıysa (ör. THYAO:
    TL fiyat, USD bilanço) Yahoo'nun fiyat tabanlı çarpanları tutarsız olur: `fx_mismatch` işaretlenir ve
    o çarpanlar yazılmaz (oranlar — özsermaye kârlılığı, marj, büyüme — para biriminden bağımsızdır)."""
    try:
        info = tk.info or {}
    except Exception:
        return None
    out: dict = {"updated": iso(now_utc())}
    for k, src in VAL_FIELDS.items():
        v = info.get(src)
        if k == "peg" and v is None:
            v = info.get("pegRatio")
        v = _num(v)
        if v is not None:
            out[k] = v
    fin, ccy = info.get("financialCurrency"), info.get("currency") or currency
    mismatch = bool(fin and ccy and fin != ccy)
    # Zarar: F/K anlamsız. Kur uyumsuzluğunda ya da marj pozitifken eksi EPS tutarsız veridir, zarar sayılmaz.
    if out.get("eps") is not None and out["eps"] < 0 and not mismatch and (out.get("margin") is None or out["margin"] < 0):
        out.pop("pe", None)
        out["loss"] = True
    for k in ("sector", "industry"):
        if info.get(k):
            out[k] = str(info[k])
    if fin:
        out["fin_ccy"] = fin
    if mismatch:
        out["fx_mismatch"] = True
        for k in PRICE_BASED + ("eps", "feps", "dy"):
            out.pop(k, None)
    return out if len(out) > 2 else None


def fetch(stock: Stock, yahoo: str | None = None, analyst: bool = False, valuation: bool = False) -> dict | None:
    import yfinance as yf
    try:
        tk = yf.Ticker(yahoo or stock.yahoo)
        intraday = _series(tk.history(period="5d", interval="5m", auto_adjust=False))
        daily = _series(tk.history(period="5y", interval="1d", auto_adjust=False))   # EMA200 yakınsaması için uzun geçmiş
        try:
            currency = tk.fast_info.get("currency")
        except Exception:
            currency = None
        try:
            cal = tk.calendar
        except Exception:
            cal = None
        next_earnings = _next_earnings(tk, cal) if cal is not None else None
        next_dividend = _next_dividend(cal)
        an = analyst_data(tk) if analyst else None
        val = valuation_data(tk, currency) if valuation else None
    except Exception as e:
        log.warning("%s fiyat alınamadı: %s", yahoo or stock.yahoo, e)
        return None
    if not daily and not intraday:
        return None
    last = (intraday or daily)[-1][1]
    prev = daily[-2][1] if len(daily) >= 2 else None
    keep = 130                                            # panelde ~6 aylık günlük grafik
    closes = [b[1] for b in daily]
    ema_overlay = {str(n): [round(v, 4) if v is not None else None for v in ema_tv(closes, n)[-keep:]]
                   for n in EMA_PERIODS}
    return {
        "symbol": stock.symbol, "yahoo": yahoo or stock.yahoo, "market": stock.market,
        "currency": currency or ("TRY" if stock.market == "BIST" else "USD"),
        "last": last, "prev_close": prev,
        "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "ta": technicals(daily, live=(live := bool(intraday) and now_utc().timestamp() - intraday[-1][0] < 20 * 60)),
        "events": tech_events(daily, live=live),
        # Panel için: gün içi 5 gün, günlük son ~6 ay yeter (dosya boyutu)
        "intraday": intraday, "daily": daily[-keep:], "ema": ema_overlay, "updated": iso(now_utc()),
        "next_earnings": next_earnings,
        **({"next_dividend": next_dividend} if next_dividend else {}),
        **({"analyst": an} if an else {}),
        **({"valuation": val} if val else {}),
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


def _old(st: Stock, key: str) -> dict | None:
    path = PRICE_DIR / f"{st.symbol}.json"
    try:
        return json.loads(path.read_text()).get(key) if path.exists() else None
    except Exception:
        return None


def _old_analyst(st: Stock) -> dict | None:
    return _old(st, "analyst")


def _due(old: dict | None, hours: float | None) -> bool:
    return hours is not None and (not old or now_utc() - parse_iso(old["updated"]) > timedelta(hours=hours))


def update_all(stocks: list[Stock], analyst_hours: float | None = 6, valuation_hours: float | None = 24) -> dict[str, dict]:
    """analyst_hours / valuation_hours: analist verisi ve değerleme çarpanları bu kadar saatte bir yenilenir
    (None → hiç alınmaz)."""
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for st in stocks:
        old = _old(st, "analyst") if analyst_hours is not None else None
        oldv = _old(st, "valuation") if valuation_hours is not None else None
        p = fetch(st, analyst=_due(old, analyst_hours), valuation=_due(oldv, valuation_hours))
        if p is not None and analyst_hours is not None and "analyst" not in p and old:
            p["analyst"] = old                       # bu tur yenilenmediyse eskisini taşı
        if p is not None and valuation_hours is not None and "valuation" not in p and oldv:
            p["valuation"] = oldv
        p = _store(st, p)
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
