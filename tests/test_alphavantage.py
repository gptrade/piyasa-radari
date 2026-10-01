import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from radar import scorecard as sc
from radar.config import Stock
from radar.models import UTC, iso
from radar.sources import alphavantage as av, tr_official

US = [Stock("AAPL", "Apple", "US", []), Stock("MSFT", "Microsoft", "US", [])]
PAYLOAD = {"feed": [
    {"title": "Apple cut", "url": "https://n/1", "time_published": "20261001T180050", "source": "Benzinga", "summary": "s",
     "ticker_sentiment": [{"ticker": "AAPL", "relevance_score": "0.81", "ticker_sentiment_score": "-0.412"},
                          {"ticker": "MSFT", "relevance_score": "0.05", "ticker_sentiment_score": "0.3"},
                          {"ticker": "GOOG", "relevance_score": "0.9", "ticker_sentiment_score": "0.3"}]},
    {"title": "old", "url": "https://n/2", "time_published": "20260101T000000",
     "ticker_sentiment": [{"ticker": "AAPL", "relevance_score": "0.9", "ticker_sentiment_score": "0.5"}]},
]}


def test_to_items_relevance_and_scores():
    items = av.to_items(PAYLOAD, US, datetime(2026, 9, 1, tzinfo=UTC))
    assert len(items) == 1
    i = items[0]
    assert i.tickers == ["AAPL"] and i.extra == {"av": {"AAPL": -0.412}}            # MSFT ilgisiz, GOOG listede yok
    assert i.source == "Benzinga · Alpha Vantage" and i.published.startswith("2026-10-01T18:00")


def test_rotation_and_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(tr_official, "STATE_FILE", tmp_path / "st.json")
    t = [datetime(2026, 10, 1, 9, tzinfo=UTC)]
    monkeypatch.setattr(av, "now_utc", lambda: t[0])
    cfg = {"interval_min": 60, "max_per_day": 3}
    got = []
    for h in range(6):
        t[0] = datetime(2026, 10, 1, 9 + h, tzinfo=UTC)
        got.append(av.next_symbol(US, cfg))
        got.append(av.next_symbol(US, cfg))                                            # aynı saatte ikinci istek yok
    assert got == ["AAPL", None, "MSFT", None, "AAPL", None, None, None, None, None, None, None]
    t[0] = datetime(2026, 10, 2, 9, tzinfo=UTC)                                        # yeni gün: sayaç sıfır
    assert av.next_symbol(US, cfg) == "MSFT"


def test_av_graded_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "ARCHIVE", tmp_path / "s.json")
    monkeypatch.setattr(sc, "SCORE", tmp_path / "c.json")
    monkeypatch.setattr(sc, "now_utc", lambda: datetime(2026, 10, 10, 12, tzinfo=UTC))
    days = [datetime(2026, 9, 28, tzinfo=ZoneInfo("America/New_York")) + timedelta(days=i) for i in range(6)]
    px = {"AAPL": {"market": "US", "daily": [[int(d.timestamp()), 100 - i] for i, d in enumerate(days)], "intraday": []},
          "_SPX": {"market": "US", "daily": [[int(d.timestamp()), 10] for d in days], "intraday": []}}
    item = {"id": "a1", "tickers": ["AAPL"], "market": "US", "published": iso(datetime(2026, 9, 29, 20, tzinfo=UTC)),
            "source": "Benzinga · Alpha Vantage", "source_type": "news", "event": "analyst", "title": "Apple cut",
            "extra": {"av": {"AAPL": -0.41}, "mx": {"AAPL": 0.43}}}
    assert sc.update([item], px, {"AAPL"})["added"] == 2                                # AI yok: iki dış görüş
    item["extra"]["av"]["AAPL"] = -0.41
    assert sc.update([item], px, {"AAPL"})["added"] == 0                                # tekrar eklenmez
    card = json.loads((tmp_path / "c.json").read_text())["scopes"]["US"]["all"]
    assert card["total"]["h1"]["n"] == 0                                                # ana toplama karışmaz
    pv = {g["g"]: g["h1"]["hit"] for g in card["dims"]["pv"]}
    assert pv == {"Alpha Vantage": 100.0, "Marketaux": 0.0}
