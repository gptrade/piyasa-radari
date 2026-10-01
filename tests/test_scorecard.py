from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from radar import scorecard as sc
from radar.models import iso

IST = ZoneInfo("Europe/Istanbul")


def day_ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=IST).timestamp())


def px_with(closes, idx_closes, intraday=None):
    days = [(2026, 9, d) for d in (21, 22, 23, 24, 25, 28, 29, 30)]
    st = {"market": "BIST", "daily": [[day_ts(*dd), c] for dd, c in zip(days, closes)], "intraday": intraday or []}
    ix = {"market": "BIST", "daily": [[day_ts(*dd), c] for dd, c in zip(days, idx_closes)], "intraday": []}
    return {"THYAO": st, "_XU100": ix}


def item(pub, sent="bullish", conf=80, label="İş ilişkisi"):
    return {"id": f"x{pub}{sent}{label}", "tickers": ["THYAO"], "market": "BIST", "published": pub, "source": "KAP",
            "source_type": "disclosure", "tier": 1, "event": "deal",
            "analysis": {"sentiment": sent, "confidence": conf, "materiality": "high", "event_label": label,
                         "provider": "gemini"}}


def test_price_at_never_uses_same_day_daily_close():
    px = px_with([100, 101, 102, 103, 104, 105, 106, 107], [10] * 8)
    # gün içi veri yok: 23 Eylül 14:00 haberi için baz 22 Eylül kapanışı (101), 23'ün kapanışı DEĞİL
    assert sc.price_at("2026-09-23T11:00:00Z", px["THYAO"], IST) == 101


def test_grade_excess_vs_index_and_waits_for_closed_sessions(monkeypatch):
    px = px_with([100, 100, 100, 110, 110, 110, 121, 121], [10, 10, 10, 10.5, 10.5, 10.5, 10.5, 10.5])
    monkeypatch.setattr(sc, "now_utc", lambda: datetime(2026, 9, 26, 12, tzinfo=IST))
    r = sc.record(item("2026-09-23T11:00:00Z"), px, {"THYAO"})
    assert r["p0"] == 100 and r["i0"] == 10
    assert sc.grade(r, px)
    assert r["r1"] == 10.0 and r["x1"] == 5.0          # 24 Eylül: hisse +%10, endeks +%5
    assert "x5" not in r                                # 5. seans henüz yok
    monkeypatch.setattr(sc, "now_utc", lambda: datetime(2026, 10, 1, 12, tzinfo=IST))
    sc.grade(r, px)
    assert r["r5"] == 21.0 and r["x5"] == 16.0          # 30 Eylül kapanışı


def test_neutral_and_unwatched_not_archived():
    px = px_with([100] * 8, [10] * 8)
    assert sc.record(item("2026-09-23T11:00:00Z", "neutral"), px, {"THYAO"}) is None
    assert sc.record(item("2026-09-23T11:00:00Z"), px, {"AKBNK"}) is None


def test_update_dedups_same_event_and_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "ARCHIVE", tmp_path / "s.json")
    monkeypatch.setattr(sc, "SCORE", tmp_path / "c.json")
    monkeypatch.setattr(sc, "now_utc", lambda: datetime(2026, 10, 1, 12, tzinfo=IST))
    px = px_with([100, 100, 100, 110, 110, 110, 121, 121], [10] * 8)
    items = [item("2026-09-23T11:00:00Z"), item("2026-09-23T12:00:00Z"),            # aynı olay 1 saat arayla
             item("2026-09-23T13:00:00Z", "bearish", 60, "Dava")]
    res = sc.update(items, px, {"THYAO"})
    assert res["added"] == 2 and res["graded"] == 2
    again = sc.update(items, px, {"THYAO"})
    assert again["added"] == 0
    import json
    card = json.loads((tmp_path / "c.json").read_text())
    tot = card["scopes"]["BIST"]["all"]["total"]["h1"]
    assert tot == {"n": 2, "hit": 50.0, "moe": 69.3, "ex": 0.0, "raw": 0.0}
    kinds = {g["g"]: g for g in card["scopes"]["ALL"]["all"]["dims"]["kind"]}
    assert kinds["Resmi bildirim (KAP/SEC)"]["count"] == 2
    conf = {g["g"]: g["h1"]["hit"] for g in card["scopes"]["ALL"]["all"]["dims"]["conf"]}
    assert conf == {"%70–84": 100.0, "%50–69": 0.0}
    assert card["scopes"]["US"]["all"]["total"]["h1"] == {"n": 0}
    assert len(card["recent"]) == 2


def test_old_records_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "ARCHIVE", tmp_path / "s.json")
    monkeypatch.setattr(sc, "SCORE", tmp_path / "c.json")
    old = {"id": "o", "k": "o", "t": "THYAO", "m": "BIST", "ts": iso(datetime(2026, 1, 1, tzinfo=IST)), "d": 1,
           "src": "KAP", "kind": "x", "ev": "news", "c": 80, "mat": "low", "pv": "AI", "p0": 1, "x1": 1, "r1": 1,
           "x5": 1, "r5": 1}
    import json
    (tmp_path / "s.json").write_text(json.dumps({"items": [old]}))
    assert sc.update([], {}, set())["total"] == 0
