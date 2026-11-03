from datetime import datetime

import numpy as np
import pandas as pd

from radar import bbstudy as B


def _raw(t, ds):
    return [{"tickers": t, "publish_date": d, "quantity": 100, "price": 10, "pct_this_transaction": 0.01} for d in ds]


def test_episodes_split_on_gap():
    raw = _raw("AAA", ["02.01.2026 18:30:00", "10.01.2026 18:30:00", "01.03.2026 18:30:00"]) + _raw("BBB,BBB.E", ["05.01.2026 08:00:00"])
    raw.append({"tickers": "AAA", "publish_date": "03.01.2026 10:00:00", "quantity": None})     # program bildirimi
    e = B.episodes(raw)
    assert [(x["t"], x["n"]) for x in e] == [("AAA", 2), ("AAA", 1), ("BBB", 1)]
    assert abs(e[0]["pct"] - 0.02) < 1e-9


def test_entry_before_open_same_day_else_next():
    d = pd.bdate_range("2026-01-05", periods=5)
    assert B.entry_index(d, datetime(2026, 1, 6, 8, 0)) == 1
    assert B.entry_index(d, datetime(2026, 1, 6, 14, 0)) == 2
    assert B.entry_index(d, datetime(2026, 1, 3, 14, 0)) == 0          # hafta sonu → pazartesi
    assert B.entry_index(d, datetime(2026, 1, 9, 18, 0)) is None


def test_study_abnormal_return_vs_bench():
    d = pd.bdate_range("2025-01-01", periods=200)
    bench = pd.Series(np.linspace(100, 120, 200), index=d)
    cols = {}
    for k in range(12):
        s = bench.copy()
        s.iloc[60 + k:] *= 1.05            # girişten sonra +%5 fazla
        cols[f"S{k}"] = s
    clean = pd.DataFrame(cols)
    eps = [{"t": f"S{k}", "pub": d[60 + k - 1].to_pydatetime().replace(hour=18), "n": 1, "pct": 0.1, "amt": 1e6} for k in range(12)]
    # giriş = ertesi gün kapanışı (60+k): o gün zaten +%5 → fazla getiri sonrasında 0
    doc = B.study(clean, bench, eps)
    assert doc["n_events"] == 12 and abs(doc["res"]["a20"]["mean"]) < 1e-6
    eps2 = [{**e, "pub": e["pub"].replace(hour=8) - pd.Timedelta(days=1)} for e in eps]
    doc2 = B.study(clean, bench, eps2)
    assert doc2["res"]["a5"]["mean"] > 4 and doc2["path"]["n"] == 12 and len(doc2["path"]["mean"]) == 81
