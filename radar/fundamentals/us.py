"""ABD temel analiz: S&P 500 + Nasdaq-100 + Dow 30 şirketlerinin SEC EDGAR XBRL verisi → BIST ile aynı oran/kriter motoru.

Kaynak (resmi, ücretsiz, kamu malı): https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
* Her şirket için us-gaap etiketleri BIST seri şemasına (series: q / ttm / cum / bs) eşlenir.
* 10-Q nakit akışı kalemleri yılbaşından bugüne (YTD) yayımlanır; çeyrekler YTD farklarından, 4. çeyrek yıllık − 9 ay
  olarak türetilir. Dönem anahtarı en yakın takvim çeyreği sonudur (Apple'ın 27 Eylül'ü → 2026/09).
* Yenileme: SEC günlük dizininden (form.YYYYMMDD.idx) o gün 10-Q / 10-K verenler kuyruğa girer; bunlara ek olarak her
  turda en eski verili şirketler yenilenir. SEC sınırı saniyede 10 istek; burada en fazla ~5. User-Agent: http.SEC_UA.
* Piyasa değeri ve 12-1 ay momentum ABD ısı haritası verisinden (us_map.json; Yahoo, yalnız piyasa değeri ve yüzde
  getiri) okunur; ham fiyat yayımlanmaz. Tutarlar USD, büyümeler nominaldir (enflasyon düzeltmesi yok).
Çıktı: site/data/fin_us/<KOD>.json (seriler) ve site/data/fin_us/_screen.json (tarama özeti; sitede yayımlanan tek dosya).
`python -m radar.fundamentals.us [bütçe]`
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .. import http
from ..config import DATA

log = logging.getLogger("radar.fundamentals.us")

OUT = DATA / "fin_us"
STATE = OUT / "_state.json"
SCREEN = OUT / "_screen.json"
USMAP = DATA / "us_map.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{y}/QTR{q}/form.{d}.idx"
QUARTERS = 20                     # 5 yıl
STALE_DAYS = 30                   # dosyalama görülmese de bu kadar günde bir yenilenir
PAUSE = 0.2
SER_VER = 3                       # seri şeması/eşleme değişince tüm şirketler yeniden indirilir

# BIST seri kalemi → (us-gaap etiketleri öncelik sırasıyla, işaret). İşaret −1: gider/ödeme, BIST şemasında eksi tutulur.
DUR = {
    "revenue": (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                 "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense",
                 "RegulatedAndUnregulatedOperatingRevenue", "ElectricUtilityRevenue", "RevenuesExcludingInterestAndDividends"], 1),
    "cogs": (["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"], -1),
    "gross": (["GrossProfit"], 1),
    "gna": (["SellingGeneralAndAdministrativeExpense", "GeneralAndAdministrativeExpense"], -1),
    "rnd": (["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"], -1),
    "op_profit": (["OperatingIncomeLoss"], 1),
    "fin_exp": (["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"], -1),
    "pretax": (["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"], 1),
    "tax": (["IncomeTaxExpenseBenefit"], -1),
    "net": (["ProfitLoss", "NetIncomeLoss"], 1),
    "net_parent": (["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"], 1),
    "da": (["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "Depreciation"], 1),
    "cfo": (["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], 1),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
               "PaymentsForCapitalImprovements"], -1),
    "dividends_paid": (["PaymentsOfDividendsCommonStock", "PaymentsOfDividends", "PaymentsOfOrdinaryDividends"], -1),
    "interest_paid": (["InterestPaidNet", "InterestPaid"], -1),
}
INST = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "st_fin_inv": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventories": ["InventoryNet"],
    "current_assets": ["AssetsCurrent"],
    "total_assets": ["Assets"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
    "goodwill": ["Goodwill"],
    "intang_x": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "st_borrowings": ["ShortTermBorrowings", "CommercialPaper", "DebtCurrent"],
    "lt_borrowings_cur": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "lt_borrowings": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"],
    "payables": ["AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"],
    "current_liab": ["LiabilitiesCurrent"],
    "total_liab": ["Liabilities"],
    "equity_parent": ["StockholdersEquity"],
    "equity_total": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "minority": ["MinorityInterest"],
    "liab_equity": ["LiabilitiesAndStockholdersEquity"],
    "retained": ["RetainedEarningsAccumulatedDeficit"],
}
SHARES = (["dei", "EntityCommonStockSharesOutstanding"], ["us-gaap", "CommonStockSharesOutstanding"])


# ───────────────────────────── yardımcılar

def _d(s: str) -> date:
    return date.fromisoformat(s)


def quarter_key(end: str) -> str:
    """Bitiş tarihi → en yakın takvim çeyrek sonu 'YYYY/MM' (52-53 haftalık mali yıllar ve kayık çeyrekler)."""
    d = _d(end)
    best = None
    for y in (d.year - 1, d.year, d.year + 1):
        for m in (3, 6, 9, 12):
            qe = date(y, m, 31 if m in (3, 12) else 30)
            gap = abs((d - qe).days)
            if best is None or gap < best[0]:
                best = (gap, f"{y}/{m:02d}")
    return best[1]


def _shift(pk: str, n: int) -> str:
    y, m = (int(x) for x in pk.split("/"))
    i = y * 4 + (m // 3 - 1) + n
    return f"{i // 4}/{(i % 4 + 1) * 3:02d}"


def _latest(facts: list[dict]) -> dict:
    """(başlangıç, bitiş) → en son dosyalanan değer (düzeltmeler eskinin yerine geçer)."""
    by: dict[tuple, dict] = {}
    for f in facts:
        if f.get("val") is None or not f.get("end"):
            continue
        k = (f.get("start"), f["end"])
        if k not in by or (f.get("filed") or "") >= (by[k].get("filed") or ""):
            by[k] = f
    return by


def _units(tagdoc: dict, unit: str = "USD") -> list[dict]:
    u = tagdoc.get("units") or {}
    return u.get(unit) or (next(iter(u.values())) if len(u) == 1 else [])


def quarterly_flow(facts: list[dict], key=None) -> dict[str, float]:
    """Süreli (gelir tablosu / nakit akışı) bir etiketin çeyreklik değerleri {pk: değer}.

    Doğrudan ~3 aylık değerler öncelikli; yoksa aynı başlangıçlı YTD değerlerin farkı (6A−3A, 9A−6A, 12A−9A)."""
    key = key or quarter_key
    by = _latest(facts)
    direct: dict[str, float] = {}
    ytd: dict[str, list] = {}
    for (start, end), f in by.items():
        if not start:
            continue
        days = (_d(end) - _d(start)).days
        if 80 <= days <= 100:
            direct[key(end)] = float(f["val"])
        if 80 <= days <= 380:
            ytd.setdefault(start, []).append((end, days, float(f["val"])))
    derived: dict[str, float] = {}
    for start, xs in ytd.items():
        xs.sort()
        for (e0, d0, v0), (e1, d1, v1) in zip(xs, xs[1:]):
            if 75 <= d1 - d0 <= 120:                      # 16 haftalık son çeyrekler (AutoZone) dahil
                derived.setdefault(key(e1), v1 - v0)
    out = {**derived, **direct}
    return out


def annual_flow(facts: list[dict], key=None) -> dict[str, float]:
    """Yıllık (~12 ay) değerler {mali yıl sonu pk: değer}."""
    key = key or quarter_key
    return {key(e): float(f["val"]) for (s, e), f in _latest(facts).items()
            if s and 350 <= (_d(e) - _d(s)).days <= 380}


def instant(facts: list[dict], key=None) -> dict[str, float]:
    key = key or quarter_key
    out, seen = {}, {}
    for (s, e), f in _latest(facts).items():
        if s:
            continue
        pk = key(e)
        if pk not in seen or e > seen[pk]:
            out[pk], seen[pk] = float(f["val"]), e
    return out


def fiscal_keys(gaap: dict):
    """Mali çeyrek sonları bilanço tarihlerinden zincirlenir: en son tarih en yakın takvim çeyreğine, öncekiler birer
    çeyrek geriye yazılır. 52-53 haftalık ve 12/12/12/16 haftalık takvimlerde iki çeyreğin aynı anahtara düşmesi önlenir."""
    ends = sorted({f["end"] for t in ("Assets", "LiabilitiesAndStockholdersEquity") if t in gaap
                   for f in _units(gaap[t]) if f.get("end") and not f.get("start")}, reverse=True)
    chain: list[tuple[date, str]] = []
    for e in ends:
        d = _d(e)
        if not chain:
            chain.append((d, quarter_key(e)))
        elif (chain[-1][0] - d).days >= 60:
            chain.append((d, _shift(chain[-1][1], -max(1, round((chain[-1][0] - d).days / 91.3)))))

    def key(end: str) -> str:
        d = _d(end)
        best = min(chain, key=lambda c: abs((c[0] - d).days), default=None)
        return best[1] if best and abs((best[0] - d).days) <= 25 else quarter_key(end)
    return key


def _pick(gaap: dict, tags: list[str], fn, key=None) -> dict[str, float]:
    """Etiketleri öncelik sırasıyla birleştirir: önceki etiketin boş bıraktığı dönemleri sonraki doldurur."""
    # Etiket değişen şirketler (ör. 2026'da PaymentsOfDividends → PaymentsOfOrdinaryDividends): olgular aynı (başlangıç,
    # bitiş) için öncelikli etiketten alınıp birleştirilir; YTD farkı iki etiketin olgularından birlikte türetilebilir.
    merged: dict[tuple, dict] = {}
    for t in tags:
        if t in gaap:
            for k, f in _latest(_units(gaap[t])).items():
                merged.setdefault(k, f)
    return fn(list(merged.values()), key) if merged else {}


def build_series(facts: dict, quarters: int = QUARTERS) -> dict | None:
    """companyfacts → BIST seri şeması (metrics.View ile okunur). Yeterli veri yoksa None."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    key = fiscal_keys(gaap)
    q: dict[str, dict] = {}
    for item, (tags, sign) in DUR.items():
        qv = _pick(gaap, tags, quarterly_flow, key)
        av = _pick(gaap, tags, annual_flow, key)
        for pk, a in av.items():                         # 4. çeyrek (ya da eksik tek çeyrek) = yıllık − diğer üçü
            prev = [qv.get(_shift(pk, -k)) for k in (1, 2, 3)]
            if pk not in qv and None not in prev:
                qv[pk] = a - sum(prev)
        q[item] = {pk: v * sign for pk, v in qv.items()}
    bs = {item: _pick(gaap, tags, instant, key) for item, tags in INST.items()}
    rev = q["revenue"]
    if not rev and not q["net_parent"]:
        return None
    anchor = max(set(rev) | set(bs["total_assets"]))
    periods = [_shift(anchor, -k) for k in range(quarters - 1, -1, -1)]
    # Brüt kâr ve FAVÖK türetmeleri
    for pk in periods:
        if pk not in q["gross"] and pk in rev and pk in q["cogs"]:
            q["gross"][pk] = rev[pk] + q["cogs"][pk]
    qa = {k: [v.get(pk) for pk in periods] for k, v in q.items()}
    qa["ebitda"] = [o + d if o is not None and d is not None else None for o, d in zip(qa["op_profit"], qa["da"])]
    qa["fcf"] = [c + (x or 0) if c is not None else None for c, x in zip(qa["cfo"], qa["capex"])]
    qa["monetary"] = [0.0] * len(periods)              # ABD'de enflasyon muhasebesi yok
    for k in ("selling", "other_op_inc", "other_op_exp", "equity_pickup", "inv_inc", "inv_exp", "fin_inc", "cfi", "cff", "tax_paid"):
        qa.setdefault(k, [None] * len(periods))

    def ttm(arr):
        return [sum(arr[i - 3:i + 1]) if i >= 3 and None not in arr[i - 3:i + 1] else None for i in range(len(arr))]
    tt = {k: ttm(v) for k, v in qa.items()}
    b = {k: [v.get(pk) for pk in periods] for k, v in bs.items()}
    n = len(periods)
    g = lambda k, i: b[k][i]  # noqa: E731
    out_bs = {k: b[k] for k in ("cash", "st_fin_inv", "receivables", "inventories", "current_assets", "total_assets", "ppe",
                                "st_borrowings", "lt_borrowings_cur", "lt_borrowings", "payables", "current_liab",
                                "equity_parent", "minority", "retained")}
    out_bs["intangibles"] = [(g("goodwill", i) or 0) + (g("intang_x", i) or 0) if g("goodwill", i) is not None or g("intang_x", i) is not None
                             else None for i in range(n)]
    out_bs["equity_parent"] = [g("equity_parent", i) if g("equity_parent", i) is not None else
                               (g("equity_total", i) - (g("minority", i) or 0) if g("equity_total", i) is not None else None) for i in range(n)]
    out_bs["equity_total"] = [g("equity_total", i) if g("equity_total", i) is not None else
                              (g("equity_parent", i) + (g("minority", i) or 0) if g("equity_parent", i) is not None else None) for i in range(n)]
    out_bs["total_liab"] = [g("total_liab", i) if g("total_liab", i) is not None else
                            (g("liab_equity", i) - out_bs["equity_total"][i] if None not in (g("liab_equity", i), out_bs["equity_total"][i]) else None)
                            for i in range(n)]
    out_bs["noncurrent_assets"] = [a - c if None not in (a, c) else None for a, c in zip(b["total_assets"], b["current_assets"])]
    out_bs["noncurrent_liab"] = [a - c if None not in (a, c) else None for a, c in zip(out_bs["total_liab"], b["current_liab"])]
    out_bs["fin_debt"] = [sum(x or 0 for x in (g("st_borrowings", i), g("lt_borrowings_cur", i), g("lt_borrowings", i)))
                          if any(x is not None for x in (g("st_borrowings", i), g("lt_borrowings_cur", i), g("lt_borrowings", i)))
                          or g("total_assets", i) is not None else None for i in range(n)]
    out_bs["net_debt"] = [fd - (c or 0) - (s or 0) if fd is not None and (c is not None or s is not None) else None
                          for fd, c, s in zip(out_bs["fin_debt"], b["cash"], b["st_fin_inv"])]
    out_bs["paid_capital"] = shares_series(facts, periods)
    out_bs["inv_property"] = out_bs["treasury"] = [None] * n
    return {"periods": periods, "cpi": [1.0] * n, "cpi_ya": [1.0] * n, "nominal": [True] * n, "template": "sanayi",
            "q": qa, "ttm": tt, "cum": tt, "cum_prev": {k: [None] * n for k in tt}, "bs": out_bs}


def shares_series(facts: dict, periods: list[str]) -> list:
    """Dönem sonu pay sayısı; kapak sayfası (dei) değeri dosyalama tarihli olduğundan en yakın önceki çeyreğe yazılır."""
    pts: dict[str, float] = {}
    for tax, tag in SHARES:
        doc = (facts.get("facts") or {}).get(tax, {}).get(tag)
        if not doc:
            continue
        # Çok sınıflı paylar (Alphabet A/B/C) aynı bildirimde ayrı satırlar: bildirim içinde toplanır, en son bildirim alınır
        per: dict[tuple, float] = {}
        filed: dict[str, tuple] = {}
        for f in _units(doc, "shares"):
            if not f.get("val") or not f.get("end"):
                continue
            k = (f["end"], f.get("accn"))
            per[k] = per.get(k, 0.0) + float(f["val"]) if tax == "dei" else float(f["val"])
            if f["end"] not in filed or (f.get("filed") or "") >= filed[f["end"]][0]:
                filed[f["end"]] = (f.get("filed") or "", f.get("accn"))
        for e, (_, accn) in filed.items():
            pts.setdefault(quarter_key(e), per[(e, accn)])
    out, last = [], None
    for pk in periods:
        last = pts.get(pk, last)
        out.append(last)
    return out


# ───────────────────────────── SEC erişimi

def _get_json(url: str):
    r = http.get(url, headers={"User-Agent": http.SEC_UA, "Accept-Encoding": "gzip, deflate"}, timeout=60, retries=2)
    time.sleep(PAUSE)
    return r.json() if r is not None and r.status_code == 200 else None


def cik_map() -> dict[str, int]:
    d = _get_json(TICKERS_URL) or {}
    return {v["ticker"].upper().replace("-", "."): int(v["cik_str"]) for v in d.values()}


def filers_on(day: date) -> set[int]:
    """O gün 10-Q / 10-K (ve düzeltmeleri) dosyalayan CIK'ler."""
    r = http.get(INDEX_URL.format(y=day.year, q=(day.month - 1) // 3 + 1, d=day.strftime("%Y%m%d")),
                 headers={"User-Agent": http.SEC_UA}, timeout=30, retries=1)
    time.sleep(PAUSE)
    if r is None or r.status_code != 200:
        return set()
    out = set()
    for line in r.text.splitlines():
        parts = line.split()
        if parts and parts[0] in ("10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT") and len(parts) >= 4:
            for p in parts[1:]:
                if p.isdigit() and len(p) <= 10:
                    out.add(int(p))
                    break
    return out


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except ValueError:
        return default


def _save(p, obj) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ───────────────────────────── ana akış

def universe() -> list[dict]:
    """us_map.json (piyasa değeri, momentum, endeks etiketi, sektör) yoksa yalnız bileşen listeleri."""
    from .. import usmap
    mp = {r["code"]: r for r in (_load(USMAP, {}).get("stocks") or [])}
    ysh = _load(usmap.SHARES, {}).get("shares", {})
    out = []
    for m in usmap.members():
        if m["code"] in usmap.DUAL:                       # GOOG → GOOGL: aynı şirket bir kez
            continue
        r = mp.get(m["code"], {})
        n = ((ysh.get(m["code"]) or {}).get("n"))
        own = r.get("mc0") or r.get("mcap")
        out.append({**m, "mcap": r.get("mcap"), "mom": r.get("mom"), "ysh": n, "px": own / n if own and n else None})
    return out


def refresh(budget: int = 120, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    OUT.mkdir(parents=True, exist_ok=True)
    st = _load(STATE, {})
    ms = universe()
    ciks = st.get("cik") or {}
    if not ciks or not st.get("cik_at") or now - datetime.fromisoformat(st["cik_at"]) > timedelta(days=7):
        got = cik_map()
        if got:
            ciks = {m["code"]: got.get(m["code"]) or got.get(m["code"].replace(".", "")) for m in ms}
            st["cik"], st["cik_at"] = ciks, now.isoformat(timespec="seconds")
    by_cik = {v: k for k, v in ciks.items() if v}
    # Son günlerde dosyalayanlar kuyruğa (dizin bir gün geriden okunur: XBRL işlemesi o gün tamamlanmış olur)
    queue = set(st.get("queue") or [])
    last = st.get("index_day")
    day = _d(last) + timedelta(days=1) if last else now.date() - timedelta(days=3)
    while day < now.date():
        if day.weekday() < 5:
            for c in filers_on(day):
                if c in by_cik:
                    queue.add(by_cik[c])
        st["index_day"] = day.isoformat()
        day += timedelta(days=1)
    fetched = st.get("fetched") or {}
    if st.get("ver") != SER_VER:
        fetched, st["ver"] = {}, SER_VER
    missing = [m["code"] for m in ms if m["code"] not in fetched and ciks.get(m["code"])]
    stale = sorted((c for c, t in fetched.items() if now - datetime.fromisoformat(t) > timedelta(days=STALE_DAYS)), key=fetched.get)
    order = list(dict.fromkeys(sorted(queue) + missing + stale))
    done = 0
    for code in order[:budget]:
        facts = _get_json(FACTS_URL.format(cik=ciks[code])) if ciks.get(code) else None
        if facts is None:
            continue
        ser = build_series(facts)
        if ser:
            _save(OUT / f"{code}.json", {"code": code, "title": facts.get("entityName"), "currency": "USD",
                                         "template": "sanayi", "series": ser, "series_at": now.isoformat(timespec="seconds")})
        fetched[code] = now.isoformat(timespec="seconds")
        queue.discard(code)
        done += 1
    st.update({"fetched": fetched, "queue": sorted(queue)})
    _save(STATE, st)
    n = build_screen(ms)
    log.info("ABD temel: %d şirket indirildi, kuyrukta %d, eksik %d, taramada %d", done, len(queue), max(0, len(missing) - done), n)
    return {"fetched": done, "queue": len(queue), "screened": n}


def us_label(lbl: str) -> str:
    """BIST etiketlerindeki enflasyona özgü ifadeler ABD'de (nominal USD) düşer."""
    import re
    out = lbl.replace("Parasal kazanç hariç vergi öncesi", "Vergi öncesi")
    out = re.sub(r"\b[Rr]eel ", "", out)
    return out[:1].upper() + out[1:]


PRIVATE = ("shares", "price", "eps", "bvps", "intrinsic")    # pay başı fiyat türevleri yayımlanmaz
SKIP_SETS = {"Enflasyon Muhasebesi & Nakit Kalitesi"}   # TMS 29'a özgü


def build_screen(ms: list[dict] | None = None) -> int:
    from . import metrics as M
    ms = ms or universe()
    rows = []
    for m in ms:
        doc = _load(OUT / f"{m['code']}.json", None)
        if not doc or not m.get("mcap"):
            continue
        ser = doc["series"]
        pc = ser["bs"]["paid_capital"]
        sh = pc[-1]
        ysh = m.get("ysh")
        if ysh and (not sh or not 0.33 < sh / ysh < 3):     # SEC'te pay sayısı yok ya da birim/sınıf uyumsuz → Yahoo
            pc[-1] = sh = ysh
        if not sh:
            continue
        price = m.get("px") or m["mcap"] / sh                 # pay başı değer; SEC toplam pay × fiyat = tüm sınıflar
        try:
            met = M.company(doc, price, None, m.get("mom"))
        except Exception:  # noqa: BLE001
            log.exception("ABD metrik hesaplanamadı: %s", m["code"])
            continue
        if not met:
            continue
        for k in SKIP_SETS:
            met["criteria"].pop(k, None)
        rows.append({"code": m["code"], "sector": m.get("sector"), "m": met, "name": m.get("name"), "ix": m.get("ix") or []})
    M.finalize(rows)
    for row in rows:
        row["m"]["ratios"]["mon_share"] = None              # ABD'de parasal kazanç kalemi yok: 0 yerine "yok"
        (row["m"].get("history") or {}).pop("mon_share", None)
        for k in SKIP_SETS:
            row["m"]["criteria"].pop(k, None)
        for c in row["m"]["criteria"].values():
            c["items"] = [[us_label(lbl), v] for lbl, v in c["items"]]
    screen = []
    for row in rows:
        m = row["m"]
        v = {k: x for k, x in m["valuation"].items() if k not in PRIVATE}
        screen.append({
            "code": row["code"], "title": row["name"], "sector": row["sector"], "period": m["period"], "mkt": "us",
            "mcap": m["valuation"].get("mcap"), "t": "sanayi", "idx": row["ix"],
            "r": m["ratios"], "v": v, "cat": m["categories"], "quality": m["quality"],
            "valuation_score": m["valuation_score"], "overall": m["overall"], "grade": m["grade"], "z": m["altman_z2"],
            "f": m["piotroski"], "mscore": m["beneish_m"], "potential": m.get("potential"),
            "crit": {k: [c["pass"], c["total"], c["known"], [x for _, x in c["items"]]] for k, c in m["criteria"].items()},
        })
    # Karşılaştır sayfası için şirket başına metrik belgesi (SEC verisinden türetilmiş oranlar; fiyat alanları yok)
    pub = OUT / "c"
    pub.mkdir(exist_ok=True)
    keep = set()
    for row in rows:
        m = dict(row["m"])
        m["valuation"] = {k: x for k, x in m["valuation"].items() if k not in PRIVATE}
        for k in ("intrinsic", "pb_hist"):
            m.pop(k, None)
        _save(pub / f"{row['code']}.json", {"code": row["code"], "title": row["name"], "sector": row["sector"], "currency": "USD",
                                            "template": "sanayi", "mkt": "us", "idx": row["ix"], "metrics": m})
        keep.add(f"{row['code']}.json")
    for f in pub.glob("*.json"):
        if f.name not in keep:
            f.unlink()
    from .store import crit_labels
    _save(SCREEN, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "currency": "USD", "rows": screen,
                   "criteria_labels": crit_labels(rows, M.CRIT_ORDER), "criteria_groups": [[g, ks] for g, ks in M.CRIT_GROUPS],
                   "source": "SEC EDGAR XBRL (companyfacts); piyasa değeri ve momentum Yahoo"})
    return len(screen)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    refresh(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
