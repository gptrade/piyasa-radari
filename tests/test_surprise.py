from datetime import date, datetime, timedelta, timezone

from radar import surprise as S


def test_release_date_moves_weekend_to_monday():
    assert S.release_date("2026-09") == date(2026, 10, 5)      # 3 Ekim 2026 cumartesi
    assert S.release_date("2026-10") == date(2026, 11, 3)      # salı
    assert S.release_date("2025-12") == date(2026, 1, 5)       # 3 Ocak 2026 cumartesi


def test_series_monthly_change_and_columns():
    items = [{"Tarih": "2026-8", "TP_TUKFIY2025_GENEL": "100", "TP_PKAUO_S01_A_U": "2.0"},
             {"Tarih": "2026-9", "TP_TUKFIY2025_GENEL": "102.5", "TP_PKAUO_S01_A_U": "2.1", "TP_PKAUO_S01_B_U": "1.8"},
             {"Tarih": "2026-10", "TP_PKAUO_S01_A_U": "1.9"}]
    exp, exp1, mom = S.series(items)
    assert mom == {"2026-09": 2.5} and exp["2026-10"] == 1.9 and exp1["2026-09"] == 1.8


def test_build_surprise_pending_and_reaction_stats():
    exp, mom, react = {}, {}, {}
    d = date(2022, 1, 1)
    ms = []
    for i in range(30):
        ym = f"{2022 + i // 12}-{i % 12 + 1:02d}"
        ms.append(ym)
        exp[ym] = 2.0
        s = (-1) ** i * 0.1 * (i % 7)
        mom[ym] = 2.0 + s
        react[S.release_date(ym).isoformat()] = {"xu": -2 * s, "xb": -3 * s}
    exp["2024-07"] = 1.5
    doc = S.build(exp, {"2024-06": 1.6}, mom, react)
    r = doc["rows"][-1]
    assert r["m"] == "2024-06" and r["sur"] == round(mom["2024-06"] - 2.0, 2) and "xu" in r
    assert doc["pending"]["m"] == "2024-07" and doc["pending"]["exp"] == 1.5 and doc["pending"]["src"] == "anket"
    assert doc["react"]["xb"]["ols"]["b"] == -3.0
    assert doc["stats"]["w12"]["n"] == 12


def test_pending_falls_back_to_previous_survey():
    doc = S.build({"2026-09": 2.0}, {"2026-09": 1.7}, {"2026-09": 2.2})
    assert doc["pending"] == {"m": "2026-10", "label": "Ekim 2026", "exp": 1.7, "src": "önceki anket (1 ay sonrası)", "rel": "2026-11-03"}


def test_due_hourly_on_release_day():
    now = datetime(2026, 11, 3, 9, tzinfo=timezone.utc)
    prev = {"generated": (now - timedelta(hours=2)).isoformat(), "pending": {"rel": "2026-11-03"}}
    assert S.due(prev, now)
    prev["pending"]["rel"] = "2026-12-03"
    assert not S.due(prev, now)
