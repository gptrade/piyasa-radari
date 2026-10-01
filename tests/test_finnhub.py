from datetime import datetime

from radar.config import Stock, TickerMatcher
from radar.models import UTC
from radar.sources import Context, finnhub as fh

ST = Stock("AAPL", "Apple", "US", [])


def test_to_items_filters_and_maps():
    rows = [{"id": 1, "datetime": 1790000000, "headline": "Apple unveils", "source": "Reuters", "summary": "s", "url": "https://x/1"},
            {"id": 2, "datetime": 1700000000, "headline": "old", "source": "Yahoo", "url": "https://x/2"},
            {"id": 3, "datetime": 1790000000, "headline": "", "url": "https://x/3"}]
    items = fh.to_items(rows, ST, datetime(2026, 1, 1, tzinfo=UTC))
    assert len(items) == 1
    i = items[0]
    assert i.source == "Reuters · Finnhub" and i.tickers == ["AAPL"] and i.market == "US" and i.source_type == "news"


def test_collect_off_without_key(monkeypatch):
    for k in fh.ENVS:
        monkeypatch.delenv(k, raising=False)
    ctx = Context(settings={"sources": {}}, stocks=[ST], matcher=TickerMatcher([ST]), since=datetime(2026, 10, 1, tzinfo=UTC))
    assert fh.collect(ctx) == []
