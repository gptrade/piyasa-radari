import numpy as np
import pandas as pd

from radar import guc as G


def _px(n_stocks=40, days=400, seed=1, drift=0.0005):
    rnd = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=days).date
    rows = []
    for k in range(n_stocks):
        p = 10.0
        for d in dates:
            p *= np.exp(rnd.normal(drift, 0.02))
            rows.append((f"S{k:02d}", d, p, p, 1000))
    b = 100.0
    for d in dates:
        b *= np.exp(rnd.normal(drift, 0.01))
        rows.append(("XU100", d, b, b, 0))
    return pd.DataFrame(rows, columns=["sym", "date", "close", "adj", "volume"])


def _members(n=40):
    return [{"code": f"S{k:02d}", "sector": f"SEK{k % 4}"} for k in range(n)]


def test_clean_prices_removes_unadjusted_split():
    idx = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    adj = pd.DataFrame({"A": [10.0, 10.5, 5.25, 5.5]}, index=idx)      # 2:1 bedelsiz Yahoo'da düzeltilmemiş
    clean, ret = G.clean_prices(adj)
    assert ret["A"].iloc[2] == 0.0
    assert abs(clean["A"].iloc[-1] - 10.5 * 5.5 / 5.25) < 1e-9


def test_clean_index_rescales_redenomination():
    s = pd.Series([1_000_000.0, 1_010_000.0, 10_200.0, 10_300.0], index=pd.date_range("2020-07-23", periods=4))
    c = G.clean_index(s)
    assert abs(c.iloc[1] / c.iloc[0] - 1.01) < 1e-9 and abs(c.iloc[2] / c.iloc[1] - 1) < 0.02


def test_build_end_to_end_and_holiday_rows():
    px = _px()
    d = G.build(px, _members())
    s = d["series"]
    assert len(s["d"]) > 100 and s["adv"][-1] + s["dec"][-1] > 30
    assert 0 <= s["p50"][-1] <= 1 and d["regime"]["state"] in G_STATES
    assert len(d["sectors"]) == 4 and all(x["quad"] in ("lider", "zayif", "geride", "iyilesen") for x in d["sectors"])
    assert sorted(x["rank"] for x in d["sectors"])[0] == 1
    assert d["stocks"][0]["rs"] >= d["stocks"][-1]["rs"] and 1 <= d["stocks"][-1]["rs"] <= 99
    # tatil artığı: yalnız birkaç hissede kayıt olan gün atılır, ertesi gün getirileri bozulmaz
    last = pd.Timestamp(px.date.max())
    extra = px[px.date == px.date.max()].head(3).assign(date=(last + pd.Timedelta(days=1)).date())
    nxt = px[px.date == px.date.max()].assign(date=(last + pd.Timedelta(days=2)).date())
    nxt[["close", "adj"]] = nxt[["close", "adj"]].mul(np.where(np.arange(len(nxt)) % 2, 1.02, 0.99), axis=0)
    d2 = G.build(pd.concat([px, extra, nxt]), _members())
    assert d2["series"]["adv"][-1] + d2["series"]["dec"][-1] > 0


G_STATES = {"boga", "duzeltme", "ayi", "dip", "toparlanma"}


def test_thrust_detected():
    idx = pd.bdate_range("2024-01-01", periods=60)
    adr = [0.2] * 30 + [0.95] * 30
    b = pd.DataFrame({"adr": adr}, index=idx)
    t = G.thrusts(b)
    assert len(t) == 1 and pd.Timestamp(t[0]) > idx[30]


def test_quad_and_trend_template():
    assert G.quad(101, 101) == "lider" and G.quad(101, 99) == "zayif" and G.quad(99, 99) == "geride" and G.quad(99, 101) == "iyilesen"
    up = pd.Series(np.linspace(10, 30, 300))
    n, items = G.trend_template(up)
    assert n == 7 and all(items)
    assert G.trend_template(pd.Series(np.linspace(30, 10, 300)))[0] <= 2
