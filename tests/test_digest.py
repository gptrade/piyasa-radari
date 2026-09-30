import json
from datetime import timedelta

from radar import digest
from radar.models import iso, now_utc


def item(i, minutes, sent="bullish", conf=80, mat="high", tk="TTKOM"):
    return {"id": f"id{i}", "published": iso(now_utc() - timedelta(minutes=minutes)), "tickers": [tk],
            "title": f"haber {i}", "source": "KAP", "tier": 1,
            "analysis": {"sentiment": sent, "confidence": conf, "materiality": mat,
                         "headline_tr": f"başlık {i}", "event_label": "Geri alım", "why": "talep artar"},
            "reaction": {"since": 1.2, "excess": 0.3, "vol_x": 2.5}}


class FakeAnalyzer:
    enabled = True

    def __init__(self, out):
        self.out, self.calls = out, []

    def ask_json(self, system, prompt, tool, fmt, max_tokens=1500):
        self.calls.append(prompt)
        return dict(self.out)


def test_window_widens_when_few_signals():
    now = now_utc()
    items = [item(1, 30), item(2, 200), item(3, 300), {"id": "x", "published": iso(now), "tickers": []}]
    hours, sigs = digest.pick_window(items, now)
    assert hours == 6 and {d["id"] for d in sigs} == {"id1", "id2", "id3"}


def test_update_filters_ids_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_FILE", tmp_path / "digest.json")
    items = [item(1, 10), item(2, 20), item(3, 40, "bearish", 60, "medium", "VAKBN")]
    fa = FakeAnalyzer({"headline": "Geri alımlar öne çıktı", "mood": "olumlu", "summary": "Özet.",
                       "ideas": [{"ticker": "ttkom", "stance": "AL", "title": "TTKOM geri alım", "rationale": "r",
                                  "risk": "k", "conviction": 70, "item_ids": ["id1", "uydurma"]},
                                 {"ticker": "VAKBN", "stance": "izle", "title": "t", "rationale": "r",
                                  "risk": "k", "conviction": 40, "item_ids": ["id3"]},
                                 {"ticker": "FAZLA", "stance": "AL"}],
                       "conflicts": ["VAKBN haber olumsuz, fiyat yükseliyor"], "_provider": "Gemini", "_model": "g"})
    d = digest.update(fa, items, {})
    assert d["ideas"][0]["ticker"] == "TTKOM" and d["ideas"][0]["item_ids"] == ["id1"]
    assert d["ideas"][1]["stance"] == "İZLE" and len(d["ideas"]) == 2
    assert d["provider"] == "Gemini" and d["window_hours"] == 2
    assert "[id1]" in fa.calls[0] and "endekse göre +0.3%" in fa.calls[0] and "hacim 2.5×" in fa.calls[0]
    digest.update(fa, items, {})                       # aynı sinyaller, taze özet → yeniden sorma
    assert len(fa.calls) == 1
    digest.update(fa, items + [item(4, 5)], {})        # yeni sinyal → yeniden üret
    assert len(fa.calls) == 2
    assert json.loads((tmp_path / "digest.json").read_text())["count"] == 4


def test_no_signals_writes_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(digest, "DIGEST_FILE", tmp_path / "digest.json")
    d = digest.update(FakeAnalyzer({}), [], {})
    assert d["empty"] is True
