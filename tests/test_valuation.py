from radar import prices
from radar.config import Stock
from radar.models import now_utc


class TK:
    def __init__(self, info):
        self.info = info


AAPL = {"trailingPE": 37.8, "forwardPE": 34.5, "priceToBook": 44.9, "enterpriseToEbitda": 29.1, "trailingPegRatio": 2.7,
        "dividendYield": 0.32, "returnOnEquity": 1.49, "profitMargins": 0.276, "trailingEps": 8.73,
        "sector": "Technology", "currency": "USD", "financialCurrency": "USD", "debtToEquity": 78.4}
THYAO = {"trailingPE": None, "forwardPE": 3.98, "priceToBook": 18.0, "enterpriseToEbitda": 184.9, "trailingEps": -6.8,
         "returnOnEquity": 0.131, "profitMargins": 0.102, "currency": "TRY", "financialCurrency": "USD", "sector": "Industrials"}


def test_valuation_fields():
    v = prices.valuation_data(TK(AAPL))
    assert v["pe"] == 37.8 and v["pb"] == 44.9 and v["peg"] == 2.7 and v["roe"] == 1.49 and v["sector"] == "Technology"
    assert "fx_mismatch" not in v


def test_currency_mismatch_hides_price_multiples():
    v = prices.valuation_data(TK(THYAO))
    assert v["fx_mismatch"] and v["fin_ccy"] == "USD"
    assert not {"pe", "fpe", "pb", "ev_ebitda", "eps"} & set(v)        # tutarsız: yazılmaz
    assert v["roe"] == 0.131 and v["margin"] == 0.102                 # oranlar kalır


def test_loss_drops_pe():
    v = prices.valuation_data(TK({**AAPL, "trailingEps": -1.0, "profitMargins": -0.05}))
    assert "pe" not in v and v["loss"]
    v = prices.valuation_data(TK({**AAPL, "trailingEps": -1.0}))          # marj pozitif: tutarsız veri, zarar sayılmaz
    assert "loss" not in v
    assert "loss" not in prices.valuation_data(TK(THYAO))


def test_valuation_refreshed_daily(tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "PRICE_DIR", tmp_path)
    monkeypatch.setattr(prices, "INDEXES", {})
    calls = []

    def fake_fetch(st, yahoo=None, analyst=False, valuation=False):
        calls.append(valuation)
        p = {"symbol": st.symbol, "last": 1}
        if valuation:
            p["valuation"] = {"updated": prices.iso(now_utc()), "pe": 10}
        return p
    monkeypatch.setattr(prices, "fetch", fake_fetch)
    st = Stock("AAPL", "Apple", "US", [])
    prices.update_all([st], None, 24)
    out = prices.update_all([st], None, 24)
    assert calls == [True, False] and out["AAPL"]["valuation"]["pe"] == 10
