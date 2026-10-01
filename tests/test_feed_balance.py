from datetime import timedelta

from radar.enrich import classify_event
from radar.models import iso, now_utc
from radar.pipeline import retain


def mk(i, tk, mat="low", tier=3, hours=0, st="news"):
    return {"id": f"{tk}{i}", "tickers": [tk], "tier": tier, "source_type": st,
            "published": iso(now_utc() - timedelta(hours=hours)), "analysis": {"materiality": mat}}


def test_noisy_ticker_capped_and_low_value_dropped_first():
    items = [mk(i, "NVDA", hours=i * 0.1) for i in range(150)] + [mk(999, "NVDA", "high", hours=40)]
    items += [mk(i, "NVDA", "medium", hours=30 + i) for i in range(5)]
    out = retain(items, {"NVDA"}, max_per_ticker=50)
    nv = [d for d in out if d["tickers"] == ["NVDA"]]
    assert len(nv) == 50
    assert any(d["id"] == "NVDA999" for d in nv)                         # yüksek önemli korunur
    assert sum(1 for d in nv if d["analysis"]["materiality"] == "medium") == 5   # orta önemli düşükten önce kalır


def test_quiet_ticker_keeps_old_items_and_total_trims_crowded():
    items = [mk(i, "NVDA", hours=i * 0.1) for i in range(90)] + [mk(i, "GOZDE", hours=200 + i) for i in range(10)]
    out = retain(items, {"NVDA", "GOZDE"}, total=60, max_per_ticker=90, min_per_ticker=25)
    assert sum(1 for d in out if d["tickers"] == ["GOZDE"]) == 10            # 8+ gün önceki kayıtlar korunur
    assert len(out) == 60
    assert out == sorted(out, key=lambda d: d["published"], reverse=True)


def test_disclosures_protected_and_age_limit():
    items = [mk(i, "THYAO", tier=1, st="disclosure", hours=i) for i in range(40)] + [mk(0, "THYAO", hours=24 * 40)]
    out = retain(items, {"THYAO"}, max_per_ticker=10, max_age_days=30)
    assert len(out) == 40                                                    # KAP bildirimi kotaya takılmaz
    assert all(d["id"] != "THYAO0" or d["tier"] == 1 for d in out)


def ev(title, label=""):
    return classify_event({"title": title, "analysis": {"event_label": label, "category": "Analist Yorumu"}})


def test_analyst_only_for_broker_actions():
    assert ev("AMD upgraded to Buy after World Labs deal") == "analyst"
    assert ev("Piper Sandler raises Microsoft stock price target") == "analyst"
    assert ev("StoneX reiterates Buy rating on Microsoft") == "analyst"
    assert ev("THYAO için hedef fiyat 420 TL") == "analyst"
    assert ev("x", "Analist AL") == "analyst"
    assert ev("AMD Zen 6 Reveals Major Ryzen Upgrade Potential") == "news"
    assert ev("The Tesla Model 3 Gets A Big Upgrade") == "news"
    assert ev("Nvidia Is World's Largest Stock Yet Still Undervalued", "Analist Değerlendirmesi") == "news"
    assert ev("Top Analyst Reports for Apple, Microsoft & Broadcom") == "news"
