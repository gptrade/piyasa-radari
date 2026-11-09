import numpy as np
import pandas as pd

from radar import korku


def _frame(n=900, crash=False):
    ix = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(1)
    r = rng.normal(0.0008, 0.01, n)
    if crash:
        r[-40:] = rng.normal(-0.012, 0.03, 40)
    bench = pd.Series(100 * np.exp(np.cumsum(r)), index=ix)
    up = pd.Series(np.clip(0.5 + r * 20, 0, 1), index=ix)
    b = pd.DataFrame({"nh": (up * 40).round(), "nl": ((1 - up) * 40).round(), "nhl_n": 400, "upv": up}, index=ix)
    usd = pd.Series(np.exp(np.cumsum(rng.normal(0.001, 0.003, n) + (np.r_[np.zeros(n - 40), np.full(40, 0.006)] if crash else 0))), index=ix)
    return b, bench, {"USDTRY": usd}


def test_crash_reads_fear_and_rally_reads_greed():
    d = korku.build(*_frame(crash=True))
    assert d["value"] < 25 and d["zone"] == "Aşırı korku"
    assert {c["key"] for c in d["components"]} >= {"mom", "nhl", "upv", "vol", "fx"}
    assert all(0 <= c["score"] <= 100 for c in d["components"])
    b, bench, ex = _frame()
    bench.iloc[-60:] *= np.linspace(1, 1.25, 60)
    b.loc[b.index[-30:], ["nh", "nl", "upv"]] = [60, 2, 0.8]
    d2 = korku.build(b, bench, ex)
    assert d2["value"] > 60


def test_zone_bounds_and_forward_table():
    assert korku.zone(10) == "Aşırı korku" and korku.zone(50) == "Nötr" and korku.zone(99.9) == "Aşırı açgözlülük"
    d = korku.build(*_frame(n=1300))
    assert [z["zone"] for z in d["zones"]] == [lbl for _, lbl in korku.ZONES]
    assert abs(sum(z["share"] for z in d["zones"]) - 1) < 0.01
