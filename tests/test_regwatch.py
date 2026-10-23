import json
from pathlib import Path

from radar import regwatch as rw

FX = Path(__file__).parent / "fixtures" / "reg"


def test_parse_date_formats():
    assert rw.parse_date("16.10.2026") == "2026-10-16"
    assert rw.parse_date("01/10/2026") == "2026-10-01"
    assert rw.parse_date("2026-10-16T09:00:00Z") == "2026-10-16"
    assert rw.parse_date("19 Oct 2026") == "2026-10-19"
    assert rw.parse_date("September 16, 2026") == "2026-09-16"
    assert rw.parse_date("Mon, 13 Oct 2026 10:00:00 GMT") == "2026-10-13"
    assert rw.parse_date("9/30/2026", dayfirst=True) == "2026-09-30"        # ay > 12 ise yer değiştir
    assert rw.parse_date("yok") is None


def test_html_bddk_and_cbuae():
    b = rw.from_html((FX / "bddk.html").read_text(), "https://www.bddk.org.tr/Duyuru/Liste/39")
    dated = [x for x in b if x["date"]]
    assert len(dated) > 100 and dated[0]["url"].startswith("https://www.bddk.org.tr/Duyuru/Detay/")
    t = rw.tidy("bddk", dict(dated[0]))
    assert not t["title"][:2].isdigit()
    c = rw.from_html((FX / "cbuae.html").read_text(), "https://rulebook.centralbank.ae/en/view-revision-updates")
    assert any("Operational Risk Management Regulation" in x["title"] and x["date"] == "2026-09-14" for x in c)


def test_table_sama():
    s = rw.from_table((FX / "sama.html").read_text(), "https://rulebook.sama.gov.sa/en/banking-sector-circulars")
    q = [x for x in s if "Quantum Computing" in x["title"]]
    assert q and q[0]["date"] == "2026-08-27" and q[0]["url"].startswith("https://rulebook.sama.gov.sa/en/node/")


def test_bis_tidy_and_rss():
    b = [rw.tidy("bcbs", x) for x in rw.from_html((FX / "bis.html").read_text(), "https://www.bis.org/committees/bcbs/publications")]
    g = [x for x in b if "G-SIB" in x["title"] or "systemically" in x["title"]]
    assert g and not g[0]["title"].startswith("Publication")
    d = rw.from_rss((FX / "dfsa.xml").read_text(), "https://www.dfsa.ae/rss")
    assert len(d) >= 5 and d[0]["url"].startswith("https://www.dfsa.ae/")


class FakeAnalyzer:
    providers = ["x"]
    last_blocked = False

    def ask_json(self, system, prompt, tool, fmt, max_tokens=1500, media=None, light=False):
        if "BAŞLIKLAR" in prompt:
            n = prompt.count("\n") + 1 - 1
            return {"items": [{"i": 0, "relevant": True, "topics": ["oprisk", "uydurma"], "type": "nihai", "title_tr": "Operasyonel risk", "summary_tr": "x"},
                              {"i": 1, "relevant": False}]}
        return {"trends": [{"title": "t", "detail": "d", "regulators": ["r"], "tr_impact": "i"}] * 3, "_model": "m"}


class FakeFetcher:
    gap = 0
    def get(self, url, **kw):
        class R:
            status_code = 200
            encoding = "utf-8"
        r = R()
        r.text = (FX / "cbuae.html").read_text() if "centralbank" in url else "<rss></rss>"
        return r


def test_run_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(rw, "OUT", tmp_path / "regwatch.json")
    st = rw.run(analyzer=FakeAnalyzer(), fetcher=FakeFetcher())
    rel = [i for i in st["items"] if i.get("relevant")]
    assert rel and rel[0]["topics"] == ["oprisk"] and rel[0]["type"] == "nihai"
    assert st["status"]["cbb"]["ok"] is False and st["status"]["cbuae"]["ok"]
    assert all("relevant" in i for i in st["items"][:40])
    json.dumps(st)


def test_future_date_is_effective_not_publication():
    import datetime as dt
    from radar import regwatch
    it = {"date": "2027-07-15", "first_seen": "2026-10-19T19:31:00+00:00"}
    regwatch.future_date(it, dt.date(2026, 10, 20))
    assert it["effective"] == "2027-07-15" and it["date"] == "2026-10-19" and it["date_est"]
    ok = {"date": "2026-10-18", "first_seen": "2026-10-19T19:31:00+00:00"}
    regwatch.future_date(ok, dt.date(2026, 10, 20))
    assert ok["date"] == "2026-10-18" and "effective" not in ok


def test_table_status_column_parsed():
    from radar import regwatch
    html = """<table><tr><td>4820</td><td><a href="/en/x">Rules on Credit Risk Management for banks</a></td><td>01/10/2026</td><td>In- Force</td></tr>
    <tr><td>4821</td><td><a href="/en/y">Old Liquidity Rules for licensed banks</a></td><td>01/02/2013</td><td>Modified</td></tr></table>"""
    rows = regwatch.from_table(html, "https://rulebook.sama.gov.sa/en/banking-sector-circulars")
    assert [r.get("status") for r in rows] == ["yururlukte", "degisti"]


def test_from_gnews_strips_publisher_and_generic_titles():
    from radar import regwatch as R
    rss = """<rss><channel>
    <item><title>CBB Ijara Murabaha Sukuk Fully subscribed - Central Bank of Bahrain</title><link>https://news.google.com/rss/articles/A1</link><pubDate>Thu, 22 Oct 2026 08:00:00 GMT</pubDate></item>
    <item><title>BANQUE DU LIBAN - Central Bank of Lebanon</title><link>https://news.google.com/rss/articles/A2</link><pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
    <item><title>Protected: Privacy Notice - Central Bank of Bahrain</title><link>https://news.google.com/rss/articles/A3</link><pubDate>Mon, 07 Sep 2026 08:00:00 GMT</pubDate></item>
    </channel></rss>"""
    out = R.from_gnews(rss, {"skip": ["^Protected:"]})
    assert [o["title"] for o in out] == ["CBB Ijara Murabaha Sukuk Fully subscribed"]
    assert out[0]["date"] == "2026-10-22" and out[0]["via"] == "Google News"
    assert "site%3Acbb.gov.bh" in R.gnews_url("cbb.gov.bh")
