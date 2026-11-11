from datetime import datetime, timezone

from radar import health

NOW = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)


def _reader(stale=False, few=False):
    def r(branch, path):
        ts = "2026-11-08T06:00:00+00:00" if stale else "2026-11-11T05:50:00+00:00"
        d = {"generated": ts, "updated": ts, "items": [1] * (10 if few else 900), "rows": [1] * 560, "stocks": [1] * 500,
             "korku": {"value": 33.0, "components": [1] * 8},
             "sources": [{"name": "KAP", "ok": True}, {"name": "X", "ok": False}, {"name": "Telegram", "ok": True}]}
        return None if (branch, path) == ("enerji", "kurulu_guc.json") else d
    return r


def test_fresh_files_ok_missing_fail():
    rows = {c["label"]: c for c in health.check_files(NOW, _reader())}
    assert rows["Sinyal akışı (15 dk)"]["status"] == "ok" and rows["Enerji"]["status"] == "fail"


def test_stale_and_thin_content_flagged():
    rows = {c["label"]: c for c in health.check_files(NOW, _reader(stale=True))}
    assert rows["Sinyal akışı (15 dk)"]["status"] == "fail" and rows["Yöntem Karnesi"]["status"] == "ok"
    rows = {c["label"]: c for c in health.check_files(NOW, _reader(few=True))}
    assert rows["Sinyal akışı (15 dk)"]["status"] == "warn"


def test_sources_and_message():
    src = health.check_sources(_reader()("data", "feed.json"))
    assert src[0]["status"] == "warn" and "X" in src[0]["detail"] and src[1]["status"] == "ok"
    d = health.run(NOW, _reader())
    m = health.message(d, "https://radar.lyracube.com")
    assert d["overall"] == "fail" and "Enerji" in m and "#kullanicilar" in m
