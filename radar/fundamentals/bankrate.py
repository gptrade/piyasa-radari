"""Banka faiz duyarlılığı: politika faizindeki değişimin bankaların net faiz marjına (NIM) ve kârına etkisi.

`python -m radar.fundamentals.bankrate` — temel.yml iş akışında temel analiz adımından sonra (günde bir hesaplar).

Yöntem (bankaların kendi KAP mali tablolarından, yeniden fiyatlama dipnotu olmadan):
  1. Çeyreklik faiz gelirlerinden aktif getirisi  y = faiz gelirleri × 4 / ortalama toplam aktif,
     faiz giderlerinden fonlama maliyeti  f = −faiz giderleri × 4 / ortalama toplam aktif.
  2. Politika faizi: TCMB ağırlıklı ortalama fonlama maliyeti (TP.APIFON4), çeyrek ortalaması.
  3. Geçişkenlik (pass-through): y ve f, aynı çeyrek ve bir önceki çeyreğin faizine regresyon (dağıtılmış gecikme).
       y_t = a + b0·r_t + b1·r_{t−1}      f_t = c + d0·r_t + d1·r_{t−1}
     Mevduat kısa vadeli olduğu için fonlama maliyeti genelde aynı çeyrekte (d0), kredi getirisi gecikmeli (b1) uyum sağlar.
  4. Az gözlemli ya da gürültülü bankalar sektör (havuz, banka sabit etkili) katsayılarına doğru büzülür
     (ampirik Bayes: kesinlik ağırlıklı ortalama).
  5. Kalıcı Δr değişiminin 12 aylık NIM etkisi (adım değişim, 4 çeyrek ortalaması):
       ΔNIM_1y = [(b0 + 0,75·b1) − (d0 + 0,75·d1)] · Δr          uzun dönem: [(b0 + b1) − (d0 + d1)] · Δr
     Pozitif katsayı: faiz artışından kazanan (aktif duyarlı); negatif: faiz indiriminden kazanan (pasif duyarlı).
  6. Senaryo: piyasa beklentisi = TCMB Piyasa Katılımcıları Anketi 12 ay sonrası politika faizi (TP.PKAUO.S04.D.U)
     − güncel fonlama faizi. Etki: NII = ΔNIM × toplam aktif; net kâr = ΔNII × (1 − efektif vergi); ROE ve piyasa değerine oranı.
Sınırlar: TL/döviz ayrımı, swap ve TÜFE'ye endeksli menkul kıymetler ayrıca modellenmez; katsayılar 2023–2026 döneminin
ortalama davranışıdır (bilanço yapısı değişirse kayar). Çıktı: site/data/fin/_bankrate.json
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .. import http
from ..config import DATA

log = logging.getLogger("radar.bankrate")

FIN = DATA / "fin"
OUT = FIN / "_bankrate.json"
EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
POLICY = "TP.APIFON4"
EXPECT = "TP.PKAUO.S04.D.U"         # 12 ay sonrası TCMB politika faizi beklentisi (%)
EXPECT_CPI = "TP.PKAUO.S01.E.U"     # 12 ay sonrası yıllık TÜFE beklentisi (%)
START = date(2022, 10, 1)
MIN_OBS = 6
# Ana örneklem 2024'ten: 2023'ün sert faiz artışı döneminde KKM, menkul kıymet tesis zorunluluğu gibi makro ihtiyati
# düzenlemeler geçişkenliği bozdu; bugünkü (sadeleşmiş) rejime 2024 sonrası daha yakın. 2023 dahil sonuç sağlamlık için ayrıca verilir.
MAIN_START = "2024/03"
DEFAULT_TAX = 0.25
W1Y = 0.75                          # 4 çeyrek ortalamasında gecikmeli katsayının ağırlığı (3/4)


# ─────────────────────────────── veri
def _evds(codes: str, start: date, end: date, monthly: bool = False) -> list[dict]:
    key = os.environ.get("EVDS_API_KEY")
    if not key:
        return []
    url = f"{EVDS_URL}series={codes}&startDate={start:%d-%m-%Y}&endDate={end:%d-%m-%Y}&type=json" + ("&frequency=5" if monthly else "")
    r = http.get(url, headers={"key": key}, timeout=60)
    if r is None:
        return []
    try:
        return r.json().get("items") or []
    except ValueError:
        return []


def policy_daily(today: date) -> list[tuple[date, float]]:
    """Günlük fonlama faizi; EVDS bir istekte en çok ~1000 satır döndürdüğü için yıllık parçalar."""
    out, s = [], START
    while s <= today:
        e = min(today, date(s.year, 12, 31))
        for it in _evds(POLICY, s, e):
            v = it.get(POLICY.replace(".", "_"))
            if v not in (None, ""):
                out.append((datetime.strptime(it["Tarih"], "%d-%m-%Y").date(), float(v)))
        s = date(s.year + 1, 1, 1)
    return sorted(set(out))


def qkey(d: date) -> str:
    return f"{d.year}/{((d.month - 1) // 3 + 1) * 3:02d}"


def quarter_avg(daily: list[tuple[date, float]]) -> dict[str, float]:
    q = defaultdict(list)
    for d, v in daily:
        q[qkey(d)].append(v)
    return {k: round(sum(v) / len(v), 4) for k, v in q.items()}


def bank_docs(fin: Path | None = None) -> list[dict]:
    docs = []
    for p in sorted((fin or FIN).glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if d.get("template") == "banka" and d.get("series", {}).get("q", {}).get("int_inc"):
            docs.append(d)
    return docs


# ─────────────────────────────── model
def observations(doc: dict, rq: dict[str, float]) -> list[dict]:
    s = doc["series"]
    P, ta, ii, ie = s["periods"], s["bs"].get("total_assets") or [], s["q"].get("int_inc") or [], s["q"].get("int_exp") or []
    rows = []
    for t in range(1, len(P)):
        if t >= len(ta) or ii[t] is None or ie[t] is None or not ta[t] or not ta[t - 1]:
            continue
        r0, r1 = rq.get(P[t]), rq.get(P[t - 1])
        if r0 is None or r1 is None:
            continue
        a = (ta[t] + ta[t - 1]) / 2
        rows.append({"p": P[t], "y": ii[t] * 4 / a * 100, "f": -ie[t] * 4 / a * 100, "r0": r0, "r1": r1})
    return rows


def ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    X = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    dof = max(1, len(y) - X.shape[1])
    cov = (e @ e / dof) * np.linalg.pinv(X.T @ X)
    tss = (y - y.mean()) @ (y - y.mean())
    return b[1:], cov[1:, 1:], float(1 - e @ e / tss) if tss > 0 else 0.0


def pooled(obs: dict[str, list[dict]], key: str) -> tuple[np.ndarray, np.ndarray]:
    """Banka sabit etkili havuz regresyonu (her bankanın ortalaması çıkarılarak)."""
    ys, X = [], []
    for rows in obs.values():
        if len(rows) < MIN_OBS:
            continue
        y = np.array([r[key] for r in rows]); x = np.array([[r["r0"], r["r1"]] for r in rows])
        ys.append(y - y.mean()); X.append(x - x.mean(axis=0))
    y, x = np.concatenate(ys), np.vstack(X)
    b, *_ = np.linalg.lstsq(x, y, rcond=None)
    e = y - x @ b
    cov = (e @ e / max(1, len(y) - 2)) * np.linalg.pinv(x.T @ x)
    return b, cov


def shrink(b: np.ndarray, cov: np.ndarray, bp: np.ndarray, tau2: np.ndarray) -> np.ndarray:
    """Kesinlik ağırlıklı büzme: belirsiz banka katsayısı sektör katsayısına yaklaşır."""
    se2 = np.clip(np.diag(cov), 1e-6, None)
    w = tau2 / (tau2 + se2)
    return w * b + (1 - w) * bp


def lincomb(b: np.ndarray, cov: np.ndarray, w: list[float]) -> tuple[float, float]:
    w = np.array(w)
    return float(w @ b), float(math.sqrt(max(0.0, w @ cov @ w)))


def _last(xs: list, default=None):
    return next((x for x in reversed(xs or []) if x is not None), default)


def ttm(q: list) -> float | None:
    xs = [x for x in (q or [])[-4:] if x is not None]
    return sum(xs) if len(xs) == 4 else None


def compute(docs: list[dict], rq: dict[str, float], policy_now: float | None, expect: float | None,
            screen: dict[str, dict] | None = None, start: str = "") -> dict:
    obs = {d["code"]: [r for r in observations(d, rq) if r["p"] >= start] for d in docs}
    obs = {k: v for k, v in obs.items() if len(v) >= MIN_OBS}
    if len(obs) < 3:
        return {"banks": [], "error": "yeterli banka verisi yok"}
    pA, cA = pooled(obs, "y")
    pL, cL = pooled(obs, "f")
    fits = {}
    for code, rows in obs.items():
        x = np.array([[r["r0"], r["r1"]] for r in rows])
        fits[code] = (ols(np.array([r["y"] for r in rows]), x), ols(np.array([r["f"] for r in rows]), x))
    # bankalar arası gerçek katsayı varyansı (gözlem gürültüsü düşülerek), en az havuz belirsizliği kadar
    def tau2(i):
        bs = np.array([f[i][0] for f in fits.values()])
        se2 = np.array([np.diag(f[i][1]) for f in fits.values()])
        return np.clip(bs.var(axis=0) - se2.mean(axis=0), np.diag(cA if i == 0 else cL) * 4 + 1e-4, None)
    tA, tL = tau2(0), tau2(1)
    dr = round(expect - policy_now, 2) if expect is not None and policy_now is not None else None
    by_doc = {d["code"]: d for d in docs}
    banks = []
    for code, rows in obs.items():
        (bA, covA, r2A), (bL, covL, r2L) = fits[code]
        sA, sL = shrink(bA, covA, pA, tA), shrink(bL, covL, pL, tL)
        cov = covA + covL                                       # iki regresyon bağımsız varsayımı (fark için üst sınır)
        y1, y1se = lincomb(sA - sL, cov, [1, W1Y])
        lr, lrse = lincomb(sA - sL, cov, [1, 1])
        d = by_doc[code]; s = d["series"]
        ta = _last(s["bs"].get("total_assets")); eq = _last(s["bs"].get("equity_parent")) or _last(s["bs"].get("equity_total"))
        nii, net = ttm(s["q"].get("nii")), ttm(s["q"].get("net_parent"))
        tax, pre = ttm(s["q"].get("tax")), ttm(s["q"].get("pretax"))
        trate = min(0.4, max(0.0, -tax / pre)) if tax is not None and pre and pre > 0 else DEFAULT_TAX
        mc = (screen or {}).get(code, {}).get("mcap")

        def scen(delta):
            if delta is None or not ta:
                return None
            dnim = y1 * delta                                   # yüzde puan
            dnii = dnim / 100 * ta
            dnet = dnii * (1 - trate)
            return {"dnim_bp": round(dnim * 100, 1), "dnii": round(dnii), "nii_pct": round(dnii / nii * 100, 1) if nii and nii > 0 else None,
                    "net_pct": round(dnet / net * 100, 1) if net and net > 0 else None, "roe_pp": round(dnet / eq * 100, 2) if eq else None,
                    "mcap_pct": round(dnet / mc * 100, 2) if mc else None,
                    **dict(zip(("lo_bp", "hi_bp"), sorted([round((y1 - 1.645 * y1se) * delta * 100, 1), round((y1 + 1.645 * y1se) * delta * 100, 1)])))}

        nim_q = [round((r["y"] - r["f"]), 3) for r in rows]
        banks.append({
            "code": code, "name": d.get("title"), "n": len(rows), "period": rows[-1]["p"],
            "asset": {"b0": round(float(sA[0]), 3), "b1": round(float(sA[1]), 3), "raw": [round(float(x), 3) for x in bA], "r2": round(r2A, 2)},
            "liab": {"b0": round(float(sL[0]), 3), "b1": round(float(sL[1]), 3), "raw": [round(float(x), 3) for x in bL], "r2": round(r2L, 2)},
            "y1": round(y1, 4), "y1_se": round(y1se, 4), "lr": round(lr, 4), "lr_se": round(lrse, 4),
            "lag_gap": round(float(sL[0] - sA[0]), 3),             # aynı çeyrekte fonlama, getiriden ne kadar hızlı uyuyor
            "ta": ta, "equity": eq, "nii_ttm": nii, "net_ttm": net, "tax_rate": round(trate, 3), "mcap": mc,
            "nim": nim_q[-1] if nim_q else None,
            "scenario": scen(dr), "per100": scen(1.0),
            "series": {"p": [r["p"] for r in rows], "y": [round(r["y"], 2) for r in rows], "f": [round(r["f"], 2) for r in rows],
                       "r": [r["r0"] for r in rows]},
        })
    banks.sort(key=lambda b: b["y1"])
    return {"pool": {"asset": [round(float(x), 3) for x in pA], "liab": [round(float(x), 3) for x in pL],
                     "y1": round(float((pA[0] + W1Y * pA[1]) - (pL[0] + W1Y * pL[1])), 4)},
            "delta_pp": dr, "banks": banks}


def run(today: date | None = None, force: bool = False) -> dict | None:
    today = today or date.today()
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        old = {}
    docs = bank_docs()
    periods = max((d["series"]["periods"][-1] for d in docs), default="")
    if not force and old.get("date") == today.isoformat() and old.get("periods") == periods:
        return old
    daily = policy_daily(today)
    if not daily:
        log.warning("Banka faiz duyarlılığı: EVDS fonlama faizi alınamadı")
        return old or None
    rq = quarter_avg(daily)
    exp_rows = _evds(f"{EXPECT}-{EXPECT_CPI}", today - timedelta(days=120), today, monthly=True)
    ex = [r for r in exp_rows if r.get(EXPECT.replace(".", "_"))]
    expect = float(ex[-1][EXPECT.replace(".", "_")]) if ex else None
    exp_cpi = float(ex[-1][EXPECT_CPI.replace(".", "_")]) if ex and ex[-1].get(EXPECT_CPI.replace(".", "_")) else None
    try:
        scr = {r["code"]: r for r in json.loads((FIN / "_screen.json").read_text(encoding="utf-8")).get("rows", [])}
    except (FileNotFoundError, ValueError):
        scr = {}
    res = compute(docs, rq, daily[-1][1], expect, scr, start=MAIN_START)
    full = compute(docs, rq, daily[-1][1], expect, scr)
    fb = {b["code"]: b for b in full.get("banks", [])}
    for b in res.get("banks", []):                                # sağlamlık: 2023 dahil örneklemle aynı ölçüler
        f = fb.get(b["code"])
        b["full"] = {"n": f["n"], "y1": f["y1"], "y1_se": f["y1_se"], "scenario": f["scenario"]} if f else None
    res["sample"] = {"main": MAIN_START, "full_pool": full.get("pool")}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "date": today.isoformat(), "periods": periods,
           "policy": {"now": daily[-1][1], "date": daily[-1][0].isoformat(), "expect_12m": expect, "expect_cpi_12m": exp_cpi,
                      "expect_date": ex[-1]["Tarih"] if ex else None, "quarters": rq,
                      "source": "TCMB EVDS: TP.APIFON4 (ağırlıklı ortalama fonlama maliyeti), TP.PKAUO.S04.D.U (Piyasa Katılımcıları Anketi)"},
           **res}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Banka faiz duyarlılığı: %d banka, beklenen Δr %s puan", len(res.get("banks", [])), res.get("delta_pp"))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
