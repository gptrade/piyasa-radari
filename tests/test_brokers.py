from radar import brokers as B


def test_canon_variants():
    assert B.canon("Ak Yatırım / Akbank") == "Ak Yatırım"
    assert B.canon("ÜNLÜ Menkul Değerler") == "ÜNLÜ & Co"
    assert B.canon("Denizbank Yatırım") == "Deniz Yatırım"
    assert B.canon("Kuveyt Türk Yatırım Menkul") == "Kuveyt Türk Yatırım"
    assert B.canon("Raymond James") == "Raymond James"
    assert B.canon("Goldman Sachs Asset Management") == "Goldman Sachs"


def test_domain():
    assert B.from_domain("research.gedik.com.tr") == "Gedik Yatırım"
    assert B.from_domain("akyatirim.com.tr") == "Ak Yatırım"
    assert B.from_domain("example.com") is None
    assert B.looks_like_domain("gedik.com.tr") and not B.looks_like_domain("Gedik Yatırım")
