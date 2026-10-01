from datetime import datetime, timedelta

from radar.models import UTC
from radar.sources import global_macro as gm

NOW = datetime(2026, 10, 2, 12, 7, tzinfo=UTC)


def series(n_bins=288, base=2, spike_last=0, norm=1000, tone=-1.0, spike_tone=None):
    start = NOW.replace(minute=0) - timedelta(minutes=15 * n_bins)
    vol, tn = [], []
    for i in range(n_bins + 1):
        t = start + timedelta(minutes=15 * i)
        recent = i >= n_bins - 8
        v = spike_last if recent and spike_last else base
        d = t.strftime("%Y%m%dT%H%M%SZ")
        vol.append({"date": d, "value": v, "norm": norm})
        tn.append({"date": d, "value": spike_tone if recent and spike_tone is not None else tone})
    return vol, tn


def test_filters():
    assert gm.keep_fed_speech("Jefferson, The U.S. Economy and Monetary Policy")
    assert not gm.keep_fed_speech("Waller, Payments in the Age of AI Agents")
    assert gm.keep_ecb("Monetary policy decisions")
    assert gm.keep_ecb("Isabel Schnabel: Monetary policy in a world of overlapping shocks")
    assert not gm.keep_ecb("Isabel Schnabel: Central banks on-chain")
    assert not gm.keep_ecb("Frank Elderson: Supervisory risk appetite, efficiency and effectiveness")


def test_quiet_theme_no_alarm():
    vol, tn = series()
    s = gm.spike(vol, tn, NOW)
    assert s["ratio"] == 1.0 and gm.triggered(s, {}) is None


def test_volume_spike():
    vol, tn = series(spike_last=10)
    s = gm.spike(vol, tn, NOW)
    assert s["count"] >= 70 and s["ratio"] >= 4
    assert gm.triggered(s, {}) == "hacim"


def test_tone_shift_needs_volume():
    vol, tn = series(spike_tone=-5.0)
    s = gm.spike(vol, tn, NOW)
    assert s["count"] == 16 and gm.triggered(s, {}) == "ton"                 # 16 haber ≥ 12, ton −4
    assert gm.triggered(s, {"min_count": 50}) is None


def test_item_text():
    vol, tn = series(spike_last=10, spike_tone=-4.0)
    s = gm.spike(vol, tn, NOW)
    it = gm.gdelt_item(gm.DEFAULT_THEMES[0], s, gm.triggered(s, {}),
                       [{"title": "Lira slides", "domain": "reuters.com", "url": "https://r/1"}], NOW)
    assert it.source_type == "macro" and it.market == "BIST" and it.url == "https://r/1"
    assert "kat" in it.title and "sertleşti" in it.title and "Lira slides (reuters.com)" in it.summary
    assert it.extra["gdelt"]["why"] == "hacim+ton"


def test_turkey_filter_and_article_text():
    assert not gm.MUST["IMF"].search("Türkiye ile Ukrayna arasındaki Serbest Ticaret Anlaşması")
    assert gm.TURKEY.search("IMF Türkiye'nin büyüme tahminini yükseltti")
    assert gm.TURKEY.search("US sanctions Turkish firms over Russia trade")
    assert not gm.TURKEY.search("Lübnan’a yeni IMF programı için reformlar şart")
    page = '<nav>Menu Home About</nav><div id="article"><p>For release at 2:00 p.m.</p><p>Inflation remains elevated.</p></div>'
    t = gm.article_text(page)
    assert t.startswith("For release at") and "Menu" not in t and "Inflation remains elevated." in t
