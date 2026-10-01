from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from radar import scorecard as sc
from radar.config import Stock, TickerMatcher
from radar.models import iso
from radar.sources import Context, marketaux as mx

IST = ZoneInfo("Europe/Istanbul")
STOCKS = [Stock("AAPL", "Apple", "US", []), Stock("THYAO", "Türk Hava Yolları", "BIST", [])]
PAYLOAD = {"data": [
    {"uuid": "u1", "title": "Morgan Stanley Lowers Apple (AAPL) Price Target", "description": "d", "url": "https://g/1",
     "published_at": "2026-10-01T18:00:50.000000Z", "source": "gurufocus.com", "language": "en",
     "entities": [{"symbol": "AAPL", "sentiment_score": 0.427063}, {"symbol": "MSFT", "sentiment_score": 0.1}]},
    {"uuid": "u2", "title": "Turkish Airlines engine deal", "url": "https://g/2", "published_at": "2026-10-01T10:00:00.000000Z",
     "source": "reuters.com", "language": "en", "entities": [{"symbol": "THYAO.IS", "sentiment_score": None}]},
    {"uuid": "u3", "title": "unrelated", "url": "https://g/3", "published_at": "2026-10-01T10:00:00.000000Z",
     "entities": [{"symbol": "XYZ", "sentiment_score": 0.9}]},
]}


def test_to_items_maps_symbols_and_scores():
    items = mx.to_items(PAYLOAD, STOCKS, None)
    assert [i.tickers for i in items] == [["AAPL"], ["THYAO"]]
    a, t = items
    assert a.extra == {"mx": {"AAPL": 0.427}} and a.source == "gurufocus.com · Marketaux" and a.market == "US"
    assert t.extra == {} and t.market == "BIST"                         # skor yoksa ikinci görüş yok
    assert mx.mx_symbol(STOCKS[1]) == "THYAO.IS"


def test_collect_off_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("MARKETAUX_API_TOKEN", raising=False)
    ctx = Context(settings={"sources": {}}, stocks=STOCKS, matcher=TickerMatcher(STOCKS), since=datetime(2026, 10, 1, tzinfo=IST))
    assert mx.collect(ctx) == []


def test_marketaux_records_kept_out_of_main_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "ARCHIVE", tmp_path / "s.json")
    monkeypatch.setattr(sc, "SCORE", tmp_path / "c.json")
    monkeypatch.setattr(sc, "now_utc", lambda: datetime(2026, 10, 10, 12, tzinfo=IST))
    days = [datetime(2026, 9, 28, tzinfo=ZoneInfo("America/New_York")) + timedelta(days=i) for i in range(6)]
    px = {"AAPL": {"market": "US", "daily": [[int(d.timestamp()), 100 - i] for i, d in enumerate(days)], "intraday": []},
          "_SPX": {"market": "US", "daily": [[int(d.timestamp()), 10] for d in days], "intraday": []}}
    item = {"id": "a1", "tickers": ["AAPL"], "market": "US", "published": iso(datetime(2026, 9, 29, 20, tzinfo=ZoneInfo("UTC"))),
            "source": "gurufocus.com · Marketaux", "source_type": "news", "tier": 2, "event": "analyst",
            "title": "Morgan Stanley Lowers Apple Price Target", "extra": {"mx": {"AAPL": 0.43}},
            "analysis": {"sentiment": "bearish", "confidence": 75, "materiality": "medium", "event_label": "Hedef düştü", "provider": "gemini"}}
    res = sc.update([item], px, {"AAPL"})
    assert res["added"] == 2
    import json
    card = json.loads((tmp_path / "c.json").read_text())["scopes"]["US"]["all"]
    assert card["total"]["h1"]["n"] == 1 and card["total"]["h1"]["hit"] == 100.0       # yalnız AI (doğru: düşüş)
    pv = {g["g"]: g["h1"] for g in card["dims"]["pv"]}
    assert pv["AI"]["hit"] == 100.0 and pv["Marketaux"]["hit"] == 0.0                   # Marketaux "olumlu" dedi, yanıldı
    assert all(g["count"] == 1 for g in card["dims"]["kind"])
