from radar import documents as dc, http
from radar.analyze import Analyzer
from radar.models import Item


def kap(subject, att=0, summary=""):
    return Item(source="KAP", source_type="disclosure", market="BIST", title="X", url="https://www.kap.org.tr/tr/Bildirim/1",
                published="2026-10-01T10:00:00Z", tickers=["THYAO"], summary=summary,
                extra={"subject": subject, "att": att, "filer": "TÜRK HAVA YOLLARI A.O."})


def test_doc_kind():
    assert dc.doc_kind(kap("Finansal Rapor")) == "Finansal rapor"
    assert dc.doc_kind(kap("Faaliyet Raporu (Konsolide)")) == "Faaliyet raporu"
    assert dc.doc_kind(kap("Özel Durum Açıklaması (Genel)", 1, "Yatırımcı Sunumu 3Ç26")) == "Yatırımcı sunumu"
    assert dc.doc_kind(kap("Özel Durum Açıklaması (Genel)", 0, "Yatırımcı Sunumu")) is None      # ek yok
    assert dc.doc_kind(kap("Pay Alım Satım Bildirimi", 1)) is None
    sec = Item(source="SEC EDGAR", source_type="disclosure", market="US", title="8-K", url="u", published="p",
               tickers=["AAPL"], extra={"form": "8-K"})
    assert dc.doc_kind(sec) == "8-K eki (EX-99)"
    sec.extra["form"] = "4"
    assert dc.doc_kind(sec) is None


def test_html_text_and_fit(monkeypatch):
    t = dc.html_text("<script>x()</script><table><tr><td>Hasılat</td><td>12</td></tr></table><p>a&amp;b</p>")
    assert "x()" not in t and "Hasılat | 12" in t and "a&b" in t
    monkeypatch.setattr(dc, "MAX_CHARS", 100)
    long = "A" * 80 + "B" * 80 + "Gelir tablosu" + "C" * 80
    out = dc.fit(long, dc.INCOME)
    assert out.startswith("A" * 50) and "Gelir tablosu" in out and len(out) < 120


def test_kap_body_skips_menu():
    page = "<div>" + "Menü " * 300 + "</div><h1>TÜRK HAVA YOLLARI A.O.</h1><p>3Ç26 sunumu</p>"
    assert dc.kap_body(page, "TÜRK HAVA YOLLARI A.O.").startswith("TÜRK HAVA YOLLARI")


class R:
    def __init__(self, text="", js=None, content=b""):
        self.text, self._js, self.content = text, js, content

    def json(self):
        return self._js


def test_fetch_sec_reads_ex99(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if url.endswith("index.json"):
            return R(js={"directory": {"item": [{"name": "aapl-8k.htm"}, {"name": "a8-kex991q3.htm"}, {"name": "x.jpg"}]}})
        return R(text="<p>" + "Revenue $94.9 billion, up 6 percent. " * 20 + "</p>")
    monkeypatch.setattr(http, "get", get)
    it = Item(source="SEC EDGAR", source_type="disclosure", market="US", title="8-K", published="p", tickers=["AAPL"],
              url="https://www.sec.gov/Archives/edgar/data/320193/000032019326000018/0000320193-26-000018-index.htm",
              extra={"form": "8-K"})
    st = dc.attach([it], {"AAPL"}, {})
    assert st["count"] == 1 and it.extra["doc"]["files"] == [{"type": "EX-99", "name": "a8-kex991q3.htm"}]
    assert "Revenue $94.9 billion" in it.extra["full_text"]
    assert calls[1].endswith("/000032019326000018/a8-kex991q3.htm")


def test_prompt_uses_doc_text_and_note():
    it = kap("Finansal Rapor")
    it.extra.update({"full_text": "Z" * 10000, "doc": {"kind": "Finansal rapor", "files": [], "chars": 10000}})
    p = Analyzer({"analysis": {"enabled": False}}).prompt(it, "")
    assert p.startswith("BELGE ÖZETİ: Bu kayıt bir Finansal rapor") and "Z" * 10000 in p
    assert '"full_text"' not in p


def test_pdf_bytes_unwraps_kap_download():
    raw = b"\xac\xed\x00\x05ur\x00\x02[B\xac\xf3\x17\xf8\x06\x08T\xe0\x02\x00\x00xp\x00\x0b\x05\xbc%PDF-1.7\n..."
    assert dc.pdf_bytes(raw).startswith(b"%PDF-1.7")
    assert dc.pdf_bytes(b"PK\x03\x04 excel") is None
