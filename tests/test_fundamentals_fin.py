"""Banka ve sigorta şablonları: ayrıştırma, kalem eşleme, oranlar (gerçek KAP 2026/06 tabloları)."""
import json
from pathlib import Path

from radar.fundamentals import kapfin, metrics as M, series as S

FX = Path(__file__).parent / "fixtures" / "kapfin"
CPI = json.loads((FX / "cpi.json").read_text())


def rep(name):
    return kapfin.parse_export((FX / f"{name}_2026_06_full.html").read_bytes())


def test_bank_template_and_tp_yp_balance():
    r = rep("akbnk")
    assert r["template"] == "banka" and r["consolidated"] and r["scale"] == 1_000_000
    assert [c["end"] for c in r["bs"]["cols"]] == ["2026-06-30", "2025-12-31"]
    b = S.balance(r, "banka")
    assert b["loans"] == 2_232_877e6 and b["deposits"] == 2_511_089e6      # TP+YP toplamı
    assert b["total_assets"] == b["total_liab_eq"] == 4_012_479e6
    f = S.flows(r, tmpl="banka")
    assert f["nii"] == 88_026e6 and f["revenue"] == 146_518e6 and f["net_parent"] == 34_350e6
    assert f["opex"] == -(27_044e6 + 46_306e6)
    assert not S.tms29(r)                                                  # bankalar nominal


def test_insurer_template_and_sums():
    r = rep("ansgr")
    assert r["template"] == "sigorta" and "cf" in r                       # "Nakit Akım Tablosu"
    f = S.flows(r, tmpl="sigorta")
    assert f["revenue"] == 54_189_705_323 and f["net_earned"] == 40_074_400_283
    assert f["claims"] == -31_729_141_926 and f["net_parent"] == 7_396_626_681
    b = S.balance(r, "sigorta")
    assert b["tech_reserves"] == 82_395_051_067 + 2_416_774_566            # KV + UV teknik karşılıklar


def test_brokerage_stays_standard():
    assert rep("ismen")["template"] == "sanayi"


def _as_annual(r):
    """Tek dönem fikstürünü yıl sonu gibi kullan (12A = kümülatif) — oran hesabını sınamak için."""
    r = json.loads(json.dumps(r))
    for kind in ("is", "cf"):
        for c in r[kind]["cols"]:
            c["end"] = c["end"][:4] + "-12-31" if c.get("start", "").endswith("-01-01") else c["end"]
    return r


def test_bank_and_insurer_ratios():
    for name, tmpl in (("garan", "banka"), ("ansgr", "sigorta")):
        r = _as_annual(rep(name))
        doc = {"code": name.upper(), "currency": "TRY", "template": tmpl, "reports": {"2025/12": r}}
        doc["series"] = S.build(doc, CPI)
        m = M.company(doc, 100.0)
        assert m and m["template"] == tmpl and set(m["categories"]) == set(M.FIN_CATEGORIES[tmpl])
        x = m["ratios"]
        if tmpl == "banka":
            assert abs(x["cost_income"] - 107_916 / 257_024) < 1e-3
            assert abs(x["ldr"] - 2_997_999 / 3_466_148) < 1e-3
            assert abs(x["equity_assets"] - 486_659 / 5_216_482) < 1e-3
            assert "Banka Sağlık Kontrolü" in m["criteria"]
        else:
            assert abs(x["loss_ratio"] - 31_729_141_926 / 40_074_400_283) < 1e-4
            assert abs(x["combined"] - (31_729_141_926 + 11_991_204_014 + 1_416_186_182) / 40_074_400_283) < 1e-4
            assert x["inflation"] and x["real_roe"] is not None
        assert m["valuation"]["pb"] > 0
