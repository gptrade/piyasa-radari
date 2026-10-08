"""KAP kar payı bildirimlerinin ayrıştırılması (çözülmüş gerçek bildirim tabloları)."""
from pathlib import Path

from radar.fundamentals import dividends as D, store

FX = Path(__file__).parent / "fixtures" / "kapdiv"


def p(name, code):
    return D.parse((FX / f"{name}.html").read_text(), code)


def test_two_installments_final():
    d = p("tuprs", "TUPRS")
    assert d["status"] == "kesin" and d["method"] == "2 Taksit"
    assert abs(d["gross"] - 17.1268815) < 1e-9 and abs(d["net"] - 14.5578492) < 1e-9
    assert [i["ex"] for i in d["installments"]] == ["2026-03-16", "2026-09-30"]
    assert d["installments"][1]["pay"] == "2026-10-02" and abs(d["installments"][1]["gross"] - 6.7469533) < 1e-9
    assert d["payout"] == 104.08


def test_single_payment_traded_group():
    d = p("froto", "FROTO")
    assert d["status"] == "kesin" and d["gross"] == 3.64 and d["net"] == 3.094   # A grubu (işlem gören)
    assert d["installments"][0]["ex"] == "2026-03-16"


def test_board_proposal_and_no_dividend():
    e = p("eregl", "EREGL")
    assert e["status"] == "öneri" and e["gross"] == 0.55 and e["installments"] == []
    a = p("aydem", "AYDEM")
    assert a["status"] == "yok"


def test_escaped_flight_text_is_decoded():
    raw = (FX / "froto.html").read_text().replace("<", "\\u003c").replace('"', '\\"')
    assert D.parse(raw, "FROTO")["gross"] == 3.64


def test_calendar_events_and_summary():
    d = {**p("tuprs", "TUPRS"), "idx": 1570793}
    ev = D.calendar_events({"TUPRS": [d]}, "2026-09-01", "2026-12-31")
    assert len(ev) == 1 and ev[0]["date"] == "2026-09-30" and ev[0]["title"] == "TUPRS temettü hak kullanım"
    assert "2. Taksit" in ev[0]["detail"] and "ödeme 2026-10-02" in ev[0]["detail"]
    s = store.div_summary([{**d, "decision": "2099-01-01"}], 379.25)
    assert s["status"] == "kesin" and abs(s["yield"] - 17.1268815 / 379.25) < 1e-3


def test_enqueue_dividend_row():
    st = {}
    row = {"disclosureClass": "ODA", "subject": "Kar Payı Dağıtım İşlemlerine İlişkin Bildirim", "disclosureIndex": 5, "stockCodes": "TUPRS"}
    assert store.enqueue(st, "TUPRS", row) and not store.enqueue(st, "TUPRS", row)
    assert st["div_queue"]["TUPRS"] == [5] and "queue" not in st
