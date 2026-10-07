"""KAP mali tablo ayrıştırma ve veri katmanı testleri (küçültülmüş gerçek KAP dışa aktarımlarıyla)."""
from pathlib import Path

import pytest

from radar.fundamentals import kapfin, store

FX = Path(__file__).parent / "fixtures" / "kapfin"


def load(name):
    return kapfin.parse_export((FX / f"{name}.html").read_bytes())


def test_parse_num():
    assert kapfin.parse_num("8.764.874") == 8764874
    assert kapfin.parse_num("-2.166.563") == -2166563
    assert kapfin.parse_num("(1.234)") == -1234
    assert kapfin.parse_num("1.234,5") == 1234.5
    assert kapfin.parse_num("") is None
    assert kapfin.parse_num("15") == 15
    assert kapfin.parse_num("(IV-a)") is None


def test_parse_scale():
    assert kapfin.parse_scale("Sunum Para Birimi 1.000 TL Finansal") == ("TRY", 1000)
    assert kapfin.parse_scale("Sunum Para Birimi TL Finansal") == ("TRY", 1)
    assert kapfin.parse_scale("Sunum Para Birimi 1.000 USD Finansal") == ("USD", 1000)


def test_trgyo_consolidated_matches_screenshot_values():
    r = load("trgyo_2026_06")
    assert (r["year"], r["period"], r["consolidated"], r["template"]) == (2026, 2, True, "sanayi")
    assert (r["currency"], r["scale"]) == ("TRY", 1000)
    inc = r["is"]
    assert [c.get("start") for c in inc["cols"]] == ["2026-01-01", "2025-01-01", "2026-04-01", "2025-04-01"]
    assert inc["rows"]["Hasılat"][0] == 8764874
    assert inc["rows"]["BRÜT KAR (ZARAR)"][0] == 6598311
    assert inc["rows"]["ESAS FAALİYET KARI (ZARARI)"][0] == 5687881
    assert inc["rows"]["Net Parasal Pozisyon Kazançları (Kayıpları)"][0] == -1731936
    assert inc["rows"]["Ana Ortaklık Payları"][0] == 5977426
    bs = r["bs"]
    assert [c["end"] for c in bs["cols"]] == ["2026-06-30", "2025-12-31"]
    assert bs["rows"]["Nakit ve Nakit Benzerleri"] == [15888366, 18015271]
    cf = r["cf"]
    assert cf["rows"]["İŞLETME FAALİYETLERİNDEN NAKİT AKIŞLARI"][0] == 9529367


def test_note_column_not_taken_as_value():
    r = load("trgyo_2026_06")
    # 'Hasılat' satırında not numarası (15) var; değerler 4 sütun olmalı
    assert len(r["is"]["rows"]["Hasılat"]) == 4


def test_solo_report_and_choose_prefers_consolidated():
    solo, cons = load("trgyo_2026_06_b"), load("trgyo_2026_06")
    assert solo["consolidated"] is False
    solo["idx"], cons["idx"] = 1652360, 1652359
    assert store.choose([solo, cons]) is cons


def test_bank_template():
    r = load("akbnk_2026_06")
    assert r["template"] == "finansal"
    assert r["scale"] == 1000000


def test_parse_indices():
    page = ('...{\\"code\\":\\"XU100\\",\\"content\\":[{\\"stockCode\\":\\"AKBNK\\",\\"title\\":\\"AKBANK T.A.Ş.\\",'
            '\\"mkkMemberOid\\":\\"4028e4a240e8d1830140e905edcd0006\\"},{\\"stockCode\\":\\"TRGYO\\",\\"title\\":\\"TORUNLAR\\",'
            '\\"mkkMemberOid\\":\\"4028e4a1413b7ef5014144f83882011f\\"}],\\"explanation\\":\\"x\\"},'
            '{\\"code\\":\\"XU050\\",\\"content\\":[{\\"stockCode\\":\\"AKBNK\\",\\"title\\":\\"AKBANK\\",\\"mkkMemberOid\\":\\"ab\\"}]}')
    idx = kapfin.parse_indices(page)
    assert [m["code"] for m in idx["XU100"]] == ["AKBNK", "TRGYO"]
    assert idx["XU100"][1]["oid"] == "4028e4a1413b7ef5014144f83882011f"
    assert len(idx["XU050"]) == 1


def test_parse_sectors():
    page = ('{"sectorName":"ULAŞTIRMA VE DEPOLAMA","sectorOid":"33E","sectorNo":"007000.001000.",'
            '"mkkMemberOid":"4028","stockCode":"THYAO","title":"TÜRK HAVA YOLLARI A.O."},'
            '{"mainSectorName":"ULAŞTIRMA VE DEPOLAMA","mainSectorOid":"33E5","mainSectorNo":"007000.",'
            '"mkkMemberOid":"4028","stockCode":"THYAO","title":"TÜRK HAVA YOLLARI A.O."}')
    assert kapfin.parse_sectors(page)["THYAO"] == {"sector": "ULAŞTIRMA VE DEPOLAMA", "main": "ULAŞTIRMA VE DEPOLAMA"}


def test_is_fr_and_period_key():
    assert kapfin.is_fr({"disclosureClass": "FR", "subject": "Finansal Rapor"})
    assert not kapfin.is_fr({"disclosureClass": "FR", "subject": "Faaliyet Raporu (Konsolide)"})
    assert kapfin.period_key(2026, 2) == "2026/06"
    assert kapfin.period_key(2025, 4) == "2025/12"


def test_parse_cpi():
    payload = {"items": [{"Tarih": "2026-8", "TP_GENENDEKS_T1": "5781.74"}, {"Tarih": "2026-9", "TP_GENENDEKS_T1": ""}]}
    assert store.parse_cpi(payload) == {"2026-08": 5781.74}


@pytest.fixture
def fin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "FIN", tmp_path)
    monkeypatch.setattr(store, "STATE", tmp_path / "_state.json")
    monkeypatch.setattr(store, "UNIVERSE", tmp_path / "_universe.json")
    monkeypatch.setattr(store, "CPI", tmp_path / "_cpi.json")
    monkeypatch.setattr(store, "GAP", 0)
    return tmp_path


def row(idx, year=2026, period=2):
    return {"disclosureClass": "FR", "subject": "Finansal Rapor", "year": year, "period": period,
            "disclosureIndex": idx, "stockCodes": "TRGYO"}


def test_queue_order_and_dedupe(fin_dir):
    st = {}
    assert store.enqueue(st, "TRGYO", row(1652359))
    assert store.enqueue(st, "TRGYO", row(1652360))
    assert not store.enqueue(st, "TRGYO", row(1652360))          # aynı bildirim iki kez
    store.enqueue(st, "TRGYO", row(1571106, 2025, 4))
    store.enqueue(st, "AKBNK", row(1637885))
    assert st["queue"]["TRGYO"]["2026/06"] == [1652359, 1652360]
    jobs = store.next_jobs(st)
    assert jobs[0][1] == "2026/06" and jobs[-1] == ("TRGYO", "2025/12")


def test_process_period_stops_at_consolidated():
    cons, solo = load("trgyo_2026_06"), load("trgyo_2026_06_b")
    calls = []

    def fake(idx):
        calls.append(idx)
        return {**(cons if idx == 1652360 else solo), "idx": idx}
    rep = store.process_period("TRGYO", "2026/06", [1652359, 1652360], fetch=fake)
    assert rep["consolidated"] and calls == [1652360]


def test_save_report_keeps_consolidated(fin_dir):
    cons, solo = load("trgyo_2026_06"), load("trgyo_2026_06_b")
    store.save_report("TRGYO", "TORUNLAR", "2026/06", cons)
    store.save_report("TRGYO", "TORUNLAR", "2026/06", solo)
    doc = store._load(fin_dir / "TRGYO.json", {})
    assert doc["reports"]["2026/06"]["consolidated"] is True
    assert doc["template"] == "sanayi" and doc["currency"] == "TRY"


def test_run_end_to_end_with_fakes(fin_dir, monkeypatch):
    monkeypatch.setattr(store.kapfin, "fetch_indices", lambda: {"XU100": [
        {"code": "TRGYO", "title": "TORUNLAR", "oid": "o1"}]})
    monkeypatch.setattr(store.kapfin, "fetch_sectors", lambda: {"TRGYO": {"sector": "GYO", "main": "MALİ"}})
    monkeypatch.setattr(store.kapfin, "recent_reports", lambda days=3: [])
    monkeypatch.setattr(store.kapfin, "list_reports", lambda oid, a, b: [row(1652359), row(1652360)])
    monkeypatch.setattr(store, "update_cpi", lambda: True)
    cons = load("trgyo_2026_06")
    monkeypatch.setattr(store.kapfin, "fetch_export", lambda idx: {**cons, "idx": idx})
    # process_period'un varsayılan argümanı modül yüklenirken bağlandı; sahtesini doğrudan ver
    real = store.process_period
    monkeypatch.setattr(store, "process_period", lambda c, p, i: real(c, p, i, fetch=store.kapfin.fetch_export))
    s = store.run(budget=60)
    assert s["processed"] == 1 and s["pending"] == 0 and s["listed_total"] == 1
    uni = store._load(fin_dir / "_universe.json", {})
    assert uni["members"][0]["sector"] == "GYO"
    doc = store._load(fin_dir / "TRGYO.json", {})
    assert doc["reports"]["2026/06"]["is"]["rows"]["Hasılat"][0] == 8764874
    # ikinci çalıştırma: yeni iş yok, liste yeniden çekilmez
    s2 = store.run(budget=60)
    assert s2["processed"] == 0 and s2["listed"] == 0
