from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from radar import usmap as U


def test_members_parse_and_yahoo_symbol():
    ms = U.members()
    assert len(ms) > 490
    brk = [m for m in ms if m["code"].startswith("BRK")]
    assert brk and "-" in brk[0]["yf"] and all(m["sector"] for m in ms)


def test_build_returns_and_mcap():
    idx = pd.bdate_range("2025-11-03", "2026-11-03")
    px = pd.DataFrame({"AAA": np.linspace(100, 200, len(idx)), "BBB": np.linspace(50, 40, len(idx))}, index=idx)
    ms = [{"code": "AAA", "name": "A", "sector": "Energy"}, {"code": "BBB", "name": "B", "sector": "Utilities"}, {"code": "CCC", "name": "C", "sector": "Energy"}]
    d = U.build(px, ms, {"AAA": {"n": 10}})
    a = {r["code"]: r for r in d["stocks"]}
    assert d["n"] == 2 and a["AAA"]["mcap"] == 2000 and a["BBB"]["mcap"] is None
    ye = px.loc[px.index.year == 2025, "AAA"].iloc[-1]
    assert abs(a["AAA"]["ytd"] - (200 / ye - 1)) < 1e-4 and a["AAA"]["d1"] > 0 and a["BBB"]["w1"] < 0


def test_due_session_and_after_close():
    t = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)          # çarşamba, seans
    assert U.due({"generated": (t - timedelta(minutes=31)).isoformat()}, t)
    assert not U.due({"generated": (t - timedelta(minutes=10)).isoformat()}, t)
    night = datetime(2026, 11, 4, 22, 0, tzinfo=timezone.utc)
    assert U.due({"generated": datetime(2026, 11, 3, 23, tzinfo=timezone.utc).isoformat()}, night)
    assert not U.due({"generated": datetime(2026, 11, 4, 21, tzinfo=timezone.utc).isoformat()}, night)
