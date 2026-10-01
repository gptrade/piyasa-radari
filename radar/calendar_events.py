"""Takvim / Katalizörler: önümüzdeki haftaların fiyatı oynatabilecek olayları (data/calendar.json).

- Makro ve merkez bankası: config/calendar.yml (TCMB PPK ve raporları, TÜİK TÜFE/GSYH, FOMC, ABD TÜFE)
- Vade sonları (hesaplanır): VİOP endeks vadeli (çift ayların son iş günü), ABD aylık opsiyon vadesi (3. cuma)
- Şirket: izleme listesindeki hisselerin bilanço ve temettü (hak kullanım / ödeme) tarihleri (Yahoo, fiyat dosyası)
Saatler İstanbul saatine çevrilir (ISO, saat dilimli).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yaml

from .config import DATA, ROOT
from .models import iso, now_utc

log = logging.getLogger("radar.calendar")

CAL_FILE = DATA / "calendar.json"
CONF = ROOT / "config" / "calendar.yml"
IST = ZoneInfo("Europe/Istanbul")
# Borsa İstanbul sabit resmi tatilleri (dini bayramlar yıla göre değişir; vade sonu çakışırsa BIST duyurusu esastır)
TR_FIXED = {(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)}
QUAD = {3, 6, 9, 12}


def _when(d: date, hhmm: str | None, tz: str) -> tuple[str, bool]:
    """Yerel tarih+saat → İstanbul saatiyle ISO; saat yoksa gün (tüm gün)."""
    if not hhmm:
        return d.isoformat(), False
    h, m = map(int, hhmm.split(":"))
    local = datetime.combine(d, time(h, m), tzinfo=ZoneInfo(tz))
    return local.astimezone(IST).isoformat(timespec="minutes"), True


def _ev(**k) -> dict:
    k.setdefault("importance", 2)
    k["id"] = "|".join(str(k.get(x, "")) for x in ("kind", "date", "ticker", "title"))
    return k


def macro_events(conf: dict) -> list[dict]:
    out = []
    for e in conf.get("events") or []:
        for raw in e.get("dates") or []:
            s = str(raw)
            star = s.endswith("*")
            d = date.fromisoformat(s.rstrip("*"))
            when, timed = _when(d, e.get("time"), e.get("tz", "Europe/Istanbul"))
            detail = "Ekonomik projeksiyonlu toplantı (nokta grafiği)" if star else e.get("detail", "")
            out.append(_ev(kind=e.get("kind", "macro"), date=d.isoformat(), when=when, timed=timed, market=e.get("market", "ALL"),
                           title=e["name"], detail=detail, importance=int(e.get("importance", 2)),
                           url=e.get("url", "")))
    return out


def _tr_business(d: date) -> bool:
    return d.weekday() < 5 and (d.month, d.day) not in TR_FIXED


def expiry_events(start: date, end: date) -> list[dict]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        if m % 2 == 0:                                       # VİOP endeks vadeli: çift ayların son iş günü
            d = nxt - timedelta(days=1)
            while not _tr_business(d):
                d -= timedelta(days=1)
            if (d.month, d.day) == (10, 28):                 # 29 Ekim arifesi yarım gün → bir önceki iş günü
                d -= timedelta(days=1)
            out.append(_ev(kind="expiry", date=d.isoformat(), when=_when(d, "17:40", "Europe/Istanbul")[0], timed=True,
                           market="BIST", title="VİOP endeks vadeli vade sonu",
                           detail="BIST 30 vadeli kontratlarında son işlem günü; kapanışa doğru oynaklık artabilir",
                           importance=2, url="https://www.borsaistanbul.com/tr/sayfa/2481/vadeli-islem-ve-opsiyon-piyasasi"))
        d = date(y, m, 1)
        d += timedelta(days=(4 - d.weekday()) % 7 + 14)      # ayın 3. cuması
        quad = m in QUAD
        out.append(_ev(kind="expiry", date=d.isoformat(), when=d.isoformat(), timed=False, market="US",
                       title="ABD dörtlü vade (quad witching)" if quad else "ABD aylık opsiyon vadesi",
                       detail="Hisse/endeks opsiyon ve vadelileri aynı gün sona erer; hacim ve oynaklık yüksek olur" if quad
                       else "Aylık hisse ve endeks opsiyonlarının vadesi (3. cuma)", importance=2 if quad else 1))
        y, m = nxt.year, nxt.month
    return [e for e in out if start.isoformat() <= e["date"] <= end.isoformat()]


def company_events(stocks: list, px: dict) -> list[dict]:
    out = []
    for st in stocks:
        p = px.get(st.symbol) or {}
        ne = p.get("next_earnings")
        if ne and ne.get("date"):
            est = []
            if ne.get("eps_est") is not None:
                est.append(f"EPS beklentisi {ne['eps_est']:.2f}".replace(".", ","))
            if ne.get("rev_est"):
                est.append(f"gelir beklentisi {ne['rev_est'] / 1e9:.2f} mr".replace(".", ","))
            out.append(_ev(kind="earnings", date=ne["date"], when=ne["date"], timed=False, market=st.market, ticker=st.symbol,
                           title=f"{st.symbol} bilanço", detail=" · ".join(est), importance=3,
                           url=f"https://finance.yahoo.com/quote/{st.yahoo}/"))
        nd = p.get("next_dividend") or {}
        if nd.get("ex"):
            out.append(_ev(kind="dividend", date=nd["ex"], when=nd["ex"], timed=False, market=st.market, ticker=st.symbol,
                           title=f"{st.symbol} temettü hak kullanım", importance=2,
                           detail="Bu tarihte ve sonrasında alınan payda bu temettü hakkı yoktur; fiyat temettü kadar düzeltilir"
                           + (f" · ödeme {nd['pay']}" if nd.get("pay") else ""),
                           url=f"https://finance.yahoo.com/quote/{st.yahoo}/"))
        elif nd.get("pay"):
            out.append(_ev(kind="dividend", date=nd["pay"], when=nd["pay"], timed=False, market=st.market, ticker=st.symbol,
                           title=f"{st.symbol} temettü ödemesi", detail="", importance=1,
                           url=f"https://finance.yahoo.com/quote/{st.yahoo}/"))
    return out


def build(stocks: list, px: dict, days_ahead: int = 60, days_back: int = 3, conf: dict | None = None) -> dict:
    if conf is None:
        conf = yaml.safe_load(CONF.read_text(encoding="utf-8")) if CONF.exists() else {}
    today = now_utc().astimezone(IST).date()
    lo, hi = today - timedelta(days=days_back), today + timedelta(days=days_ahead)
    evs = [e for e in macro_events(conf) + expiry_events(lo, hi) + company_events(stocks, px)
           if lo.isoformat() <= e["date"] <= hi.isoformat()]
    seen, uniq = set(), []
    for e in sorted(evs, key=lambda e: (e["when"], -e["importance"], e["title"])):
        if e["id"] not in seen:
            seen.add(e["id"])
            uniq.append(e)
    last = max((str(d).rstrip("*") for e in conf.get("events") or [] for d in e.get("dates") or []), default="")
    return {"generated": iso(now_utc()), "today": today.isoformat(), "range": [lo.isoformat(), hi.isoformat()],
            "macro_until": last, "events": uniq}


def update(stocks: list, px: dict) -> dict:
    cal = build(stocks, px)
    CAL_FILE.write_text(json.dumps(cal, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Takvim: %d olay", len(cal["events"]))
    return cal
