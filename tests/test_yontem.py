import math
import random
from datetime import date

from radar import yontem as Y


def test_known_at_uses_publish_else_deadline():
    assert Y.known_at({"published": "2024-05-08T18:10"}, "2024/03", {}) == date(2024, 5, 8)
    assert Y.known_at({"idx": 5}, "2024/03", {"5": "2024-04-30T09:00"}) == date(2024, 4, 30)
    assert Y.known_at({}, "2024/12", {}) == date(2025, 3, 12)      # yıl sonu +71 gün
    assert Y.known_at({}, "2024/06", {}) == date(2024, 8, 30)      # 2. çeyrek +61 gün


def test_raw_price_undoes_later_split_and_split_factor():
    daily = {"X": {"d": ["2020-01-31", "2020-02-28", "2020-03-31"], "c": [5.0, 5.2, 5.0], "a": [5.0, 5.2, 5.0],
                   "v": [100, 100, 100], "s": [("2020-03-15", 2.0)]}}
    px = Y.prepare_prices(daily)["X"]
    assert px["raw"]["2020-01"] == 10.0 and px["raw"]["2020-03"] == 5.0     # bedelsiz öncesi gerçek fiyat
    assert px["tv"]["2020-01"] == 500.0
    assert Y.split_factor(px["splits"], date(2019, 12, 31), date(2020, 3, 31)) == 2.0
    assert Y.split_factor(px["splits"], date(2020, 3, 31), date(2020, 6, 30)) == 1.0


def test_nw_t_and_rank():
    m, t = Y.nw_t([0.01] * 10 + [0.012] * 10)
    assert abs(m - 0.011) < 1e-12 and t > 10
    r = Y.rank01({"a": 1, "b": 2, "c": 2, "d": 3})
    assert r["a"] == 0 and r["d"] == 1 and r["b"] == r["c"] == 0.5


def _panel(signal_beta, months=60, n=100, seed=3):
    rnd = random.Random(seed)
    panel = {}
    for i in range(months):
        m = Y._madd("2018-01", i)
        rows = {}
        for k in range(n):
            x = rnd.gauss(0, 1)
            rows[f"S{k}"] = {"x": x, "r": signal_beta * x + rnd.gauss(0, 0.08), "fin": False}
        panel[m] = rows
    return panel


def test_evaluate_finds_planted_signal_and_rejects_noise():
    good = Y.evaluate(_panel(0.01), "x", "all", {}, {})
    assert good["verdict"] == "guclu" and good["ls"] > 0.015 and good["quint"][4] > good["quint"][0]
    noise = Y.evaluate(_panel(0.0), "x", "all", {}, {})
    assert noise["verdict"] in ("yok", "umut", "zayif_ters")
    bad = Y.evaluate(_panel(-0.01), "x", "all", {}, {})
    assert bad["verdict"] == "ters"
    short = Y.evaluate(_panel(0.01, months=12), "x", "all", {}, {})
    assert short["verdict"] == "yetersiz"


def test_ties_do_not_empty_buckets():
    panel = _panel(0.0, months=30)
    for rows in panel.values():
        for k, s in enumerate(rows.values()):
            s["x"] = 0.0 if k < 60 else s["x"]          # temettüsüzler gibi çok sayıda eşit değer
    assert Y.evaluate(panel, "x", "all", {}, {})["n"] == 30


def test_pb_residual_prefers_cheap_for_given_roe():
    sig = {f"S{k}": {"bp": 1 / math.exp(0.5 + 2 * (k % 10) / 10), "roe": (k % 10) / 10} for k in range(40)}
    sig["CHEAP"] = {"bp": 1 / math.exp(0.5), "roe": 0.9}       # yüksek ROE, düşük PD/DD
    res = Y.pb_residual(sig)
    assert res["CHEAP"] == max(res.values())
