"""KAP sözleşme bildirimlerinde tutar / ciro oranı."""
from radar import deals
from radar.models import Item

RATES = {"TRY": 1.0, "USD": 40.0, "EUR": 45.0}
TEXT = """GÜLERMAK AĞIR SANAYİ İNŞAAT VE TAAHHÜT A.Ş. Yeni İş İlişkisi. Şirketimiz ile X Belediyesi arasında
toplam bedeli 125.400.000 EUR (KDV hariç) olan metro hattı yapım işi sözleşmesi imzalanmıştır. İşin süresi 36 aydır.
Pay başına nominal değer 1 TL olup sermayenin %25'i ... 2026 yılı içinde başlanacaktır."""


def test_amounts_parse_turkish_formats():
    a = deals.amounts(TEXT)
    assert (125_400_000.0, "EUR") in a
    assert all(c != "TRY" or v >= 1000 for v, c in a)          # "1 TL" nominal değer alınmaz
    assert (12_500_000.0, "USD") in deals.amounts("Sipariş tutarı 12,5 milyon USD'dir.")
    assert (3_200_000_000.0, "TRY") in deals.amounts("İhale bedeli 3,2 milyar TL")
    assert (750_000.0, "USD") in deals.amounts("toplam USD 750.000 tutarında")


def test_size_and_materiality():
    d = deals.size(TEXT, RATES, revenue=20e9)
    assert d["cur"] == "EUR" and d["tl"] == round(125.4e6 * 45) and abs(d["ratio"] - 0.2822) < 0.001
    assert deals.materiality(d["ratio"], "medium") == "high"
    assert deals.materiality(0.005, "high") == "low"
    assert deals.materiality(0.05, "low") == "medium" and deals.materiality(0.02, "medium") == "medium"
    assert deals.size("tutar belirtilmedi", RATES, 1e9) is None


def test_attach_and_adjust(monkeypatch):
    class R:
        text = "<html>menü ... GÜLERMAK AĞIR SANAYİ " + TEXT + "</html>"
    monkeypatch.setattr(deals.http, "get", lambda url, **kw: R())
    monkeypatch.setattr(deals, "ttm_revenue", lambda code: 20e9)
    it = Item(source="KAP", source_type="disclosure", market="BIST", title="GLRMK: Yeni İş İlişkisi",
              url="https://www.kap.org.tr/tr/Bildirim/1", published="2026-10-15T10:00:00Z", tickers=["GLRMK"],
              summary="", extra={"subject": "Yeni İş İlişkisi", "filer": "GÜLERMAK AĞIR SANAYİ"})
    other = Item(source="KAP", source_type="disclosure", market="BIST", title="GLRMK: Genel Kurul",
                 url="u", published="2026-10-15T10:00:00Z", tickers=["GLRMK"], extra={"subject": "Genel Kurul İşlemlerine İlişkin Bildirim"})
    macro = {"series": [{"code": "TP.DK.EUR.A.YTL", "history": [["15-10-2026", 45.0]]}]}
    assert deals.attach([it, other], {"GLRMK"}, macro) == 1
    assert it.extra["deal"]["ratio"] > 0.28 and "deal" not in other.extra
    it.analysis = {"materiality": "medium"}
    deals.adjust(it)
    assert it.analysis["materiality"] == "high"


def test_dash_separator_and_kap_fields():
    t = "Sözleşmenin toplam bedeli KDV hariç 10.200.000-ABD Doları'dır. (toplam 502.901.820 -TL'dir.)"
    assert (10_200_000.0, "USD") in deals.amounts(t) and (502_901_820.0, "TRY") in deals.amounts(t)
    form = ("| İhale Bedeli | Tender Value | | | | 2.000.000.000 TL | 2.000.000.000 TRY | | İhale Bedelinden Ortaklık Payına Düşen Kısım"
            " | Share of Company in Tender Value | | | | 500.000.000 TL | 500.000.000 TRY | | Ortaklık Payına Düşen Kısmın ... Oranı (%) |"
            " Ratio Of Tender Value Corporate Share Amount To Gross Sales Revenue On Publicly Disclosed The Latest Financial Statement Of Company (%) | | | | 12,5 | 12.5 |")
    d = deals.size(form, RATES, revenue=1e10)
    assert d["amount"] == 500_000_000 and d["ratio"] == 0.125 and d["src"] == "KAP"
    assert deals.SUBJECT.search("Yeni İş İlişkisi") and deals.NOT_DEAL.search("Esas Sözleşme Tadili")
