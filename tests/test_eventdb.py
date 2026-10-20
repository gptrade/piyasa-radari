import json
from datetime import date

import pandas as pd

from radar import eventdb as E

UTC = "UTC"


def T(s):
    return pd.Timestamp(s, tz=UTC)


def test_kap_type_and_rows():
    assert E.kap_type("Pay Geri Alımına İlişkin Bildirim")[0] == "geri_alim"
    assert E.kap_type("Finansal Rapor")[0] == "finansal"
    assert E.kap_type("Özel Durum Açıklaması (Genel)", "Yeni İş İlişkisi")[0] == "is_iliskisi"
    rows = E.from_kap_rows([{"publishDate": "20.10.2026 18:42:10", "disclosureIndex": 7, "relatedStocks": "ISCTR, ISATR",
                             "subject": "Finansal Rapor", "summary": "", "kapTitle": "TÜRKİYE İŞ BANKASI A.Ş."}])
    assert [r["sym"] for r in rows] == ["ISCTR", "ISATR"] and rows[0]["ts"] == T("2026-10-20 15:42:10")
    assert rows[0]["id"] == "kap:7" and rows[0]["dir"] is None


def test_merge_fills_ai_direction_and_keeps_first_seen():
    kap = E.from_kap_rows([{"publishDate": "20.10.2026 10:30:00", "disclosureIndex": 9, "relatedStocks": "ENTRA", "subject": "Özel Durum Açıklaması (Genel)"}])
    first, dup = E.merge(None, kap, T("2026-10-20 08:00"))
    feed = E.from_feed([{"source": "KAP", "source_type": "disclosure", "market": "BIST", "published": "2026-10-20T07:30:00Z", "tickers": ["ENTRA"],
                         "title": "x", "extra": {"index": 9, "subject": "Özel Durum Açıklaması (Genel)"}, "id": "f1",
                         "analysis": {"sentiment": "bullish", "confidence": 70, "materiality": "high", "category": "yeni iş"}}])
    out, dup2 = E.merge(first, feed + feed, T("2026-10-20 09:00"))
    assert len(out) == 1 and dup2 == 1
    r = out.iloc[0]
    assert r["dir"] == 1 and abs(r["conf"] - 0.7) < 1e-9 and r["mat"] == "high"
    assert r["ingested"] == T("2026-10-20 08:00")                      # ilk görülme korunur
    assert json.loads(r["payload"])["ai"] is True


def test_research_buyback_dividend_calendar():
    res = E.from_research([{"id": "r1", "t": "AAPL", "m": "US", "ts": "2026-10-01T12:00:00Z", "tp": 330, "prev": 370, "action": "down", "dir": 0, "broker": "X"}])
    assert res[0]["type"] == "hedef_degisim" and res[0]["dir"] == -1 and abs(res[0]["mag"] + 0.1081) < 1e-3
    assert E.from_research([{"id": "r2", "t": None, "ts": "2026-10-01T12:00:00Z"}]) == []
    bb = E.from_buybacks([{"disclosure_index": 5, "publish_date": "20.10.2026 22:43:15", "tickers": "AKHAN", "pct_this_transaction": 0.01}])
    assert bb[0]["type"] == "geri_alim" and bb[0]["mag"] == 0.01
    dv = E.from_dividends({"ZEDUR": [{"decision": "2025-03-20", "idx": 11, "status": "yok", "net": 0}]})
    assert dv[0]["subtype"] == "ödenmeyecek" and dv[0]["ts"] == T("2025-03-20 15:30")
    cal = E.from_calendar([{"kind": "data", "when": "2026-10-06T12:00+03:00", "title": "PMI", "id": "c1"},
                           {"kind": "data", "when": "2026-12-06T12:00+03:00", "title": "gelecek"},
                           {"kind": "earnings", "when": "2026-10-06T12:00+03:00", "title": "kazanç", "ticker": None}], T("2026-10-20"))
    assert [c["id"] for c in cal] == ["cal:c1"]


def test_ts_effective_sessions():
    sess = [date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)]       # Cuma, Pazartesi, Salı
    # seans içi: kendisi
    t, d = E.ts_effective(T("2026-10-19 09:00"), "BIST", sess)
    assert t == T("2026-10-19 09:00") and d == date(2026, 10, 19)
    # kapanış sonrası Cuma → Pazartesi açılışı (10:00 İstanbul = 07:00 UTC)
    t, d = E.ts_effective(T("2026-10-16 16:30"), "BIST", sess)
    assert t == T("2026-10-19 07:00") and d == date(2026, 10, 19)
    # açılış öncesi: aynı günün açılışı
    t, d = E.ts_effective(T("2026-10-20 05:00"), "BIST", sess)
    assert t == T("2026-10-20 07:00")
    # ABD: 16:00 New York sonrası (EDT, 20:00 UTC) → ertesi gün 13:30 UTC
    t, d = E.ts_effective(T("2026-10-20 20:30"), "US", [])
    assert t == T("2026-10-21 13:30")


def _px():
    days = pd.bdate_range("2026-09-01", periods=40).date
    rows = []
    for i, d in enumerate(days):
        rows.append({"sym": "XU100", "date": d, "close": 100 + i, "adj_close": 100 + i, "volume": 0})
        rows.append({"sym": "AAA", "date": d, "close": 10 * (1.01 ** i), "adj_close": 10 * (1.01 ** i), "volume": 1})
    return pd.DataFrame(rows), list(days)


def test_event_returns_market_adjusted():
    px, days = _px()
    sess = sorted(days)
    t, _ = E.ts_effective(pd.Timestamp(f"{days[10]} 16:00", tz="UTC"), "BIST", sess)     # kapanış sonrası → days[11] açılışı
    ev = pd.DataFrame([{"id": "e", "sym": "AAA", "market": "BIST", "ts_eff": t}])
    r = E.event_returns(ev, px).iloc[0]
    assert r["d0"] == days[10]
    exp1 = (1.01 - 1) * 100 - ((111 / 110) - 1) * 100
    assert abs(r["ar1"] - round(exp1, 3)) < 1e-3
    assert abs(r["r5"] - round((1.01 ** 5 - 1) * 100, 3)) < 1e-3
    assert abs(r["r20"] - round((1.01 ** 20 - 1) * 100, 3)) < 1e-3
    late = pd.DataFrame([{"id": "l", "sym": "AAA", "market": "BIST", "ts_eff": pd.Timestamp(f"{days[35]} 08:00", tz="UTC")}])
    rl = E.event_returns(late, px).iloc[0]
    assert pd.notna(rl["r1"]) and pd.isna(rl.get("r20"))                        # 20 seanslık vade henüz dolmadı


def test_px_gap_ratio():
    px, days = _px()
    px = px[~((px.sym == "AAA") & (px.date == days[5]))]
    g, worst = E.px_gap_ratio(px, ["AAA"], days[0])
    assert abs(g - 1 / 40) < 1e-9 and worst == ["AAA"]


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "EV_DIR", tmp_path / "events")
    rows = E.from_kap_rows([{"publishDate": "20.10.2026 10:30:00", "disclosureIndex": 1, "relatedStocks": "A", "subject": "Finansal Rapor"},
                            {"publishDate": "30.09.2026 10:30:00", "disclosureIndex": 2, "relatedStocks": "B", "subject": "Finansal Rapor"}])
    df, _ = E.merge(None, rows, T("2026-10-20 12:00"))
    df["ts_eff"] = df["ts"]
    E.save_events(df)
    assert sorted(p.name for p in (tmp_path / "events").iterdir()) == ["2026-09.parquet", "2026-10.parquet"]
    back = E.load_events()
    assert len(back) == 2 and set(back.id) == {"kap:1", "kap:2"}


def test_clusters_group_same_story():
    rows = [E._row(id="a", sym="AAPL", ts=T("2026-10-20 10:00"), title="Apple iPhone 18 Pro bileşen siparişlerini kıstı"),
            E._row(id="b", sym="AAPL", ts=T("2026-10-20 12:00"), title="Apple, iPhone 18 Pro bileşen siparişlerini kesti"),
            E._row(id="c", sym="AAPL", ts=T("2026-10-20 13:00"), title="Citi Apple hedef fiyatını yükseltti"),
            E._row(id="d", sym="MSFT", ts=T("2026-10-20 12:00"), title="Apple iPhone 18 Pro bileşen siparişlerini kıstı")]
    df = pd.DataFrame(rows, columns=E.COLS)
    df["cluster"] = E.clusters(df)
    assert list(df.cluster) == ["a", "a", "c", "d"]
    assert E.near_dups(df) == (1, 4)
