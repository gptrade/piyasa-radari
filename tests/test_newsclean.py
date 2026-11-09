from radar import newsclean as N

P = "2026-11-07T10:00:00Z"


def test_stale_detects_republished_old_events():
    assert N.is_stale("Tesla (TSLA) Delays Cybertruck Launch to Late November 2023 Amid Pricing", P)
    assert N.is_stale("Tesla Plans to Halt Cybertruck Production in Texas by Mid-2024", P)
    assert N.is_stale("x", P, "Tesla Cybertruck lansmanını 2023'e erteledi")


def test_stale_keeps_historical_comparisons():
    for t in ("Nvidia Stock Eyes a Negative Streak Unseen Since 2012",
              "Tech just had a crisis-sized day — the kind that came in 2000, 2008, and 2020",
              "Apple's record-breaking Q4 beat Covid-fueled 2020 holiday quarter",
              "Microsoft Is Borrowing $25 Billion, Its First Bond Sale Since 2017",
              "Tesla, 2027'de Cybertruck üretimini durduracak", "THYAO 2025 yılı bilançosu"):
        assert not N.is_stale(t, P), t


def _it(title, tk, src, ts=P, tier=3, ai=None):
    return {"title": title, "tickers": tk, "source": src, "source_type": "news", "published": ts, "tier": tier,
            "analysis": {"headline_tr": ai} if ai else None}


def test_cluster_merges_same_event_across_languages():
    items = [
        _it("Tesla cuts Cybertruck output to focus on robotaxi", ["TSLA"], "Reuters", tier=1,
            ai="Tesla, Cybertruck üretimini azaltıp robotaxi kapasitesine odaklanıyor"),
        _it("Tesla Cybertruck üretimini azaltıp Cybercab'e odaklanacak", ["TSLA"], "Bloomberg HT",
            ai="Tesla, Cybertruck üretimini azaltıp Cybercab'e odaklanacak"),
        _it("Tesla cancels Cybertruck orders in two countries", ["TSLA"], "CNBC",
            ai="Tesla, Cybertruck siparişlerini iki ülkede iptal etti"),
        _it("Tesla cuts Cybertruck output to focus on robotaxi", ["F"], "X"),                 # başka hisse
        _it("Tesla cuts Cybertruck output", ["TSLA"], "Old", ts="2026-11-01T10:00:00Z",
            ai="Tesla, Cybertruck üretimini azaltıp robotaxi kapasitesine odaklanıyor"),    # 72 saat dışı
    ]
    out = N.cluster(items)
    assert len(out) == 4
    rep = out[0]
    assert rep["source"] == "Reuters" and rep["dups"] == 1 and rep["dup_sources"] == ["Bloomberg HT"]
