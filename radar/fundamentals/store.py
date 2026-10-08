"""Temel analiz veri katmanı: BIST-100 şirketlerinin KAP mali tablolarını ve TÜFE'yi toplar.

Radar iş akışında ayrı bir adım olarak, zaman bütçesiyle çalışır (`python -m radar.fundamentals`):
  1. Evren (haftalık): KAP endeks sayfasından BIST-100 üyeleri.
  2. TÜFE (günlük): EVDS TP.GENENDEKS.T1 (2003=100, TMS 29'un da kullandığı seri).
  3. Yeni raporlar (saatlik): son 3 günün finansal rapor bildirimleri → kuyruk.
  4. Geçmiş (kademeli): her şirketin 2023'ten bu yana raporları listelenir → kuyruk.
  5. Kuyruk: en yeni dönemden eskiye; her dönem için konsolide rapor tercih edilir.
Çıktı: site/data/fin/{KOD}.json, _universe.json, _cpi.json, _state.json
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .. import http
from ..config import DATA
from . import dividends, kapfin, series

log = logging.getLogger("radar.fundamentals")

FIN = DATA / "fin"
STATE = FIN / "_state.json"
UNIVERSE = FIN / "_universe.json"
CPI = FIN / "_cpi.json"
DIVS = FIN / "_dividends.json"
HISTORY_START = date(2023, 1, 1)        # BIST-100: 2022 yıl sonundan bu yana
HISTORY_START_EXT = date(2024, 7, 1)    # diğer şirketler: 12A ve yıllık büyüme için yeterli en kısa geçmiş (2024/06'dan)
INDEX_TAGS = ("XU030", "XU050", "XU100", "XKTUM")   # arayüzde süzgeç olarak kullanılan endeksler
UNIVERSE_INDEX = os.environ.get("FIN_UNIVERSE", "XUTUM")  # BIST Tüm
CPI_SERIES = "TP.GENENDEKS.T1"
EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
GAP = float(os.environ.get("FIN_GAP", 3.0))   # KAP istekleri arası bekleme (sn)
PAUSE_MIN = 10     # 429 sonrası ara
MAX_PERIODS = 20   # çalıştırma başına işlenecek dönem
MAX_REQ = 40       # çalıştırma başına liste isteği
MAX_EXPORTS = 9    # çalıştırma başına rapor indirme (KAP ~5 dakikada 10 indirmeden sonra 429 veriyor; radar 15 dk'da bir)
MAX_TRIES = 3
MAX_DIV = 10       # çalıştırma başına kar payı bildirim sayfası
LIST_VERSION = 2   # 2: liste kar payı bildirimlerini de içerir (eski listeler bir kez yeniden çekilir)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _due(state: dict, name: str, hours: float) -> bool:
    last = state.get("last", {}).get(name)
    if last and _now() - datetime.fromisoformat(last) < timedelta(hours=hours):
        return False
    state.setdefault("last", {})[name] = _now().isoformat(timespec="seconds")
    return True


# ---- TÜFE ----

def parse_cpi(payload: dict, code: str = CPI_SERIES) -> dict[str, float]:
    key = code.replace(".", "_")
    out = {}
    for row in payload.get("items", []):
        v, t = row.get(key), row.get("Tarih")
        if v in (None, "") or not t:
            continue
        y, m = str(t).split("-")[:2]
        out[f"{int(y):04d}-{int(m):02d}"] = round(float(v), 4)
    return out


def update_cpi() -> bool:
    key = os.environ.get("EVDS_API_KEY")
    if not key:
        return False
    end = date.today()
    url = (f"{EVDS_URL}series={CPI_SERIES}&startDate=01-01-2015&endDate={end:%d-%m-%Y}"
           f"&type=json&frequency=5")
    r = http.get(url, headers={"key": key}, timeout=60)
    if r is None:
        return False
    try:
        m = parse_cpi(r.json())
    except ValueError:
        return False
    if m:
        _save(CPI, {"series": CPI_SERIES, "base": "2003=100", "updated": _now().isoformat(timespec="seconds"), "m": m})
    return bool(m)


# ---- Kuyruk ----

def enqueue(state: dict, code: str, row: dict) -> bool:
    """Bildirimi kuyruğa ekler. Aynı dönem için daha yeni bildirim (düzeltme) gelirse dönem yeniden işlenir."""
    if kapfin.is_div(row):
        idx = int(row["disclosureIndex"])
        comp = state.setdefault("companies", {}).setdefault(code, {})
        if idx in comp.get("seen", []):
            return False
        comp.setdefault("seen", []).append(idx)
        state.setdefault("div_queue", {}).setdefault(code, []).append(idx)
        return True
    try:
        year, period = int(row["year"]), int(row["period"])
    except (KeyError, TypeError, ValueError):
        return False
    if not 1 <= period <= 4:
        return False
    idx = int(row["disclosureIndex"])
    comp = state.setdefault("companies", {}).setdefault(code, {})
    if idx in comp.get("seen", []):
        return False
    comp.setdefault("seen", []).append(idx)
    pk = kapfin.period_key(year, period)
    q = state.setdefault("queue", {}).setdefault(code, {})
    q.setdefault(pk, [])
    if idx not in q[pk]:
        q[pk].append(idx)
    return True


def next_jobs(state: dict, priority: set[str] | None = None) -> list[tuple[str, str]]:
    """(kod, dönem) çiftleri: önce öncelikli şirketler (BIST-100), her grupta en yeni dönemden geriye."""
    jobs = [(code, pk) for code, per in state.get("queue", {}).items() for pk in per]
    pr = priority or set()
    return sorted(jobs, key=lambda j: (j[0] in pr, j[1], j[0]), reverse=True)


def choose(reports: list[dict]) -> dict | None:
    """Aynı dönemin raporlarından: konsolide olanı, yoksa en yenisini seç."""
    good = [r for r in reports if r and r.get("is")]
    if not good:
        return None
    good.sort(key=lambda r: (bool(r.get("consolidated")), r.get("idx", 0)), reverse=True)
    return good[0]


def process_period(code: str, pk: str, idxs: list[int], fetch=kapfin.fetch_export) -> dict | None:
    """En yeni bildirimden başlar; konsolide bulunca durur."""
    got = []
    for idx in sorted(idxs, reverse=True):
        rep = fetch(idx)
        time.sleep(GAP)
        if rep is None:
            continue
        got.append(rep)
        if rep.get("consolidated"):
            break
    return choose(got)


def save_report(code: str, title: str, pk: str, rep: dict) -> None:
    p = FIN / f"{code}.json"
    doc = _load(p, {"code": code, "title": title, "reports": {}})
    old = doc["reports"].get(pk)
    # Konsolide olan konsolide olmayanla ezilmez; aynı türde daha yeni bildirim kazanır.
    if old and old.get("consolidated") and not rep.get("consolidated"):
        return
    doc["title"] = title or doc.get("title")
    doc["reports"][pk] = rep
    latest = max(doc["reports"])
    doc["template"] = doc["reports"][latest].get("template")
    doc["currency"] = doc["reports"][latest].get("currency")
    doc["updated"] = _now().isoformat(timespec="seconds")
    _save(p, doc)


def rebuild_series(force: bool = False) -> int:
    """Yeni rapor gelen (ya da TÜFE güncellenince tüm) şirketlerin standart serilerini yeniden hesaplar."""
    cpi = _load(CPI, {}).get("m", {})
    n = 0
    for p in sorted(FIN.glob("[A-Z0-9]*.json")):
        doc = _load(p, None)
        if not doc or (not force and doc.get("series_at") == doc.get("updated")):
            continue
        try:
            doc["series"] = series.build(doc, cpi)
        except Exception:  # tek şirketin bozuk verisi tüm adımı durdurmasın
            log.exception("Seri hesaplanamadı: %s", p.name)
            continue
        doc["series_at"] = doc.get("updated")
        _save(p, doc)
        n += 1
    return n


# ---- Ana döngü ----

def _kap_work(state, members, comps, stats, left, budget) -> None:
    start_req, start_exp = kapfin.REQUESTS, kapfin.EXPORTS
    spent = lambda: kapfin.REQUESTS - start_req  # noqa: E731
    exported = lambda: kapfin.EXPORTS - start_exp  # noqa: E731
    if _due(state, "recent", 1):
        for row in kapfin.recent_reports(3):
            for c in kapfin.codes_of(row):
                if c in members and enqueue(state, c, row):
                    stats["queued"] += 1

    order = sorted(members.items(), key=lambda kv: "XU100" not in kv[1].get("idx", ["XU100"]))
    for code, m in order:
        if left() < budget * 0.6 or spent() >= MAX_REQ:
            break
        if comps.get(code, {}).get("listed") and comps[code].get("lv", 1) >= LIST_VERSION:
            continue
        start = HISTORY_START if "XU100" in m.get("idx", ["XU100"]) else HISTORY_START_EXT
        rows = kapfin.list_reports(m["oid"], start, date.today())
        if rows is None:
            continue
        for row in rows:
            if enqueue(state, code, row):
                stats["queued"] += 1
        comps.setdefault(code, {})["listed"] = date.today().isoformat()
        comps[code]["lv"] = LIST_VERSION
        stats["listed"] += 1

    prio = {c for c, m in members.items() if "XU100" in m.get("idx", ["XU100"])}
    for code, pk in next_jobs(state, prio):
        if left() < 15 or stats["processed"] + stats["failed"] >= MAX_PERIODS or exported() >= MAX_EXPORTS - 1:
            break
        idxs = state["queue"][code][pk]
        rep = process_period(code, pk, idxs)          # RateLimited burada yukarı çıkar, iş kuyrukta kalır
        tries = comps.setdefault(code, {}).setdefault("tries", {})
        if rep is None:
            tries[pk] = tries.get(pk, 0) + 1
            if tries[pk] < MAX_TRIES:
                continue
            comps[code].setdefault("failed", []).append(pk)
            stats["failed"] += 1
        else:
            save_report(code, members.get(code, {}).get("title", ""), pk, rep)
            stats["processed"] += 1
        tries.pop(pk, None)
        del state["queue"][code][pk]
        if not state["queue"][code]:
            del state["queue"][code]

    # Kar payı bildirimleri (ayrı uç: bildirim sayfası); en yeniden eskiye
    dq = state.get("div_queue", {})
    prio = {c for c, m in members.items() if "XU100" in m.get("idx", ["XU100"])}
    jobs = sorted(((code in prio, idx, code) for code, xs in dq.items() for idx in xs), reverse=True)
    jobs = [(idx, code) for _, idx, code in jobs]
    divs = None
    for idx, code in jobs[:MAX_DIV]:
        if left() < 10:
            break
        d = dividends.fetch(idx, code)
        time.sleep(GAP)
        dq[code].remove(idx)
        if not dq[code]:
            del dq[code]
        if d is None:
            continue
        if divs is None:
            divs = _load(DIVS, {})
        divs[code] = merge_divs(divs.get(code, []), d)
        stats["dividends"] = stats.get("dividends", 0) + 1
    if divs is not None:
        for c, xs in divs.items():             # eski kayıtlardaki tekrarları da temizle
            out: list[dict] = []
            for x in xs:
                out = merge_divs(out, x)
            divs[c] = out
        _save(DIVS, divs)

def run(budget: float = 180.0, settings: dict | None = None) -> dict:
    t0 = time.monotonic()
    left = lambda: budget - (time.monotonic() - t0)  # noqa: E731
    state = _load(STATE, {})
    uni = _load(UNIVERSE, {})
    stats = {"listed": 0, "queued": 0, "processed": 0, "failed": 0}
    comps = state.setdefault("companies", {})

    if not uni.get("members") or uni.get("v", 1) < 3 or _due(state, "universe", 24 * 7):
        idx = kapfin.fetch_indices()
        base = idx.get(UNIVERSE_INDEX) or idx.get("XU100")
        if base:
            sectors = kapfin.fetch_sectors()
            members = [{**m, **sectors.get(m["code"], {}),
                        "idx": [t for t in INDEX_TAGS if any(x["code"] == m["code"] for x in idx.get(t, []))]} for m in base]
            uni = {"v": 3, "index": UNIVERSE_INDEX if idx.get(UNIVERSE_INDEX) else "XU100",
                   "updated": _now().isoformat(timespec="seconds"), "members": members}
            _save(UNIVERSE, uni)
    members = {m["code"]: m for m in uni.get("members", [])}
    only = {c.strip().upper() for c in os.environ.get("FIN_CODES", "").split(",") if c.strip()}
    if only:                                   # deneme/önizleme: yalnız seçili şirketler
        members = {c: m for c, m in members.items() if c in only}
    if not members:
        log.warning("Temel analiz: evren boş (KAP endeks sayfası okunamadı)")
        _save(STATE, state)
        return stats

    if not state.get("mig_fin"):
        # Banka/sigorta şablonu eklendi: eski ayrıştırmayla (bilançosuz) kaydedilenler yeniden indirilir
        for p in FIN.glob("[A-Z0-9]*.json"):
            doc = _load(p, None)
            if doc and doc.get("template") == "finansal":
                code = doc.get("code") or p.stem
                p.unlink()
                comps.pop(code, None)
                state.get("queue", {}).pop(code, None)
        state["mig_fin"] = True

    cpi_new = _due(state, "cpi", 24) and update_cpi()

    comps = state.setdefault("companies", {})
    pause = state.get("kap_pause_until")
    if pause and _now() < datetime.fromisoformat(pause):
        log.info("Temel analiz: KAP hız sınırı beklemesi (%s'e kadar)", pause)
    else:
        try:
            _kap_work(state, members, comps, stats, left, budget)
        except kapfin.RateLimited:
            state["kap_pause_until"] = (_now() + timedelta(minutes=PAUSE_MIN)).isoformat(timespec="seconds")
            stats["rate_limited"] = True
            log.warning("Temel analiz: KAP 429 — %d dk ara", PAUSE_MIN)

    rebuilt = rebuild_series(force=bool(cpi_new))
    prices_new = _due(state, "prices", 1) and update_prices(sorted(members))
    if rebuilt or prices_new or not SCREEN.exists():
        try:
            stats["screened"] = build_metrics()
        except Exception:
            log.exception("Temel analiz metrikleri hesaplanamadı")
    pending = sum(len(v) for v in state.get("queue", {}).values())
    stats["div_pending"] = sum(len(v) for v in state.get("div_queue", {}).values())
    state["summary"] = {**stats, "pending": pending, "companies": len(members),
                        "listed_total": sum(1 for c in members if comps.get(c, {}).get("listed")),
                        "at": _now().isoformat(timespec="seconds")}
    _save(STATE, state)
    log.info("Temel analiz: %s", state["summary"])
    return state["summary"]


# ---- Fiyatlar ve metrikler ----

PRICES = FIN / "_prices.json"
SCREEN = FIN / "_screen.json"


def update_prices(codes: list[str]) -> bool:
    """Evrenin son kapanışları (Yahoo, toplu indirme). Yalnız son fiyat ve tarih saklanır."""
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        return False
    for i in range(0, len(codes), 100):                    # 100'erli parçalar
        part = codes[i:i + 100]
        try:
            df = yf.download(" ".join(f"{c}.IS" for c in part), period="5d", interval="1d",
                             group_by="ticker", auto_adjust=False, threads=True, progress=False)
        except Exception as e:
            log.warning("Temel analiz fiyatları alınamadı: %s", e)
            continue
        for c in part:
            try:
                ser = df[f"{c}.IS"]["Close"].dropna() if len(part) > 1 else df["Close"].dropna()
            except (KeyError, TypeError):
                continue
            if len(ser):
                out[c] = {"price": round(float(ser.iloc[-1]), 4), "date": str(ser.index[-1].date())}
    if out:
        _save(PRICES, {"updated": _now().isoformat(timespec="seconds"), "p": out})
    return bool(out)


def merge_divs(lst: list[dict], d: dict) -> list[dict]:
    """Aynı karar tarihli bildirimlerden (YK önerisi → GK sonucu, güncellemeler) yalnız en yenisi kalır."""
    by: dict[str, dict] = {}
    for x in lst + [d]:
        k = x.get("decision") or f"idx{x.get('idx')}"
        if k not in by or x.get("idx", 0) > by[k].get("idx", 0):
            by[k] = x
    return sorted(by.values(), key=lambda x: (x.get("decision") or "", x.get("idx", 0)), reverse=True)


def div_summary(evs: list[dict], price: float | None) -> dict | None:
    """Son 13 ayın en yeni kar payı kararı: brüt/net, hak kullanım günleri, verim."""
    cutoff = (date.today() - timedelta(days=400)).isoformat()
    cur = next((d for d in evs if (d.get("decision") or "") >= cutoff), None)
    if not cur:
        return None
    if cur.get("status") == "yok":
        return {"status": "yok", "decision": cur.get("decision")}
    today = date.today().isoformat()
    exs = [i["ex"] for i in cur.get("installments") or [] if i.get("ex")]
    nxt = next((x for x in sorted(exs) if x >= today), None)
    return {"status": cur.get("status"), "decision": cur.get("decision"), "gross": cur.get("gross"), "net": cur.get("net"),
            "payout": cur.get("payout"), "ex": exs, "next_ex": nxt, "idx": cur.get("idx"),
            "yield": round(cur["gross"] / price, 4) if cur.get("gross") and price else None}


def build_metrics() -> int:
    """Tüm şirketlerin oranları/skorları → şirket dosyasına `metrics`, özet tablo → _screen.json."""
    from . import metrics as M
    uni = {m["code"]: m for m in _load(UNIVERSE, {}).get("members", [])}
    prices = _load(PRICES, {}).get("p", {})
    divs = _load(DIVS, {})
    rows, docs = [], {}
    for p in sorted(FIN.glob("[A-Z0-9]*.json")):
        doc = _load(p, None)
        if not doc:
            continue
        code = doc.get("code") or p.stem
        try:
            m = M.company(doc, (prices.get(code) or {}).get("price"))
        except Exception:
            log.exception("Metrik hesaplanamadı: %s", code)
            m = None
        docs[code] = (p, doc)
        if m:
            rows.append({"code": code, "sector": uni.get(code, {}).get("sector"), "m": m})
    M.finalize(rows)
    screen = []
    for row in rows:
        p, doc = docs[row["code"]]
        doc["metrics"] = row["m"]
        _save(p, doc)
        m = row["m"]
        screen.append({
            "code": row["code"], "title": doc.get("title"), "sector": row["sector"], "period": m["period"],
            "price": m["valuation"].get("price"), "mcap": m["valuation"].get("mcap"),
            "t": m.get("template", "sanayi"), "idx": uni.get(row["code"], {}).get("idx") or [],
            "r": m["ratios"], "v": {k: v for k, v in m["valuation"].items() if k not in ("shares",)},
            "cat": m["categories"], "quality": m["quality"], "valuation_score": m["valuation_score"],
            "overall": m["overall"], "grade": m["grade"], "z": m["altman_z2"], "f": m["piotroski"],
            "mscore": m["beneish_m"], "intrinsic": m.get("intrinsic"), "potential": m.get("potential"),
            "crit": {k: [c["pass"], c["total"], c["known"], [v for _, v in c["items"]]] for k, c in m["criteria"].items()},
            "div": div_summary(divs.get(row["code"], []), m["valuation"].get("price")),
        })
    done = {r["code"] for r in rows}
    out_of_scope, pending = [], []
    for c, u in uni.items():
        if c in done:
            continue
        d = docs.get(c, (None, None))[1]
        item = {"code": c, "title": u.get("title"), "sector": u.get("sector")}
        (out_of_scope if d and d.get("template") == "finansal" else pending).append(item)
    _save(SCREEN, {"updated": _now().isoformat(timespec="seconds"), "rows": screen, "out_of_scope": out_of_scope, "pending": pending,
                   "criteria_labels": {k: [lbl for lbl, _ in c["items"]] for row in rows for k, c in row["m"]["criteria"].items()}})
    return len(screen)
