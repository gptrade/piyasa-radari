import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from radar import anomaly
from radar.config import Stock
from radar.enrich import classify_event
from radar.models import iso, now_utc
from radar.notify import should_notify
from radar.scorecard import kind

IST = ZoneInfo("Europe/Istanbul")
GOZDE = Stock("GOZDE", "Gözde Girişim", "BIST", [])


def series(rets, start=100.0):
    d0 = datetime(2026, 6, 1, tzinfo=IST)
    px, out = start, [[int(d0.timestamp()), start]]
    for i, r in enumerate(rets, 1):
        px *= 1 + r / 100
        out.append([int((d0 + timedelta(days=i)).timestamp()), round(px, 4)])
    return out


def make_px(today_stock, today_idx, seed=1):
    rnd = random.Random(seed)
    idx_r = [rnd.gauss(0, 1) for _ in range(80)]
    stk_r = [1.0 * x + rnd.gauss(0, 1.5) for x in idx_r]
    idx_r.append(today_idx)
    stk_r.append(today_stock)
    return {"GOZDE": {"market": "BIST", "daily": series(stk_r), "change_pct": today_stock},
            "_XU100": {"market": "BIST", "daily": series(idx_r, 10000), "change_pct": today_idx}}


def test_market_move_is_not_anomaly():
    px = make_px(6.0, 5.5)                                     # endeksle birlikte yükseliş
    assert anomaly.anomaly_items([GOZDE], px, []) == []


def test_idiosyncratic_move_without_news_flags_once():
    px = make_px(9.0, 0.2)
    s = anomaly.stats(px["GOZDE"], px["_XU100"])
    assert 0.6 < s["beta"] < 1.4 and s["z"] > 4
    items = anomaly.anomaly_items([GOZDE], px, [])
    assert len(items) == 1
    it = items[0]
    assert it.analysis["sentiment"] == "bullish" and it.analysis["materiality"] == "high"
    assert "habersiz yükseliş · +%9,00" in it.title
    assert anomaly.anomaly_items([GOZDE], px, [])[0].id == it.id        # aynı gün aynı kimlik
    d = it.to_dict()
    assert classify_event(d) == "anomaly" and kind(d) == "Habersiz hareket"
    assert should_notify(it, {"anomaly": True}) and not should_notify(it, {"anomaly": False})


def test_disclosure_or_important_news_explains_move():
    px = make_px(-9.0, 0.0)
    recent = [{"tickers": ["GOZDE"], "published": iso(now_utc() - timedelta(hours=3)), "source_type": "disclosure", "tier": 1}]
    assert anomaly.anomaly_items([GOZDE], px, recent) == []
    weak = [{"tickers": ["GOZDE"], "published": iso(now_utc() - timedelta(hours=3)), "source_type": "social", "tier": 3,
             "analysis": {"materiality": "low"}}]
    items = anomaly.anomaly_items([GOZDE], px, weak)
    assert len(items) == 1 and "1 düşük önemli kayıt" in items[0].analysis["why"]
    old = [{"tickers": ["GOZDE"], "published": iso(now_utc() - timedelta(hours=40)), "source_type": "disclosure", "tier": 1}]
    assert len(anomaly.anomaly_items([GOZDE], px, old)) == 1             # 24 saatten eski bildirim açıklamaz


def test_small_move_below_floor_ignored():
    px = make_px(1.5, 0.0)
    assert anomaly.anomaly_items([GOZDE], px, [], {"z": 0.5, "min_move_pct": 2.0}) == []


def test_low_materiality_investigation_news_still_explains():
    px = make_px(9.0, 0.2)
    recent = [{"tickers": ["GOZDE"], "published": iso(now_utc() - timedelta(hours=2)), "source_type": "news", "tier": 3,
               "title": "GOZDE hakkında SPK soruşturması: idari para cezası", "analysis": {"materiality": "low"}}]
    assert anomaly.anomaly_items([GOZDE], px, recent) == []
