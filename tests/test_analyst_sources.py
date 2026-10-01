from datetime import timedelta
from urllib.parse import unquote_plus

import pandas as pd

from radar import prices
from radar.config import Stock, TickerMatcher
from radar.enrich import enrich
from radar.models import now_utc
from radar.notify import should_notify
from radar.pipeline import analyst_items, grade_dir
from radar.sources import Context, feeds

NVDA = Stock("NVDA", "Nvidia", "US", [])
THY = Stock("THYAO", "Türk Hava Yolları", "BIST", [])


def test_site_query_combines_sites():
    assert feeds.site_query(NVDA, ["marketwatch.com", "tradingview.com"]) == \
        '("NVDA") (site:marketwatch.com OR site:tradingview.com)'
    assert feeds.site_query(THY, ["fintables.com"]) == '("Türk Hava Yolları" OR "THYAO") (site:fintables.com)'


def test_google_news_one_site_and_one_analyst_query_per_stock(monkeypatch):
    urls = []
    monkeypatch.setattr(feeds, "fetch_feed", lambda url, **k: urls.append(unquote_plus(url)) or None)
    settings = {"sources": {"google_news": {"sites": {"US": ["a.com", "b.com"]},
                                            "analyst_terms": {"US": ["price target", "upgrade"]}}}}
    ctx = Context(settings=settings, stocks=[NVDA], matcher=TickerMatcher([NVDA]), since=now_utc())
    feeds.collect_google_news(ctx)
    assert len(urls) == 3                                   # ana arama + site: + analist
    assert "site:a.com OR site:b.com" in urls[1]
    assert '"price target" OR upgrade' in urls[2]


class FakeTicker:
    analyst_price_targets = {"current": 100, "mean": 150.5, "median": 150, "high": 200, "low": 90}
    recommendations = pd.DataFrame([{"period": "0m", "strongBuy": 10, "buy": 20, "hold": 5, "sell": 1, "strongSell": 0}])
    upgrades_downgrades = pd.DataFrame(
        [{"Firm": "Morgan Stanley", "ToGrade": "Overweight", "FromGrade": "Equal-Weight", "Action": "up",
          "currentPriceTarget": 180.0, "priorPriceTarget": 140.0},
         {"Firm": "Old Firm", "ToGrade": "Buy", "FromGrade": "", "Action": "main",
          "currentPriceTarget": 0.0, "priorPriceTarget": 0.0}],
        index=pd.to_datetime([now_utc().date(), now_utc().date() - timedelta(days=30)]))


def test_analyst_data_from_yfinance_shapes():
    a = prices.analyst_data(FakeTicker())
    assert a["targets"]["mean"] == 150.5
    assert a["rec"] == {"strongBuy": 10, "buy": 20, "hold": 5, "sell": 1, "strongSell": 0}
    assert a["changes"][0]["firm"] == "Morgan Stanley" and a["changes"][0]["pt"] == 180.0
    assert a["changes"][1]["pt"] is None                   # 0 hedef = yok


def test_analyst_data_none_when_empty():
    class Empty:
        analyst_price_targets = {}
        recommendations = None
        upgrades_downgrades = None
    assert prices.analyst_data(Empty()) is None


def test_analyst_items_recent_changes_only_and_notify():
    px = {"NVDA": {"last": 150.0, "currency": "USD", "analyst": prices.analyst_data(FakeTicker())}}
    items = analyst_items([NVDA], px, max_age_days=3)
    assert len(items) == 1                                  # 30 günlük eski not akışa düşmez
    it = items[0]
    assert it.analysis["sentiment"] == "bullish" and it.analysis["event_label"] == "Not artırımı"
    assert "Equal-Weight → Overweight" in it.title and "hedef 180" in it.title and "önce 140" in it.title
    d = enrich(it.to_dict())
    assert d["event"] == "analyst" and d["tier"] == 2
    assert should_notify(it, {"min_confidence": 70, "only_directional": True, "min_materiality": "medium"})
    assert analyst_items([NVDA], px)[0].id == it.id        # aynı not ikinci kez yeni kayıt üretmez


def test_maintained_rating_with_big_target_cut_is_bearish():
    px = {"NVDA": {"last": 100.0, "analyst": {"changes": [
        {"date": now_utc().date().isoformat(), "firm": "X", "to": "Buy", "from": "Buy", "action": "main",
         "pt": 90.0, "pt_prev": 120.0}]}}}
    it = analyst_items([NVDA], px)[0]
    assert it.analysis["sentiment"] == "bearish" and it.analysis["event_label"] == "Hedef düşürüldü"


def test_grade_dir():
    assert grade_dir("Strong Buy") == 1 and grade_dir("Underperform") == -1 and grade_dir("Neutral") == 0
    assert grade_dir("Equal-Weight") == 0 and grade_dir("Market Perform") == 0


def test_update_all_refreshes_analyst_only_when_due(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "PRICE_DIR", tmp_path)
    monkeypatch.setattr(prices, "INDEXES", {})
    calls = []

    def fake_fetch(st, yahoo=None, analyst=False):
        calls.append(analyst)
        p = {"symbol": st.symbol, "last": 1}
        if analyst:
            p["analyst"] = {"updated": prices.iso(now_utc()), "rec": {"buy": 1}}
        return p
    monkeypatch.setattr(prices, "fetch", fake_fetch)
    prices.update_all([NVDA], analyst_hours=6)
    out = prices.update_all([NVDA], analyst_hours=6)
    assert calls == [True, False]
    assert out["NVDA"]["analyst"]["rec"] == {"buy": 1}     # yenilenmediğinde eski veri taşınır
