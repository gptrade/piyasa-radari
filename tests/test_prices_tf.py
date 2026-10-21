from datetime import datetime
from zoneinfo import ZoneInfo

from radar import prices as P

IST = ZoneInfo("Europe/Istanbul")


def ts(d, h, m=0):
    return int(datetime(2026, 10, d, h, m, tzinfo=IST).timestamp())


def test_4h_bars_aligned_to_session_and_auction_folded():
    h1 = [[ts(20, h), float(h), 1] for h in range(10, 19)] + [[ts(21, 10), 100.0, 1]]   # 10:00 … 18:00 (kapanış seansı), ertesi gün
    b4 = P.bars_4h(h1, "BIST")
    assert [b[1] for b in b4] == [13.0, 18.0, 100.0]
    b1 = P.bars_tf(h1, "BIST", 60)
    assert len(b1) == 9 and b1[-2][1] == 18.0          # 17:00 dilimine 18:00 kapanış barı katılır


def test_weekly_uses_local_date():
    # Yahoo BIST günlük barı yerel gece yarısında (UTC pazar 21:00) damgalı: pazartesi yeni haftaya düşmeli
    daily = [[ts(16, 0), 1.0], [ts(19, 0), 2.0], [ts(20, 0), 3.0]]       # Cuma, Pazartesi, Salı
    assert P._weekly(daily, IST) == [1.0, 3.0]


def test_ema_set_alignment_with_ema8():
    closes = [float(i) for i in range(1, 400)]
    st = P.ema_set(closes)
    assert st["align"] == "boğa" and set(st["ema"]) == {"8", "14", "34", "55", "200"}
    assert P.ema_set(closes[:10]) is None
