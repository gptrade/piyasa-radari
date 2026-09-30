from datetime import datetime, timezone

import feedparser

from radar.config import Stock, TickerMatcher
from radar.sources import kap, spk, tcmb
from radar.sources.feeds import wire_tickers

STOCKS = [
    Stock("VAKBN", "VakıfBank", "BIST", ["VakıfBank", "Türkiye Vakıflar Bankası"]),
    Stock("GLRMK", "Gülermak", "BIST", ["Gülermak"]),
    Stock("NVDA", "NVIDIA", "US", ["Nvidia"]),
    Stock("AAPL", "Apple", "US", ["Apple"]),
]
M = TickerMatcher(STOCKS)


# ------------------------------------------------------------ Borsa İstanbul (KAP)
def test_bist_measure_rows():
    rows = [{"publishDate": "29.09.2026 19:05:00", "kapTitle": "BORSA İSTANBUL A.Ş.",
             "relatedStocks": "GLRMK", "disclosureIndex": 1600001,
             "subject": "Borsa İstanbul A.Ş. Duyurusu", "summary": "Brüt Takas"},
            {"publishDate": "29.09.2026 19:06:00", "kapTitle": "BORSA İSTANBUL A.Ş.",
             "relatedStocks": "GLRMK", "disclosureIndex": 1600002,
             "subject": "Borsa İstanbul A.Ş. Duyurusu", "summary": "Brüt Takas Tedbirinin Kaldırılması"}]
    a, b = kap.parse_rows(rows, {"GLRMK"}, "watchlist")
    assert a.source == "Borsa İstanbul · KAP" and a.extra["bist_measure"] == "Brüt takas"
    assert a.title == "GLRMK: Brüt takas"
    assert b.extra["bist_measure"] == "Tedbir kaldırıldı"


def test_bist_measure_keywords_turkish_case():
    assert kap.bist_measure("KREDİLİ İŞLEM YASAĞI") == "Kredili işlem yasağı"
    assert kap.bist_measure("TEK FİYAT YÖNTEMİ") == "Tek fiyat yöntemi"
    assert kap.bist_measure("İŞLEM SIRASI DURDURMA") == "İşlem sırası durduruldu"


# ------------------------------------------------------------ SPK
LISTING = """
<ul>
 <li><a href="/data/aaa111/2026-66.pdf">Bülten No : 2026/66 <span>Yayımlanma : 28 Eylül 2026 Pazartesi</span></a></li>
 <li><a href="https://spk.gov.tr/data/bbb222/2026-65.pdf">Bülten No : 2026/65 Yayımlanma : 25 EYLÜL 2026 Cuma</a></li>
 <li><a href="/data/aaa111/2026-66.pdf">tekrar</a></li>
</ul>"""


def test_spk_listing():
    out = spk.parse_listing(LISTING, "https://spk.gov.tr/spk-bultenleri/2026-yili-spk-bultenleri")
    assert [b["no"] for b in out] == ["2026/66", "2026/65"]
    assert out[0]["url"] == "https://spk.gov.tr/data/aaa111/2026-66.pdf"
    assert out[0]["date"].day == 28 and out[0]["date"].month == 9
    assert out[1]["date"].month == 9


def test_spk_excerpts_only_matching_parts():
    text = ("A" * 5000) + " GÜLERMAK AĞIR SANAYİ İNŞAAT A.Ş.'nin bedelsiz sermaye artırımı onaylanmıştır. " + ("B" * 5000)
    tickers = M.match(text, market="BIST")
    assert tickers == ["GLRMK"]
    ex = spk.excerpts(text, M, tickers)
    assert "bedelsiz" in ex and len(ex) < 3000


# ------------------------------------------------------------ TCMB / EVDS
def test_evds_url_is_path_style():
    u = tcmb.evds_url(["TP.DK.USD.A.YTL", "TP.APIFON4"], datetime(2026, 9, 1), datetime(2026, 9, 30))
    assert "?" not in u
    assert u.endswith("series=TP.DK.USD.A.YTL-TP.APIFON4&startDate=01-09-2026&endDate=30-09-2026&type=json")


def test_evds_parse_skips_nulls():
    payload = {"items": [
        {"Tarih": "26-09-2026", "TP_DK_USD_A_YTL": "41.10", "TP_APIFON4": "40.5"},
        {"Tarih": "27-09-2026", "TP_DK_USD_A_YTL": None, "TP_APIFON4": None},
        {"Tarih": "29-09-2026", "TP_DK_USD_A_YTL": "41.30", "TP_APIFON4": "40.5"},
    ]}
    s = tcmb.parse_evds(payload, [{"code": "TP.DK.USD.A.YTL", "name": "USD/TRY"},
                                  {"code": "TP.APIFON4", "name": "AOFM", "unit": "%"},
                                  {"code": "TP.YOK", "name": "yok"}])
    usd, rate = s
    assert len(s) == 2
    assert usd["last"] == 41.30 and usd["prev"] == 41.10 and usd["date"] == "29-09-2026"
    assert rate["change"] == 0


# ------------------------------------------------------------ Basın bültenleri
def test_wire_tickers_exchange_tag_and_title():
    us = [s for s in STOCKS if s.market == "US"]
    assert wire_tickers("Company X partners", "SANTA CLARA, Calif. -- (NASDAQ: NVDA) today...", us) == ["NVDA"]
    assert wire_tickers("Nvidia Announces Q3 Results", "", us) == ["NVDA"]
    # Başka bir şirketin borsa etiketi varsa başlıktaki ad eşleşmesi kullanılmaz
    assert wire_tickers("Apple Hospitality REIT Reports", "(NYSE: APLE)", us) == []
    assert wire_tickers("Pineapple Growers Unite", "Apple orchards", us) == []
    assert wire_tickers("Acme Corp results", "(NYSE: AAPLX)", us) == []


def test_tcmb_rss_market_wide_items():
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>PPK</title>
    <item><title>Faiz Oranlarına İlişkin Basın Duyurusu</title><link>https://tcmb/1</link>
    <pubDate>Thu, 24 Sep 2026 11:00:00 GMT</pubDate></item></channel></rss>"""
    from radar.sources.feeds import entries_to_items
    items = entries_to_items(feedparser.parse(rss), source="TCMB · PPK Kararları", source_type="macro",
                             market="BIST", since=datetime(2026, 9, 20, tzinfo=timezone.utc),
                             lang="tr", allow_empty=True)
    assert len(items) == 1 and items[0].tickers == []


# ------------------------------------------------------------ Türkçe tarihli RSS (TCMB)
def test_parse_tr_date_formats():
    from radar.sources.feeds import parse_tr_date
    d = parse_tr_date("10 Ara 2024 11:23:57")
    assert (d.year, d.month, d.day, d.hour, d.second) == (2024, 12, 10, 11, 57)
    assert parse_tr_date("28 Eylül 2026 Pazartesi").month == 9
    assert parse_tr_date("25 EYLÜL 2026").day == 25
    assert parse_tr_date("28.09.2026 18:30").hour == 18
    assert parse_tr_date("tarih yok") is None


def test_tcmb_style_feed_turkish_dates_and_relative_links():
    from radar.sources.feeds import entries_to_items
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>PPK</title>
    <item><title><![CDATA[Faiz Oranlarına İlişkin Basın Duyurusu (2026-40)]]></title>
    <link>/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Duyurular/Basin/2026/DUY2026-40</link>
    <pubDate>24 Eyl 2026 14:00:00</pubDate></item>
    <item><title>Eski</title><link>/eski</link><pubDate>10 Ara 2024 11:23:57</pubDate></item>
    </channel></rss>"""
    feed = feedparser.parse(rss)
    feed["_base"] = "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Bottom+Menu/Diger/RSS/PPK+Kararlari"
    items = entries_to_items(feed, source="TCMB · PPK Kararları", source_type="macro", market="BIST",
                             since=datetime(2026, 9, 20, tzinfo=timezone.utc), lang="tr", allow_empty=True)
    assert len(items) == 1
    assert items[0].url == "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Duyurular/Basin/2026/DUY2026-40"
    assert items[0].published == "2026-09-24T11:00:00Z"          # İstanbul 14:00 → UTC 11:00


def test_per_stock_limit_keeps_newest():
    from radar.sources.feeds import entries_to_items
    body = "".join(f"<item><title>NVDA haber {i}</title><link>https://x/{i}</link>"
                   f"<pubDate>Tue, 29 Sep 2026 {10 + i:02d}:00:00 GMT</pubDate></item>" for i in range(6))
    feed = feedparser.parse(f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>')
    items = entries_to_items(feed, source="Google News", source_type="news", market="US",
                             since=datetime(2026, 9, 28, tzinfo=timezone.utc), lang="en",
                             tickers=["NVDA"], limit=3)
    assert [i.url for i in items] == ["https://x/5", "https://x/4", "https://x/3"]


def test_failures_are_reported_in_status(tmp_path, monkeypatch):
    import json
    from radar import http, pipeline, prices
    monkeypatch.setattr(pipeline, "DATA", tmp_path)
    monkeypatch.setattr(pipeline, "FEED", tmp_path / "feed.json")
    monkeypatch.setattr(pipeline, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(prices, "update_all", lambda stocks: {})
    monkeypatch.setattr(pipeline.tcmb, "update_macro", lambda settings: None)
    monkeypatch.setattr(pipeline.digest, "DIGEST_FILE", tmp_path / "digest.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def flaky(ctx):
        http.note_failure("https://www.bloomberght.com/rss", "HTTP 403")
        return []
    monkeypatch.setattr(pipeline, "COLLECTORS", [("TR haber RSS", flaky)])
    pipeline.run()
    st = json.loads((tmp_path / "feed.json").read_text())["sources"][0]
    assert st["warnings"] == ["www.bloomberght.com: HTTP 403"]


def test_investing_naive_iso_dates():
    from radar.sources.feeds import entries_to_items
    from radar.config import Stock, TickerMatcher
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>BIST</title>
    <item><title>Türk Hava Yolları yeni uçak siparişi verdi</title><pubDate>2026-09-30 15:13:09</pubDate>
    <link>https://tr.investing.com/news/x-1</link></item></channel></rss>"""
    m = TickerMatcher([Stock("THYAO", "Türk Hava Yolları", "BIST", ["Türk Hava Yolları", "THY"])])
    items = entries_to_items(feedparser.parse(rss), source="Investing · BİST", source_type="news", market="BIST",
                             since=datetime(2026, 9, 29, tzinfo=timezone.utc), lang="tr", matcher=m)
    assert len(items) == 1 and items[0].published == "2026-09-30T15:13:09Z" and items[0].tickers == ["THYAO"]


def test_investing_analysis_feed_dates():
    from radar.sources.feeds import _entry_time
    assert _entry_time({"published": "Jul 06, 2026 06:58 GMT"}).isoformat() == "2026-07-06T06:58:00+00:00"
    assert _entry_time({"published": "2026-08-22 03:06:03"}).isoformat() == "2026-08-22T03:06:03+00:00"
