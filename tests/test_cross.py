import numpy as np
import pandas as pd

from radar import cross as C


def _df(n=1500, seed=2, trend=None):
    rnd = np.random.default_rng(seed)
    idx = pd.bdate_range("2019-01-01", periods=n)
    base = {"usdtry": 6, "eurtry": 7, "xu100": 100000, "gold": 1300, "brent": 60, "copper": 3, "us10y": 2.5, "dxy": 95, "spx": 2500, "vix": 18, "btc": 4000}
    out = {}
    for k, v in base.items():
        steps = rnd.normal(0, 0.01, n) + (trend or {}).get(k, 0)
        out[k] = (v + np.cumsum(steps)) if k == "us10y" else v * np.exp(np.cumsum(steps))
    df = pd.DataFrame(out, index=idx)
    df.loc[idx[min(700, n - 50)]:, "xu100"] /= 100          # 2020 tipi ölçek kırılması
    return df


def test_derive_rescales_index_and_builds_usd_and_gram():
    d = C.derive(_df())
    r = d["xu100"] / d["xu100"].shift(1)
    assert r.max() < 1.2 and r.min() > 0.8
    assert abs(d["gram"].iloc[-1] - d["gold"].iloc[-1] * d["usdtry"].iloc[-1] / C.GRAM) < 1e-6


def test_strip_doc_fields():
    s = C.strip_doc(C.derive(_df(200)))
    k = {i["k"]: i for i in s["items"]}
    assert "xu100usd" in k and k["us10y"]["chg_kind"] == "bp" and 20 <= len(k["usdtry"]["spark"]) <= 70


def test_regime_risk_on_when_equities_up_and_dollar_vix_down():
    up = {"spx": 0.004, "copper": 0.004, "btc": 0.004, "vix": -0.004, "dxy": -0.004, "us10y": -0.004}
    df = _df()
    tail = df.index[-30:]
    for k, t in up.items():
        df.loc[tail, k] = df.loc[tail[0], k] * (np.exp(np.cumsum(np.full(30, t * 6))) if k != "us10y" else 1) + (np.cumsum(np.full(30, t * 10)) if k == "us10y" else 0)
    d = C.regime_doc(df)
    assert d["state"] == "on" and d["score"] > 0.5
    assert set(d["backtest"]) == {"on", "mixed", "off"} and d["hist"]
