import numpy as np
import pandas as pd

from radar import eventstudy as S


def test_clustered_mean_inflates_se_for_same_day_events():
    x = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])
    indep = S.clustered_mean(x, np.array(list("abcdef")))
    same = S.clustered_mean(x, np.array(list("aaabbb")))
    assert indep[0] == same[0] == 0
    assert same[1] > indep[1] * 1.5


def test_build_rows_use_ew_for_bist_and_skip_admin():
    ev = pd.DataFrame([
        {"id": "a", "sym": "AAA", "market": "BIST", "type": "geri_alim", "dir": 1, "conf": None, "mat": None, "ts": pd.Timestamp("2026-10-01 08:00", tz="UTC"),
         "ts_eff": pd.Timestamp("2026-10-01 08:00", tz="UTC"), "cluster": "a", "subtype": "x", "title": "t", "url": "u"},
        {"id": "b", "sym": "AAA", "market": "BIST", "type": "idari", "dir": None, "conf": None, "mat": None, "ts": pd.Timestamp("2026-10-01 08:00", tz="UTC"),
         "ts_eff": pd.Timestamp("2026-10-01 08:00", tz="UTC"), "cluster": "b", "subtype": "", "title": "t", "url": ""}])
    ret = pd.DataFrame([{"id": "a", "sym": "AAA", "d0": "2026-09-30", "pre5": 0.1, "ar1": 9.0, "ae1": 1.0, "ar5": None, "ae5": None, "ar20": None, "ae20": None},
                        {"id": "b", "sym": "AAA", "d0": "2026-09-30", "pre5": 0.1, "ar1": 9.0, "ae1": 1.0, "ar5": None, "ae5": None, "ar20": None, "ae20": None}])
    d = S.build(ev, ret, None, ["AAA"], pd.Timestamp("2026-10-20", tz="UTC"))
    assert len(d["rows"]) == 1
    r = dict(zip(d["cols"], d["rows"][0]))
    assert r["a1"] == 1.0 and r["type"] == "geri_alim" and r["dir"] == 1
