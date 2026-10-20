from datetime import date

import numpy as np

from radar.fundamentals import bankrate as br

PERIODS = [f"{y}/{m:02d}" for y in (2024, 2025, 2026) for m in (3, 6, 9, 12)][:10]
RATES = [50, 50, 50, 48, 45, 44, 46, 43, 40, 38]


def _doc(code, a_beta, f_beta, ta=1000.0, noise=0.0, seed=0):
    """Sentetik banka: getiri = 4 + a_beta·r, maliyet = 1 + f_beta·r (yıllık %, ortalama aktife göre)."""
    rng = np.random.default_rng(seed)
    n = len(PERIODS)
    tas = [ta] * n
    ii, ie = [], []
    for r in RATES:
        y = 4 + a_beta * r + rng.normal(0, noise)
        f = 1 + f_beta * r + rng.normal(0, noise)
        ii.append(y / 100 * ta / 4)
        ie.append(-f / 100 * ta / 4)
    q = {"int_inc": ii, "int_exp": ie, "nii": [a + b for a, b in zip(ii, ie)], "net_parent": [5.0] * n, "tax": [-1.0] * n, "pretax": [4.0] * n}
    return {"code": code, "title": code, "template": "banka",
            "series": {"periods": PERIODS, "q": q, "bs": {"total_assets": tas, "equity_parent": [100.0] * n}}}


def _rq(lag=False):
    # çeyrek ortalaması: lag=True ise r1 = önceki çeyrek
    return dict(zip(PERIODS, map(float, RATES)))


def test_quarter_avg_and_key():
    d = [(date(2026, 1, 5), 40.0), (date(2026, 3, 30), 38.0), (date(2026, 4, 2), 37.0)]
    q = br.quarter_avg(d)
    assert br.qkey(date(2026, 2, 1)) == "2026/03" and br.qkey(date(2026, 12, 31)) == "2026/12"
    assert q == {"2026/03": 39.0, "2026/06": 37.0}


def test_observations_annualised_ratios():
    obs = br.observations(_doc("A", 0.5, 0.8), _rq())
    assert len(obs) == len(PERIODS) - 1                      # ilk dönemin önceki çeyreği yok
    o = obs[0]
    assert abs(o["y"] - (4 + 0.5 * RATES[1])) < 1e-9 and abs(o["f"] - (1 + 0.8 * RATES[1])) < 1e-9
    assert o["r0"] == RATES[1] and o["r1"] == RATES[0]


def test_pooled_recovers_common_beta():
    rq = _rq()
    obs = {c: br.observations(_doc(c, 0.5, 0.8, seed=i), rq) for i, c in enumerate("ABC")}
    bA, _ = br.pooled(obs, "y")
    bL, _ = br.pooled(obs, "f")
    assert abs(bA.sum() - 0.5) < 1e-6 and abs(bL.sum() - 0.8) < 1e-6


def test_shrink_moves_noisy_toward_pool():
    b, bp = np.array([1.0, 0.0]), np.array([0.0, 0.0])
    tight = br.shrink(b, np.diag([1e-4, 1e-4]), bp, np.array([0.01, 0.01]))
    loose = br.shrink(b, np.diag([1.0, 1.0]), bp, np.array([0.01, 0.01]))
    assert tight[0] > 0.95 and loose[0] < 0.05


def test_compute_signs_and_interval_order():
    rq = _rq()
    docs = [_doc("LIAB", 0.4, 0.9, noise=0.05, seed=1), _doc("ASSET", 0.9, 0.4, noise=0.05, seed=2), _doc("MID", 0.6, 0.6, noise=0.05, seed=3)]
    res = br.compute(docs, rq, policy_now=38.0, expect=30.0, screen={"LIAB": {"mcap": 500.0}})
    by = {b["code"]: b for b in res["banks"]}
    assert res["delta_pp"] == -8.0
    # fonlaması daha hassas banka faiz indiriminde kazanır, aktifi hassas olan kaybeder
    assert by["LIAB"]["y1"] < 0 < by["ASSET"]["y1"]
    assert by["LIAB"]["scenario"]["dnim_bp"] > 0 > by["ASSET"]["scenario"]["dnim_bp"]
    for b in res["banks"]:
        s = b["scenario"]
        assert s["lo_bp"] <= s["dnim_bp"] <= s["hi_bp"]
    assert by["LIAB"]["scenario"]["mcap_pct"] is not None and by["ASSET"]["scenario"]["mcap_pct"] is None
    assert by["LIAB"]["tax_rate"] == 0.25
    assert [b["code"] for b in res["banks"]] == sorted(by, key=lambda c: by[c]["y1"])


def test_compute_sample_start_and_minimum():
    rq = _rq()
    docs = [_doc(c, 0.5, 0.7, noise=0.05, seed=i) for i, c in enumerate("ABC")]
    assert br.compute(docs, rq, 38.0, 30.0, start="2026/03").get("error")   # çok az çeyrek kalır
    full = br.compute(docs, rq, 38.0, 30.0)
    assert all(b["n"] == len(PERIODS) - 1 for b in full["banks"])


def test_dedupe_banks_drops_asset_managers_and_share_classes():
    def d(code, title, n):
        return {"code": code, "title": title, "series": {"periods": PERIODS[:n]}}
    out = br.dedupe_banks([d("ISCTR", "TÜRKİYE İŞ BANKASI A.Ş.", 10), d("ISATR", "TÜRKİYE İŞ BANKASI A.Ş.", 6),
                           d("BRKVY", "BİRİKİM VARLIK YÖNETİM A.Ş.", 9), d("ICBCT", "ICBC TURKEY BANK A.Ş.", 8)])
    assert [x["code"] for x in out] == ["ICBCT", "ISCTR"]
