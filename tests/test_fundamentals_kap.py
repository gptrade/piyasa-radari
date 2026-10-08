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
    assert r["template"] == "banka"
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
    monkeypatch.setattr(store, "PRICES", tmp_path / "_prices.json")
    monkeypatch.setattr(store, "SCREEN", tmp_path / "_screen.json")
    monkeypatch.setattr(store, "update_prices", lambda codes: False)
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


def test_process_period_stops_at_consolidated(fin_dir):
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


def _fake_env(monkeypatch, fetch):
    monkeypatch.setattr(store.kapfin, "fetch_indices", lambda: {"XU100": [{"code": "TRGYO", "title": "T", "oid": "o1"}]})
    monkeypatch.setattr(store.kapfin, "fetch_sectors", lambda: {})
    monkeypatch.setattr(store.kapfin, "recent_reports", lambda days=3: [])
    monkeypatch.setattr(store.kapfin, "list_reports", lambda oid, a, b: [row(1652360)])
    monkeypatch.setattr(store, "update_cpi", lambda: True)
    real = store.process_period
    monkeypatch.setattr(store, "process_period", lambda c, p, i: real(c, p, i, fetch=fetch))


def test_rate_limit_keeps_job_and_pauses(fin_dir, monkeypatch):
    def boom(idx):
        raise store.kapfin.RateLimited("x")
    _fake_env(monkeypatch, boom)
    s = store.run(budget=60)
    assert s["rate_limited"] and s["pending"] == 1
    st = store._load(fin_dir / "_state.json", {})
    assert "kap_pause_until" in st
    s2 = store.run(budget=60)            # bekleme süresinde KAP'a gidilmez
    assert s2["pending"] == 1 and not s2.get("rate_limited")


def test_failed_period_retried_then_given_up(fin_dir, monkeypatch):
    _fake_env(monkeypatch, lambda idx: None)
    for _ in range(store.MAX_TRIES - 1):
        assert store.run(budget=60)["pending"] == 1
    s = store.run(budget=60)
    assert s["pending"] == 0 and s["failed"] == 1


# ---- Standart seriler (değerler ekran görüntüsündeki TRGYO 2026/06 rakamlarıyla doğrulandı) ----

from radar.fundamentals import series as S  # noqa: E402

CPI_T = {"2025-12": 3513.87, "2026-06": 3513.87 * 1.1773}


def trgyo_doc():
    return {"currency": "TRY", "reports": {"2026/06": load("trgyo_2026_06"), "2025/12": load("trgyo_2025_12")}}


def test_series_cumulative_and_quarter():
    o = S.build(trgyo_doc(), CPI_T)
    assert o["periods"] == ["2025/12", "2026/06"]
    assert o["cum"]["revenue"][1] == 8_764_874_000
    assert o["cum"]["ebitda"][1] == 6_160_912_000          # brüt − GYG − pazarlama + amortisman
    assert o["q"]["revenue"][1] == 5_172_134_000           # raporun kendi 3 aylık sütunu
    assert o["cum_prev"]["revenue"][1] == 5_355_172_000


def test_series_ttm_matches_reference():
    o = S.build(trgyo_doc(), CPI_T)
    assert abs(o["ttm"]["revenue"][1] - 20.90e9) < 0.01e9
    assert abs(o["ttm"]["ebitda"][1] - 14.34e9) < 0.01e9   # referans: 14,34 mr ₺
    assert abs(o["ttm"]["net_parent"][1] - 9.44e9) < 0.01e9  # referans: 9,44 mr ₺
    assert o["ttm"]["revenue"][0] == o["cum"]["revenue"][0]   # yıl sonu = kümülatif


def test_series_balance_debt():
    o = S.build(trgyo_doc(), CPI_T)
    assert o["bs"]["fin_debt"][1] == 12_458_860_000
    assert o["bs"]["net_debt"][1] == -3_760_467_000
    assert o["bs"]["equity_parent"][1] == 154_575_736_000
    assert o["bs"]["current_assets"][1] == 25_604_208_000


def test_q4_derived_from_annual_minus_nine_months():
    def rep(year, period, rev, end):
        start = f"{year}-01-01"
        return {"scale": 1, "is": {"cols": [{"start": start, "end": end, "prior": False}],
                                   "rows": {"Hasılat": [rev], "Net Parasal Pozisyon Kazançları (Kayıpları)": [1]}}}
    doc = {"currency": "TRY", "reports": {"2025/09": rep(2025, 3, 90, "2025-09-30"),
                                          "2025/12": rep(2025, 4, 130, "2025-12-31")}}
    o = S.build(doc, {"2025-09": 100, "2025-12": 110})
    assert abs(o["q"]["revenue"][1] - (130 - 90 * 1.1)) < 1e-6


def test_parse_sectors_multi_code():
    page = ('{"sectorName":"BANKALAR","sectorOid":"1","sectorNo":"008000.001000.",'
            '"mkkMemberOid":"x","stockCode":"GARAN, TGB","title":"GARANTİ"}')
    out = kapfin.parse_sectors(page)
    assert out["GARAN"]["sector"] == "BANKALAR" and out["TGB"]["sector"] == "BANKALAR"


def test_nominal_reports_skip_cpi_ratio():
    def rep(rev, end):
        return {"scale": 1, "is": {"cols": [{"start": end[:4] + "-01-01", "end": end, "prior": False}], "rows": {"Hasılat": [rev]}}}
    doc = {"currency": "TRY", "reports": {"2025/09": rep(90, "2025-09-30"), "2025/12": rep(130, "2025-12-31")}}
    o = S.build(doc, {"2025-09": 100, "2025-12": 110})
    assert o["q"]["revenue"][1] == 40 and o["nominal"] == [True, True]


def test_priority_jobs_bist100_first():
    st = {}
    store.enqueue(st, "AAAA", row(1, 2026, 2))
    store.enqueue(st, "THYAO", row(2, 2025, 4))
    jobs = store.next_jobs(st, {"THYAO"})
    assert jobs[0] == ("THYAO", "2025/12") and jobs[1] == ("AAAA", "2026/06")


def test_universe_from_xutum_with_index_tags(fin_dir, monkeypatch):
    monkeypatch.setattr(store.kapfin, "fetch_indices", lambda: {
        "XUTUM": [{"code": "TRGYO", "title": "T", "oid": "o1"}, {"code": "KUCUK", "title": "K", "oid": "o2"}],
        "XU100": [{"code": "TRGYO", "title": "T", "oid": "o1"}], "XU030": []})
    monkeypatch.setattr(store.kapfin, "fetch_sectors", lambda: {})
    monkeypatch.setattr(store.kapfin, "recent_reports", lambda days=3: [])
    seen = []
    monkeypatch.setattr(store.kapfin, "list_reports", lambda oid, a, b: seen.append((oid, a)) or [])
    monkeypatch.setattr(store, "update_cpi", lambda: True)
    store.run(budget=60)
    uni = store._load(fin_dir / "_universe.json", {})
    assert uni["index"] == "XUTUM" and {m["code"]: m["idx"] for m in uni["members"]} == {"TRGYO": ["XU100"], "KUCUK": []}
    assert seen[0] == ("o1", store.HISTORY_START) and seen[1] == ("o2", store.HISTORY_START_EXT)
