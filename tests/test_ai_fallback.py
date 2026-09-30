"""Claude → Gemini yedekleme mantığı."""
import json

import pytest

from radar import analyze
from radar.analyze import Analyzer, ClaudeProvider, GeminiProvider, ProviderDown, normalize, parse_json_text
from radar.models import Item

GOOD = {"sentiment": "bullish", "confidence": 80, "materiality": "high", "horizon": "days",
        "category": "geri alım", "headline_tr": "Başlık", "summary": "Özet", "key_points": ["a"],
        "risks": ["r"], "affected_tickers": ["ttkom"]}
ITEM = Item(source="KAP", source_type="disclosure", market="BIST", title="TTKOM: geri alım",
            url="https://kap/1", published="2026-09-30T10:00:00Z", tickers=["TTKOM"])


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "g")


class FakeResp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._p, self.text = status, payload, text or json.dumps(payload or {})

    def json(self):
        return self._p


def gemini_ok(obj):
    return FakeResp(200, {"candidates": [{"content": {"parts": [{"text": "```json\n" + json.dumps(obj) + "\n```"}]}}]})


def test_normalize_and_json_parsing():
    n = normalize({**GOOD, "confidence": 0.72, "materiality": "huge"})
    assert n["confidence"] == 72 and n["materiality"] == "low" and n["affected_tickers"] == ["TTKOM"]
    assert normalize({"sentiment": "moon"}) is None
    assert parse_json_text('Açıklama: {"sentiment": "neutral"} bitti') == {"sentiment": "neutral"}


def test_claude_first_when_healthy(keys, monkeypatch):
    monkeypatch.setattr(ClaudeProvider, "assess", lambda self, s, p: GOOD)
    monkeypatch.setattr(GeminiProvider, "assess", lambda self, s, p: pytest.fail("Gemini çağrılmamalı"))
    a = Analyzer({"analysis": {}})
    out = a.assess(ITEM)
    assert out["provider"] == "Claude" and a.status()["by_provider"] == {"Claude": 1}


def test_fallback_to_gemini_when_claude_out_of_credit(keys, monkeypatch):
    calls = {"claude": 0}

    def broke(self, s, p):
        calls["claude"] += 1
        raise ProviderDown("BadRequestError: Your credit balance is too low")
    monkeypatch.setattr(ClaudeProvider, "assess", broke)
    monkeypatch.setattr(analyze.time, "sleep", lambda s: None)
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: gemini_ok(GOOD))
    a = Analyzer({"analysis": {}})
    o1, o2 = a.assess(ITEM), a.assess(ITEM)
    assert o1["provider"] == o2["provider"] == "Gemini"
    assert calls["claude"] == 1                      # kredi bitince bu tur Claude bir daha denenmez
    st = a.status()
    assert "Claude" in st["down"] and st["by_provider"] == {"Gemini": 2} and st["model"] == "gemini-3.8-flash"


def test_claude_billing_error_is_classified_as_down(monkeypatch):
    class BadRequestError(Exception):
        status_code = 400

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                raise BadRequestError("Your credit balance is too low to access the Anthropic API")
    p = ClaudeProvider("m")
    p._client = FakeClient()
    with pytest.raises(ProviderDown):
        p.assess("s", "p")


def test_gemini_retired_model_falls_through(monkeypatch):
    import requests
    seen = []

    def post(url, **kw):
        seen.append(url.split("/models/")[1].split(":")[0])
        return FakeResp(404, text="model not found") if len(seen) == 1 else gemini_ok(GOOD)
    monkeypatch.setattr(requests, "post", post)
    g = GeminiProvider(["gemini-9-flash", "gemini-flash-latest"], "k")
    assert g.assess("s", "p")["sentiment"] == "bullish"
    assert seen == ["gemini-9-flash", "gemini-flash-latest"] and g.model == "gemini-flash-latest"


def test_gemini_bad_key_marks_down(monkeypatch):
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: FakeResp(403, text="API key not valid"))
    with pytest.raises(ProviderDown):
        GeminiProvider(["gemini-3.8-flash"], "k").assess("s", "p")


def test_only_gemini_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: gemini_ok(GOOD))
    a = Analyzer({"analysis": {}})
    assert a.status()["providers"] == ["Gemini"] and a.assess(ITEM)["provider"] == "Gemini"


def test_both_down_returns_none(keys, monkeypatch):
    monkeypatch.setattr(ClaudeProvider, "assess", lambda self, s, p: (_ for _ in ()).throw(ProviderDown("x")))
    monkeypatch.setattr(GeminiProvider, "assess", lambda self, s, p: (_ for _ in ()).throw(ProviderDown("y")))
    a = Analyzer({"analysis": {}})
    assert a.assess(ITEM) is None and not a.can_run()
