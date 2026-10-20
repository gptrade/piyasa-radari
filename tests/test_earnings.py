from radar import earnings as E


def test_seasonal_surprise_real_terms():
    cpi = [100.0] * 4 + [200.0] * 5            # fiyat düzeyi ikiye katlandı
    q = [10, 10, 10, 10, 20, 20, 20, 20, 40]   # nominal ikiye katlanma reelde değişimsiz; son çeyrek reel olarak iki kat
    s = E.sue_series(q, cpi)
    assert abs(s[4]["su"]) < 1e-9
    assert abs(s[8]["su"] - 1.0) < 1e-9 and E.direction(s[8]["su"]) == 1
    assert E.direction(0.1) == 0 and E.direction(-0.3) == -1 and E.direction(None) is None
