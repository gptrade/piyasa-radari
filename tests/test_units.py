from datetime import datetime, timedelta, timezone

import feedparser

from radar import notify, prices
from radar.config import Stock, TickerMatcher
from radar.models import Item, iso
from radar.sources import kap
from radar.sources.feeds import entries_to_items

STOCKS = [
    Stock("VAKBN", "VakıfBank", "BIST", ["VakıfBank", "Türkiye Vakıflar Bankası"]),
    Stock("THYAO", "Türk Hava Yolları", "BIST", ["Türk Hava Yolları", "THY"]),
    Stock("AMD", "Advanced Micro Devices", "US", ["AMD"]),
    Stock("AAPL", "Apple", "US", ["Apple"]),
]


def test_matcher_symbols_aliases_and_case():
    m = TickerMatcher(STOCKS)
    assert m.match("vakıfbank kâr açıkladı") == ["VAKBN"]
    assert m.match("THY yeni uçak siparişi", market="BIST") == ["THYAO"]
    assert m.match("$AMD rallies") == ["AMD"]
    assert m.match("pineapple prices") == []          # "apple" kelime içinde → eşleşmemeli
    assert m.match("THYAOX token") == []


def test_kap_parse_filters_watchlist():
    rows = [
        {"publishDate": "27.09.2026 18:42:10", "kapTitle": "TÜRKİYE VAKIFLAR BANKASI T.A.O.",
         "disclosureClass": "ODA", "relatedStocks": "VAKBN", "disclosureIndex": 1500001,
         "subject": "Özel Durum Açıklaması (Genel)", "summary": "Sendikasyon kredisi", "modifyStatus": None},
        {"publishDate": "27.09.2026 18:40:00", "kapTitle": "BAŞKA A.Ş.", "relatedStocks": "XXXXX",
         "disclosureIndex": 1500002, "subject": "Genel Kurul"},
    ]
    items = kap.parse_rows(rows, {"VAKBN"}, "watchlist")
    assert len(items) == 1
    it = items[0]
    assert it.tickers == ["VAKBN"] and it.market == "BIST"
    assert it.published == "2026-09-27T15:42:10Z"       # İstanbul UTC+3 → UTC
    assert it.url.endswith("/1500001")
    assert len(kap.parse_rows(rows, {"VAKBN"}, "all")) == 2


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>VakıfBank sermaye artırımı - Bloomberg HT</title><link>https://ex.com/1</link>
<pubDate>Sun, 27 Sep 2026 12:00:00 GMT</pubDate><description>&lt;p&gt;Detay&lt;/p&gt;</description></item>
<item><title>Altın fiyatları</title><link>https://ex.com/2</link>
<pubDate>Sun, 27 Sep 2026 12:00:00 GMT</pubDate></item>
<item><title>Eski haber VakıfBank</title><link>https://ex.com/3</link>
<pubDate>Sun, 20 Sep 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_entries_match_and_since():
    feed = feedparser.parse(RSS)
    since = datetime(2026, 9, 26, tzinfo=timezone.utc)
    items = entries_to_items(feed, source="Bloomberg HT", source_type="news", market="BIST",
                             since=since, lang="tr", matcher=TickerMatcher(STOCKS))
    assert [i.url for i in items] == ["https://ex.com/1"]
    assert items[0].tickers == ["VAKBN"] and items[0].summary == "Detay"


def test_reaction_horizons():
    t0 = int(datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc).timestamp())
    intraday = [[t0 + 300 * i, 100 + i] for i in range(40)]      # 5 dk barlar
    daily = [[t0 - 86400, 99], [t0 + 86400 * 2, 110]]
    r = prices.reaction(iso(datetime.fromtimestamp(t0 + 60, tz=timezone.utc)),
                        {"intraday": intraday, "daily": daily})
    assert r["base"] == 100
    assert r["15m"] == 4.0          # t0+60+900 → ilk bar t0+1200 = 104
    assert r["1h"] == 13.0
    assert r["1d"] == 10.0
    assert r["since"] == 39.0


def test_notify_filter():
    it = Item(source="KAP", source_type="disclosure", market="BIST", title="x", url="u",
              published="2026-09-27T10:00:00Z", tickers=["VAKBN"])
    cfg = {"min_confidence": 70, "only_directional": True, "min_materiality": "medium"}
    it.analysis = {"sentiment": "bullish", "confidence": 80, "materiality": "high"}
    assert notify.should_notify(it, cfg)
    it.analysis = {"sentiment": "neutral", "confidence": 90, "materiality": "high"}
    assert not notify.should_notify(it, cfg)
    it.analysis = {"sentiment": "bearish", "confidence": 60, "materiality": "high"}
    assert not notify.should_notify(it, cfg)
    msg = notify.format_message(Item(source="KAP", source_type="disclosure", market="BIST",
                                     title="Kâr & zarar", url="https://k", published="2026-09-27T10:00:00Z",
                                     tickers=["VAKBN"]) , None)
    assert "Kâr &amp; zarar" in msg
