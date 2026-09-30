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
