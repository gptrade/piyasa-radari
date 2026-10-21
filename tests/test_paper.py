from datetime import date

import numpy as np
import pandas as pd

from radar import paper as P


def _R(n_syms=12, days=30, r=0.01):
    dates = list(pd.bdate_range("2026-08-03", periods=days).date)
    R = pd.DataFrame({f"S{i}": [np.nan] + [r] * (days - 1) for i in range(n_syms)}, index=dates)
    return dates, R


def test_trades_and_nav_with_costs_and_breadth():
    dates, R = _R()
    ev = pd.DataFrame([{"id": f"e{i}", "sym": f"S{i}", "ts_eff": pd.Timestamp(f"{dates[2]} 08:00", tz="UTC"), "dir": 1, "mag": 0.5, "period": "2026/06"} for i in range(12)])
    tr = P.trades(ev, dates, R, 5)
    assert len(tr) == 12 and tr[0]["e"] == 2 and tr[0]["x"] == 7 and abs(tr[0]["gross"] - (1.01 ** 5 - 1)) < 1e-12
    d, c = P.nav(tr, dates, R, 0.002)
    assert c[3] == 12 and abs(d[3] - (0.01 - 0.002)) < 1e-12 and abs(d[5] - 0.01) < 1e-12 and abs(d[7] - (0.01 - 0.002)) < 1e-12
    assert d[8] == 0 and c[8] == 0
    # az pozisyon: nakitte kalınır
    d2, c2 = P.nav(tr[:3], dates, R, 0.0)
    assert not d2.any() and not c2.any()


def test_stats():
    s = P.stats(np.array([0.01, -0.02, 0.03, 0.0]))
    assert s["days"] == 4 and s["maxdd"] < 0 and abs(s["total"] - ((1.01 * 0.98 * 1.03) - 1) * 100) < 0.01
