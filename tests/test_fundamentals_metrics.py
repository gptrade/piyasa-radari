"""Oran/skor motoru: TRGYO'nun 6 dönemlik gerçek KAP verisi ve EVDS TÜFE'siyle, referans platform değerleri."""
import glob
import json
from pathlib import Path

import pytest

from radar.fundamentals import kapfin, metrics as M, series as S

FX = Path(__file__).parent / "fixtures" / "kapfin"


@pytest.fixture(scope="module")
def trgyo():
    cpi = json.loads((FX / "cpi.json").read_text())
    reps = {}
    for f in sorted(glob.glob(str(FX / "trgyo_*.html"))):
        if f.endswith("_b.html"):
            continue
        r = kapfin.parse_export(Path(f).read_bytes())
        reps[kapfin.period_key(r["year"], r["period"])] = r
    doc = {"code": "TRGYO", "currency": "TRY", "template": "sanayi", "reports": reps}
    doc["series"] = S.build(doc, cpi)
    return doc


def approx(a, b, tol):
    return a is not None and abs(a - b) <= tol


def test_q4_in_real_terms(trgyo):
    s = trgyo["series"]
    i = s["periods"].index("2025/12")
    # 4Ç25 hasılatı (yıllık − 9 ay, Aralık TL'si) → Haziran 2026 TL'sine taşınınca ~8,98 mr ₺
    real = s["q"]["revenue"][i] * s["cpi"][-1] / s["cpi"][i]
    assert approx(real, 8.98e9, 0.05e9)


def test_ratios_match_reference(trgyo):
    m = M.company(trgyo, 92.70)
    r, v = m["ratios"], m["valuation"]
    assert m["period"] == "2026/06"
    assert approx(r["roe"], 0.062, 0.001) and approx(r["roa"], 0.050, 0.001)
    assert approx(r["rev_growth"], 0.074, 0.001) and approx(r["ebitda_growth"], 0.282, 0.001)
    assert approx(r["net_growth"], -0.616, 0.001)
    assert approx(r["gross_margin"], 0.724, 0.001) and approx(r["ebitda_margin"], 0.686, 0.001)
    assert approx(r["core_margin"], 0.679, 0.001) and approx(r["net_margin"], 0.452, 0.001)
    assert approx(r["current"], 4.69, 0.01) and approx(r["debt_equity"], 0.28, 0.01)
    assert approx(r["interest_cov"], 11.51, 0.01) and approx(r["cfo_ni"], 1.16, 0.01)
    assert approx(r["asset_turnover"], 0.11, 0.005) and approx(r["net_debt_ebitda"], -0.26, 0.01)
    assert approx(v["pe"], 9.82, 0.01) and approx(v["pb"], 0.60, 0.01)
    assert approx(v["ev_ebitda"], 6.20, 0.01) and approx(v["ev_sales"], 4.25, 0.01)
    assert m["beneish_m"] == -2.88
    assert approx(m["altman_z2"], 7.1, 0.15)


def test_criteria_sets(trgyo):
    m = M.company(trgyo, 92.70)
    c = m["criteria"]
    assert (c["Benjamin Graham — Savunmacı Yatırımcı"]["pass"], c["Benjamin Graham — Savunmacı Yatırımcı"]["total"]) == (7, 8)
    assert c["Warren Buffett — Kalıcı Rekabet Avantajı"]["pass"] == 7
    assert c["Peter Lynch — Makul Fiyata Büyüme"]["pass"] == 3
    assert m["categories"]["Finansal Yapı"] == 100 and m["categories"]["Likidite"] == 100


def test_finalize_peer_valuation_and_grade(trgyo):
    base = M.company(trgyo, 92.70)

    def clone(price):
        m = json.loads(json.dumps(base))
        v = m["valuation"]
        k = price / 92.70
        for key in ("price", "mcap", "pe", "pb", "ps"):
            v[key] *= k
        v["ev"] = v["mcap"] + (base["valuation"]["ev"] - base["valuation"]["mcap"])
        v["ev_ebitda"] = base["valuation"]["ev_ebitda"] * v["ev"] / base["valuation"]["ev"]
        v["ev_sales"] = base["valuation"]["ev_sales"] * v["ev"] / base["valuation"]["ev"]
        return m
    rows = [{"code": c, "sector": "GYO", "m": clone(p)} for c, p in (("A", 60.0), ("B", 92.70), ("C", 140.0))]
    M.finalize(rows)
    a, b, c = (r["m"] for r in rows)
    assert a["valuation_score"] > b["valuation_score"] > c["valuation_score"]   # ucuz olan daha yüksek puan
    assert approx(b["intrinsic"], 92.70, 0.5)                                    # medyan şirket ≈ kendi fiyatı
    assert b["grade"] in "ABCDE" and b["overall"] == round(0.6 * b["quality"] + 0.4 * b["valuation_score"])


def test_bank_out_of_scope():
    assert M.company({"template": "finansal", "series": {"periods": ["2026/06"]}}, 10) is None


def test_tms29_and_cash_quality(trgyo):
    r = M.company(trgyo, 92.70)["ratios"]
    # TRGYO'nun 12A parasal pozisyonu zarar (−5,4 mr ₺): pay negatif, zarar hariç VÖK daha yüksek
    assert approx(r["mon_share"], -0.284, 0.001) and r["pbt_ex_mon_margin"] > r["net_margin"]
    assert approx(r["fcf_conv"], 0.661, 0.001)                       # SNA 9,48 / FAVÖK 14,34 mr ₺
    assert approx(r["rule40"], 0.074 + 0.686, 0.002)
    assert approx(r["ccc_chg"], -30.0, 0.1) and r["ccc"] > 0
    c = M.company(trgyo, 92.70)["criteria"]["Enflasyon Muhasebesi & Nakit Kalitesi"]
    assert (c["pass"], c["total"]) == (6, 6)


def test_pb_history_median_and_relative(trgyo):
    # ay sonu gerçek fiyatlar (bedelsiz düzeltmesi geri alınmış); TRGYO dönemleri 2025/03…2026/06
    hist = [["2025-03", 60.0], ["2025-06", 70.0], ["2025-09", 75.0], ["2025-12", 80.0], ["2026-03", 85.0], ["2026-06", 88.0]]
    m = M.company(trgyo, 92.70, hist)
    ph, v = m["pb_hist"], m["valuation"]
    assert ph["n"] >= 3 and ph["med"] > 0 and v["pb_med3"] == ph["med"]
    assert abs(v["pb_rel3"] - (v["pb"] / ph["med"] - 1)) < 1e-3
    assert M.company(trgyo, 92.70)["pb_hist"] is None and "pb_med3" not in M.company(trgyo, 92.70)["valuation"]


def test_raw_monthly_undoes_splits():
    import pandas as pd
    from radar.fundamentals import store
    idx = pd.to_datetime(["2025-01-30", "2025-01-31", "2025-02-28", "2025-03-31"])
    close = pd.Series([10.0, 10.0, 11.0, 12.0], index=idx)          # Yahoo: geriye dönük düzeltilmiş
    splits = pd.Series([0.0, 0.0, 2.0, 0.0], index=idx)             # Şubat sonu %100 bedelsiz
    out = store.raw_monthly(close, splits)
    assert out == [["2025-01", 20.0], ["2025-02", 11.0], ["2025-03", 12.0]]
