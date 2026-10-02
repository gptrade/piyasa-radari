from datetime import datetime
from zoneinfo import ZoneInfo

from radar.prices import EX_TZ, prev_close

IST = ZoneInfo("Europe/Istanbul")
ts = lambda *a: int(datetime(*a, tzinfo=IST).timestamp())
DAILY_WITH_TODAY = [[ts(2026, 9, 30), 51.55], [ts(2026, 10, 1), 52.45], [ts(2026, 10, 2), 53.10]]
DAILY_NO_TODAY = DAILY_WITH_TODAY[:2]
INTRA = [[ts(2026, 10, 1, 17, 55), 52.5], [ts(2026, 10, 2, 9, 55), 52.3], [ts(2026, 10, 2, 12, 0), 53.1]]


def test_today_bar_present():
    assert prev_close(DAILY_WITH_TODAY, INTRA, EX_TZ["BIST"]) == 52.45


def test_today_bar_missing_uses_yesterday_not_two_days_ago():
    assert prev_close(DAILY_NO_TODAY, INTRA, EX_TZ["BIST"]) == 52.45      # eski kod 51,55 veriyordu


def test_no_intraday_falls_back_to_daily():
    assert prev_close(DAILY_WITH_TODAY, [], EX_TZ["BIST"]) == 52.45
    assert prev_close([], INTRA, EX_TZ["BIST"]) is None
