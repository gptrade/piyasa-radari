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
from . import kapfin, series

log = logging.getLogger("radar.fundamentals")

FIN = DATA / "fin"
STATE = FIN / "_state.json"
UNIVERSE = FIN / "_universe.json"
CPI = FIN / "_cpi.json"
HISTORY_START = date(2023, 1, 1)
CPI_SERIES = "TP.GENENDEKS.T1"
EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
GAP = float(os.environ.get("FIN_GAP", 3.0))   # KAP istekleri arası bekleme (sn)
PAUSE_MIN = 10     # 429 sonrası ara
MAX_PERIODS = 20   # çalıştırma başına işlenecek dönem
MAX_REQ = 40       # çalıştırma başına liste isteği
MAX_EXPORTS = 9    # çalıştırma başına rapor indirme (KAP ~5 dakikada 10 indirmeden sonra 429 veriyor; radar 15 dk'da bir)
MAX_TRIES = 3


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


def next_jobs(state: dict) -> list[tuple[str, str]]:
    """(kod, dönem) çiftleri: önce en yeni dönemler (tüm şirketlerde), sonra geriye doğru."""
    jobs = [(code, pk) for code, per in state.get("queue", {}).items() for pk in per]
    return sorted(jobs, key=lambda j: (j[1], j[0]), reverse=True)


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

    for code, m in members.items():
        if left() < budget * 0.6 or spent() >= MAX_REQ:
            break
        if comps.get(code, {}).get("listed"):
            continue
        rows = kapfin.list_reports(m["oid"], HISTORY_START, date.today())
        if rows is None:
            continue
        for row in rows:
            if enqueue(state, code, row):
                stats["queued"] += 1
        comps.setdefault(code, {})["listed"] = date.today().isoformat()
        stats["listed"] += 1

    for code, pk in next_jobs(state):
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

def run(budget: float = 180.0, settings: dict | None = None) -> dict:
    t0 = time.monotonic()
    left = lambda: budget - (time.monotonic() - t0)  # noqa: E731
    state = _load(STATE, {})
    uni = _load(UNIVERSE, {})
    stats = {"listed": 0, "queued": 0, "processed": 0, "failed": 0}
    comps = state.setdefault("companies", {})

    if not uni.get("members") or _due(state, "universe", 24 * 7):
        idx = kapfin.fetch_indices()
        if idx.get("XU100"):
            sectors = kapfin.fetch_sectors()
            members = [{**m, **sectors.get(m["code"], {})} for m in idx["XU100"]]
            uni = {"index": "XU100", "updated": _now().isoformat(timespec="seconds"), "members": members}
            _save(UNIVERSE, uni)
    members = {m["code"]: m for m in uni.get("members", [])}
    only = {c.strip().upper() for c in os.environ.get("FIN_CODES", "").split(",") if c.strip()}
    if only:                                   # deneme/önizleme: yalnız seçili şirketler
        members = {c: m for c, m in members.items() if c in only}
    if not members:
        log.warning("Temel analiz: evren boş (KAP endeks sayfası okunamadı)")
        _save(STATE, state)
        return stats

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
    try:
        import yfinance as yf
        df = yf.download(" ".join(f"{c}.IS" for c in codes), period="5d", interval="1d",
                         group_by="ticker", auto_adjust=False, threads=False, progress=False)
    except Exception as e:
        log.warning("Temel analiz fiyatları alınamadı: %s", e)
        return False
    out = {}
    for c in codes:
        try:
            s = df[f"{c}.IS"]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if len(s):
            out[c] = {"price": round(float(s.iloc[-1]), 4), "date": str(s.index[-1].date())}
    if out:
        _save(PRICES, {"updated": _now().isoformat(timespec="seconds"), "p": out})
    return bool(out)


def build_metrics() -> int:
    """Tüm şirketlerin oranları/skorları → şirket dosyasına `metrics`, özet tablo → _screen.json."""
    from . import metrics as M
    uni = {m["code"]: m for m in _load(UNIVERSE, {}).get("members", [])}
    prices = _load(PRICES, {}).get("p", {})
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
            "r": m["ratios"], "v": {k: v for k, v in m["valuation"].items() if k not in ("shares",)},
            "cat": m["categories"], "quality": m["quality"], "valuation_score": m["valuation_score"],
            "overall": m["overall"], "grade": m["grade"], "z": m["altman_z2"], "f": m["piotroski"],
            "mscore": m["beneish_m"], "intrinsic": m.get("intrinsic"), "potential": m.get("potential"),
            "crit": {k: [c["pass"], c["total"], c["known"], [v for _, v in c["items"]]] for k, c in m["criteria"].items()},
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
                   "criteria_labels": {k: [lbl for lbl, _ in c["items"]] for k, c in rows[0]["m"]["criteria"].items()} if rows else {}})
    return len(screen)
