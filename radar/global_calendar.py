"""Küresel takvim: ABD ve Avrupa bilançoları, ECB faiz kararları, Euro Bölgesi verileri.

Kaynaklar (günde bir kez çekilir, önbellek DATA/global_calendar.json; çekilemezse önbellek kullanılır):
- ABD bilançoları: Alpha Vantage EARNINGS_CALENDAR (resmi API, 3 ay ileri, tarih + seans + EPS beklentisi).
  Yalnız S&P 500 (config/sp500.csv) ve izleme listesi tutulur; en büyük ~35 şirket yüksek önemli.
- Avrupa bilançoları: Yahoo (yfinance) takvimi, seçili büyük şirketler (EU_COMPANIES).
- ECB: ecb.europa.eu toplantı takvimi (robots.txt izinli); para politikası toplantısının 2. günü karar günü.
- Euro Bölgesi: Eurostat "Euro indicators" yayın takvimi (sitenin kendi takvim JSON'u; robots.txt izinli).
Hepsine bölge etiketi eklenir: US / EU.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import time as _time
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from . import http
from .config import DATA, ROOT
from .models import iso, now_utc

log = logging.getLogger("radar.globalcal")

CACHE = DATA / "global_calendar.json"
SP500 = ROOT / "config" / "sp500.csv"
IST = ZoneInfo("Europe/Istanbul")
NY = ZoneInfo("America/New_York")
CET = ZoneInfo("Europe/Brussels")
AV_URL = "https://www.alphavantage.co/query"
ECB_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
EUROSTAT_PAGE = "https://ec.europa.eu/eurostat/news/release-calendar"
EUROSTAT_JSON = "https://ec.europa.eu/eurostat/o/calendars/eventsJson"
REFRESH_H = 20
RETRY_H = 2

US_MEGA = {"AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "TSLA", "BRK.B", "JPM", "LLY", "V", "MA",
           "WMT", "XOM", "UNH", "ORCL", "COST", "NFLX", "HD", "PG", "JNJ", "ABBV", "BAC", "KO", "CRM", "AMD", "PLTR",
           "CVX", "MRK", "WFC", "CSCO", "IBM", "GS", "MS", "INTC", "QCOM", "TXN", "CAT"}

# (Yahoo kodu, ad, ülke, büyük mü)
EU_COMPANIES: list[tuple[str, str, str, bool]] = [
    ("ASML.AS", "ASML", "NL", True), ("SAP.DE", "SAP", "DE", True), ("MC.PA", "LVMH", "FR", True),
    ("NOVO-B.CO", "Novo Nordisk", "DK", True), ("NESN.SW", "Nestlé", "CH", True),
    ("NOVN.SW", "Novartis", "CH", True), ("SHEL.L", "Shell", "GB", True), ("AZN.L", "AstraZeneca", "GB", True),
    ("HSBA.L", "HSBC", "GB", True), ("SIE.DE", "Siemens", "DE", True), ("TTE.PA", "TotalEnergies", "FR", True),
    ("OR.PA", "L'Oréal", "FR", False), ("SAN.PA", "Sanofi", "FR", False), ("ALV.DE", "Allianz", "DE", False),
    ("RMS.PA", "Hermès", "FR", False), ("AIR.PA", "Airbus", "FR", False), ("SU.PA", "Schneider Electric", "FR", False),
    ("DTE.DE", "Deutsche Telekom", "DE", False), ("IBE.MC", "Iberdrola", "ES", False), ("SAN.MC", "Banco Santander", "ES", False),
    ("BNP.PA", "BNP Paribas", "FR", False), ("ENEL.MI", "Enel", "IT", False), ("ISP.MI", "Intesa Sanpaolo", "IT", False),
    ("UCG.MI", "UniCredit", "IT", False), ("INGA.AS", "ING", "NL", False), ("ABI.BR", "AB InBev", "BE", False),
    ("MUV2.DE", "Munich Re", "DE", False), ("DB1.DE", "Deutsche Börse", "DE", False), ("SAF.PA", "Safran", "FR", False),
    ("EL.PA", "EssilorLuxottica", "FR", False), ("CS.PA", "AXA", "FR", False), ("BBVA.MC", "BBVA", "ES", False),
    ("ITX.MC", "Inditex", "ES", False), ("ADYEN.AS", "Adyen", "NL", False), ("PRX.AS", "Prosus", "NL", False),
    ("BAS.DE", "BASF", "DE", False), ("BAYN.DE", "Bayer", "DE", False), ("BMW.DE", "BMW", "DE", False),
    ("MBG.DE", "Mercedes-Benz", "DE", False), ("VOW3.DE", "Volkswagen", "DE", False), ("IFX.DE", "Infineon", "DE", False),
    ("ADS.DE", "Adidas", "DE", False), ("DHL.DE", "DHL", "DE", False), ("ENI.MI", "Eni", "IT", False),
    ("STLAM.MI", "Stellantis", "IT", False), ("RACE.MI", "Ferrari", "IT", False), ("NOKIA.HE", "Nokia", "FI", False),
    ("KER.PA", "Kering", "FR", False), ("DG.PA", "Vinci", "FR", False), ("AI.PA", "Air Liquide", "FR", False),
    ("BN.PA", "Danone", "FR", False), ("RI.PA", "Pernod Ricard", "FR", False), ("WKL.AS", "Wolters Kluwer", "NL", False),
    ("AD.AS", "Ahold Delhaize", "NL", False), ("HEIA.AS", "Heineken", "NL", False), ("ULVR.L", "Unilever", "GB", False),
    ("BP.L", "BP", "GB", False), ("GSK.L", "GSK", "GB", False), ("RIO.L", "Rio Tinto", "GB", False),
    ("BATS.L", "British American Tobacco", "GB", False), ("LSEG.L", "LSEG", "GB", False), ("BARC.L", "Barclays", "GB", False),
    ("LLOY.L", "Lloyds", "GB", False), ("REL.L", "RELX", "GB", False), ("DGE.L", "Diageo", "GB", False),
    ("GLEN.L", "Glencore", "GB", False), ("VOD.L", "Vodafone", "GB", False), ("UBSG.SW", "UBS", "CH", False),
    ("ZURN.SW", "Zurich Insurance", "CH", False), ("ABBN.SW", "ABB", "CH", False), ("CFR.SW", "Richemont", "CH", False),
    ("MAERSK-B.CO", "Maersk", "DK", False), ("ERIC-B.ST", "Ericsson", "SE", False), ("VOLV-B.ST", "Volvo", "SE", False),
    ("ATCO-A.ST", "Atlas Copco", "SE", False), ("EQNR.OL", "Equinor", "NO", False),
]

# Eurostat başlığı → (kısa ad, önem, etkilediği varlıklar)
EUROSTAT_RULES: list[tuple[str, str, int, list[str]]] = [
    (r"^Flash estimate inflation", "Euro Bölgesi enflasyon (öncü)", 3, ["ECB faiz beklentisi", "EUR/USD", "Avrupa hisseleri"]),
    (r"^Inflation \(HICP\)", "Euro Bölgesi enflasyon (kesin)", 2, ["ECB faiz beklentisi", "EUR/USD"]),
    (r"^Preliminary flash estimate GDP", "Euro Bölgesi GSYH (öncü)", 3, ["EUR/USD", "Avrupa hisseleri"]),
    (r"^Flash estimate GDP and employment", "Euro Bölgesi GSYH ve istihdam", 2, ["EUR/USD", "Avrupa hisseleri"]),
    (r"^GDP main aggregates", "Euro Bölgesi GSYH (ayrıntılı)", 1, ["Avrupa hisseleri"]),
    (r"^Unemployment", "Euro Bölgesi işsizlik", 2, ["ECB faiz beklentisi", "EUR/USD"]),
    (r"^Economic Sentiment", "AB ekonomik güven endeksi", 2, ["Avrupa hisseleri"]),
    (r"^Industrial production", "Euro Bölgesi sanayi üretimi", 1, ["Avrupa sanayi hisseleri"]),
    (r"^Retail trade", "Euro Bölgesi perakende satışlar", 1, ["Avrupa tüketici hisseleri"]),
    (r"^Industrial producer prices", "Euro Bölgesi ÜFE", 1, ["ECB faiz beklentisi"]),
    (r"^International trade in goods", "Euro Bölgesi dış ticaret", 1, ["EUR/USD"]),
    (r"^Labour cost index", "Euro Bölgesi işgücü maliyeti", 1, ["ECB faiz beklentisi"]),
]
_ER = [(re.compile(p, re.I), *rest) for p, *rest in EUROSTAT_RULES]


def _ev(**k) -> dict:
    k.setdefault("importance", 1)
    k["id"] = "|".join(str(k.get(x, "")) for x in ("kind", "date", "ticker", "title"))
    return k


def load_sp500() -> dict[str, dict]:
    out = {}
    if SP500.exists():
        lines = [ln for ln in SP500.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
        for r in csv.DictReader(lines):
            out[r["symbol"].replace("-", ".").upper()] = {"name": r["name"], "sector": r["sector"]}
    return out


def _norm(sym: str) -> str:
    return sym.replace("-", ".").upper()


# ------------------------------------------------------------------ ABD (Alpha Vantage)
def parse_av(text: str, keep: set[str]) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        sym = _norm(r.get("symbol") or "")
        if not sym or sym not in keep or not r.get("reportDate"):
            continue
        est = r.get("estimate") or ""
        try:
            est = round(float(est), 4)
        except ValueError:
            est = None
        tod = (r.get("timeOfTheDay") or "").strip()
        rows.append({"s": sym, "n": (r.get("name") or "").strip(), "d": r["reportDate"],
                     "t": "bmo" if tod.startswith("pre") else "amc" if tod.startswith("post") else "",
                     "e": est, "fy": r.get("fiscalDateEnding") or ""})
    return rows


def fetch_us(watch: set[str]) -> list[dict] | None:
    key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        return None
    r = http.get(AV_URL, params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": key}, timeout=90)
    if r is None or "reportDate" not in r.text[:200]:
        log.warning("Alpha Vantage kazanç takvimi alınamadı")
        return None
    return parse_av(r.text, set(load_sp500()) | watch)


# ------------------------------------------------------------------ Avrupa (Yahoo)
def fetch_eu() -> list[dict] | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    from .prices import _next_earnings
    out, ok = [], 0
    for sym, name, cc, big in EU_COMPANIES:
        try:
            ne = _next_earnings(yf.Ticker(sym))
            ok += 1
        except Exception:
            ne = None
        if ne:
            out.append({"s": sym, "n": name, "c": cc, "big": big, "d": ne["date"], "e": ne.get("eps_est")})
        elif ok >= 10 and not out:                          # ilk 10'dan hiç tarih yok: Yahoo kısıtlıyor, sonra dene
            log.warning("Avrupa bilançoları: Yahoo yanıt vermiyor, %d saat sonra yeniden denenecek", RETRY_H)
            return None
        _time.sleep(0.4)
    return out or None                  # hiç tarih gelmediyse (Yahoo kısıtlaması) başarısız say


# ------------------------------------------------------------------ ECB
def parse_ecb(html: str) -> list[str]:
    """Para politikası toplantılarının karar günleri (2. gün) — ISO tarih listesi."""
    out = []
    for d, txt in re.findall(r"<dt>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd>(.*?)</dd>", html, re.S):
        t = re.sub(r"<[^>]+>", " ", txt)
        if re.search(r"monetary policy meeting", t, re.I) and not re.search(r"non-monetary", t, re.I) \
                and re.search(r"Day 2|press conference", t, re.I):
            dd, mm, yy = d.split("/")
            out.append(f"{yy}-{mm}-{dd}")
    return sorted(set(out))


def fetch_ecb() -> list[str] | None:
    r = http.get(ECB_URL, timeout=60)
    if r is None:
        return None
    dates = parse_ecb(r.text)
    return dates or None


# ------------------------------------------------------------------ Eurostat
EN_TR = {"January": "Ocak", "February": "Şubat", "March": "Mart", "April": "Nisan", "May": "Mayıs", "June": "Haziran",
         "July": "Temmuz", "August": "Ağustos", "September": "Eylül", "October": "Ekim", "November": "Kasım", "December": "Aralık"}


def tr_period(p: str) -> str:
    m = re.fullmatch(r"Q([1-4])/(\d{4})", (p or "").strip())
    if m:
        return f"{m.group(1)}. çeyrek {m.group(2)}"
    return " ".join(EN_TR.get(w, w) for w in (p or "").split())


def parse_eurostat(items: list[dict]) -> list[dict]:
    out = []
    for x in items:
        title = (x.get("title") or "").strip()
        m = next(((short, imp, assets) for rx, short, imp, assets in _ER if rx.search(title)), None)
        if not m or not x.get("start"):
            continue
        out.append({"title": title, "short": m[0], "imp": m[1], "assets": m[2], "d": x["start"][:10],
                    "hm": x["start"][11:16] or "11:00", "period": tr_period(x.get("period") or "")})
    return out


def fetch_eurostat(lo: date, hi: date) -> list[dict] | None:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (piyasa-radari takvim; github.com/gptrade/piyasa-radari)", "Accept-Language": "en"})
    try:
        s.get(EUROSTAT_PAGE, timeout=60)
        r = s.get(EUROSTAT_JSON, timeout=60, headers={"X-Requested-With": "XMLHttpRequest", "Referer": EUROSTAT_PAGE,
                                                      "Accept": "application/json, text/javascript, */*; q=0.01"},
                  params={"start": f"{lo}T00:00:00+00:00", "end": f"{hi}T00:00:00+00:00", "theme": "", "category": "",
                          "keywords": "", "isEuroindicator": "true", "authorInclude": "", "authorExclude": ""})
        if r.status_code != 200 or not r.content:
            log.warning("Eurostat takvimi boş döndü (HTTP %s)", r.status_code)
            return None
        return parse_eurostat(r.json())
    except (requests.RequestException, ValueError) as e:
        log.warning("Eurostat takvimi alınamadı: %s", e)
        return None


# ------------------------------------------------------------------ önbellek + olaylar
def refresh(watch_us: set[str], force: bool = False) -> tuple[dict, dict]:
    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    now = now_utc()
    status = {}
    today = now.astimezone(IST).date()
    jobs = {"us": lambda: fetch_us(watch_us), "eu": fetch_eu, "ecb": fetch_ecb,
            "eurostat": lambda: fetch_eurostat(today - timedelta(days=14), today + timedelta(days=75))}
    changed = False
    for k, fn in jobs.items():
        part = cache.get(k) or {}
        at, fail = part.get("at"), part.get("fail_at")
        age = lambda t: now - datetime.fromisoformat(t.replace("Z", "+00:00"))  # noqa: E731
        if not force and at and part.get("rows") and age(at) < timedelta(hours=REFRESH_H):
            status[k] = {"ok": True, "n": len(part["rows"]), "cached": True}
            continue
        if not force and fail and age(fail) < timedelta(hours=RETRY_H):      # başarısız denemeden sonra bekle
            status[k] = {"ok": bool(part.get("rows")), "n": len(part.get("rows") or []), "cached": True, "error": "alınamadı, yeniden denenecek"}
            continue
        try:
            rows = fn()
        except Exception as e:  # noqa: BLE001
            log.warning("Küresel takvim (%s) hatası: %s", k, e)
            rows = None
        if rows is None:
            cache[k] = {**part, "fail_at": iso(now)}
            changed = True
            status[k] = {"ok": bool(part.get("rows")), "n": len(part.get("rows") or []), "cached": True, "error": "alınamadı"}
            continue
        cache[k] = {"at": iso(now), "rows": rows}
        status[k] = {"ok": True, "n": len(rows), "cached": False}
        changed = True
    if changed:
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return cache, status


def _at(d: str, hm: str, tz: ZoneInfo) -> str:
    h, m = map(int, hm.split(":"))
    return datetime.combine(date.fromisoformat(d), time(h, m), tzinfo=tz).astimezone(IST).isoformat(timespec="minutes")


SESSION = {"bmo": "ABD seans açılışı öncesi", "amc": "ABD seans kapanışı sonrası"}


def events(cache: dict, lo: str, hi: str, watch_us: set[str]) -> list[dict]:
    sp = load_sp500()
    out = []
    for r in (cache.get("us") or {}).get("rows") or []:
        if not (lo <= r["d"] <= hi):
            continue
        sym = r["s"]
        mega, mine = sym in US_MEGA, sym in watch_us
        info = sp.get(sym, {})
        name = info.get("name") or r.get("n") or sym
        det = [x for x in [SESSION.get(r.get("t")), f"EPS beklentisi {r['e']:.2f} $".replace(".", ",") if r.get("e") is not None else None,
                           info.get("sector")] if x]
        out.append(_ev(kind="earnings", date=r["d"], when=r["d"], timed=False, market="US", region="US", ticker=sym,
                       title=f"{sym} bilanço", name=name, session=r.get("t") or "", eps_est=r.get("e"),
                       detail=" · ".join(det), importance=3 if (mega or mine) else 1, src="av",
                       group="S&P 500" if sym in sp else "İzleme listesi",
                       url=f"https://finance.yahoo.com/quote/{sym.replace('.', '-')}/"))
    for r in (cache.get("eu") or {}).get("rows") or []:
        if not (lo <= r["d"] <= hi):
            continue
        det = [x for x in [f"EPS beklentisi {r['e']:.2f}".replace(".", ",") if r.get("e") is not None else None,
                           "tarih Yahoo'dan; şirket teyidi için yatırımcı ilişkileri sayfası"] if x]
        out.append(_ev(kind="earnings", date=r["d"], when=r["d"], timed=False, market="EU", region="EU", ticker=r["s"],
                       title=f"{r['n']} bilanço", name=r["n"], country=r.get("c"), eps_est=r.get("e"),
                       detail=" · ".join(det), importance=3 if r.get("big") else 2, src="yahoo", group="Avrupa",
                       url=f"https://finance.yahoo.com/quote/{r['s']}/"))
    for d in (cache.get("ecb") or {}).get("rows") or []:
        if lo <= d <= hi:
            out.append(_ev(kind="cb", date=d, when=_at(d, "14:15", CET), timed=True, market="EU", region="EU",
                           title="ECB faiz kararı", importance=3, src="ecb",
                           detail="Karar 14:15 CET'te, basın toplantısı 14:45 CET'te",
                           assets=["EUR/USD", "Avrupa tahvil faizleri", "Avrupa bankaları"], url=ECB_URL))
    for r in (cache.get("eurostat") or {}).get("rows") or []:
        if lo <= r["d"] <= hi:
            out.append(_ev(kind="macro" if r["imp"] >= 2 else "data", date=r["d"], when=_at(r["d"], r["hm"], CET), timed=True,
                           market="EU", region="EU", title=r["short"] + (f" · {r['period']}" if r.get("period") else ""),
                           period=r.get("period"), detail=f"Eurostat: {r['title']}", importance=r["imp"], src="eurostat",
                           inst="Eurostat", assets=r["assets"], url=EUROSTAT_PAGE))
    return out
