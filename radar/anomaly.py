"""Habersiz hareket: endekse göre arındırılmış olağandışı fiyat hareketi, ilgili önemli haber/bildirim yokken.

Bugünkü getiri r, endeks getirisi r_i, son 60 günde OLS ile beta → artık = r − beta·r_i.
Artık, son 60 günün artık oynaklığının `z` katını ve `min_move_pct`'yi aşarsa olağandışıdır.
Son `news_hours` saatte o hisseye ait KAP/SEC bildirimi ya da orta/yüksek önemli birinci/ikinci kademe haber
yoksa "habersiz" sayılır ve akışa kural tabanlı bir kayıt düşer (gün başına hisse ve yön için bir kez).
BIST küçük hisselerinde fiyat çoğu zaman bildirimden önce hareket eder; bu kayıt o boşluğu yakalar.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import prices
from .enrich import classify_event
from .models import Item, iso, make_id, now_utc, parse_iso

STRONG_EVENTS = {"legal", "measure", "regulator", "earnings", "deal", "buyback", "dividend", "insider", "analyst"}

EX_TZ = {"BIST": ZoneInfo("Europe/Istanbul"), "US": ZoneInfo("America/New_York")}


def _rets(daily: list, tz) -> dict:
    """tarih → günlük getiri (%), kapanıştan kapanışa."""
    out, prev = {}, None
    for b in daily:
        if prev:
            out[datetime.fromtimestamp(b[0], tz).date()] = (b[1] / prev - 1) * 100
        prev = b[1]
    return out


def stats(p: dict, idx: dict | None, lookback: int = 60) -> dict | None:
    """Bugünkü artık hareket ve z skoru. Bugün = fiyat dosyasındaki son günlük bar."""
    tz = EX_TZ.get(p.get("market"), EX_TZ["US"])
    daily = p.get("daily") or []
    if len(daily) < lookback // 2 + 2 or p.get("change_pct") is None:
        return None
    rs = _rets(daily, tz)
    today = datetime.fromtimestamp(daily[-1][0], tz).date()
    r = p["change_pct"]
    ri_all = _rets(idx.get("daily") or [], tz) if idx else {}
    ri = idx.get("change_pct") if idx else None
    hist = [d for d in sorted(rs) if d < today][-lookback:]
    pairs = [(rs[d], ri_all.get(d, 0.0)) for d in hist]
    if len(pairs) < lookback // 2:
        return None
    xs = [b for _, b in pairs]
    ys = [a for a, _ in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx > 1e-9 and idx else 0.0
    res = [y - beta * x for x, y in zip(xs, ys)]
    mr = sum(res) / len(res)
    sd = math.sqrt(sum((e - mr) ** 2 for e in res) / (len(res) - 1))
    if sd < 1e-6:
        return None
    resid = r - beta * (ri or 0.0)
    return {"date": today.isoformat(), "r": round(r, 2), "ri": round(ri, 2) if ri is not None else None,
            "beta": round(beta, 2), "resid": round(resid, 2), "sd": round(sd, 2), "z": round(resid / sd, 2)}


def explained(sym: str, recent: list[dict], hours: int = 24) -> tuple[bool, int]:
    """Son N saatte hareketi açıklayabilecek kayıt var mı? (var mı, düşük önemli kayıt sayısı)"""
    lo = iso(now_utc() - timedelta(hours=hours))
    weak = 0
    for d in recent:
        if sym not in (d.get("tickers") or []) or d.get("published", "") < lo:
            continue
        if d.get("source_type") == "technical":
            continue
        a = d.get("analysis") or {}
        if d.get("source_type") in ("disclosure", "regulator", "report"):
            return True, weak
        if (d.get("tier") or 3) <= 2 and a.get("materiality") in ("medium", "high"):
            return True, weak
        # Fiyatı oynatabilecek olay türleri, AI düşük önem dese de açıklama sayılır (soruşturma, tedbir, bilanço…)
        if d.get("source_type") != "social" and classify_event(d) in STRONG_EVENTS:
            return True, weak
        weak += 1
    return False, weak


def tr_pct(v: float, d: int = 2) -> str:
    """Panelle aynı biçim: +%6,14 · −%2,90"""
    sgn = "+" if v > 0 else "−" if v < 0 else ""
    return f"{sgn}%{abs(v):.{d}f}".replace(".", ",")


def tr_num(v: float, d: int = 1) -> str:
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def anomaly_items(stocks: list, px: dict, recent: list[dict], cfg: dict | None = None) -> list[Item]:
    cfg = cfg or {}
    zmin, mmin = float(cfg.get("z", 2.5)), float(cfg.get("min_move_pct", 2.0))
    out = []
    for st in stocks:
        p = px.get(st.symbol)
        if not p:
            continue
        idx = px.get(prices.INDEXES[st.market].symbol) if st.market in prices.INDEXES else None
        s = stats(p, idx, int(cfg.get("lookback_days", 60)))
        if not s or abs(s["z"]) < zmin or abs(s["resid"]) < mmin:
            continue
        ok, weak = explained(st.symbol, recent, int(cfg.get("news_hours", 24)))
        if ok:
            continue
        k = 1 if s["resid"] > 0 else -1
        up = "yükseliş" if k > 0 else "düşüş"
        idx_name = "BIST 100" if st.market == "BIST" else "S&P 500"
        title = f"{st.symbol}: habersiz {up} · {tr_pct(s['r'])} ({tr_num(abs(s['z']))}σ)"
        what = (f"Bugün {tr_pct(s['r'])}; {idx_name} {tr_pct(s['ri'] or 0)}, beta {tr_num(s['beta'], 2)} → endeksten "
                f"arındırılmış hareket {tr_pct(s['resid'])}, son 60 günün normal oynaklığının {tr_num(abs(s['z']))} katı")
        why = ("Son 24 saatte bu hisseye ait KAP/SEC bildirimi ya da önemli haber yok"
               + (f" ({weak} düşük önemli kayıt var)" if weak else "") +
               ". Habersiz sert hareket bazen bilginin fiyata bildirimden önce yansıdığını gösterir; KAP'ı izle.")
        out.append(Item(
            id=make_id("anom", st.symbol, s["date"], str(k)), source="Fiyat anomalisi", source_type="technical",
            market=st.market, title=title, summary=what, lang="tr", tickers=[st.symbol], published=iso(now_utc()),
            url=f"https://www.tradingview.com/chart/?symbol={st.tv}#habersiz-{s['date']}",
            extra={"no_ai": True, "anomaly": True, "z": s["z"], "resid": s["resid"], "beta": s["beta"], "bar": s["date"]},
            analysis={"sentiment": "bullish" if k > 0 else "bearish", "confidence": 60,
                      "materiality": "high" if abs(s["z"]) >= 4 else "medium", "horizon": "days",
                      "category": "Fiyat anomalisi", "event_label": "Habersiz hareket", "headline_tr": title,
                      "what": what, "why": why,
                      "risk": "Haber geç gelebilir ya da sektör/endeks dışı bir etken olabilir; tek günlük hareket tersine dönebilir.",
                      "summary": "", "affected_tickers": [st.symbol], "provider": "kural (anomali)"},
        ))
    return out
