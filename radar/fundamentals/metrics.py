"""Oranlar, skorlar ve kriter setleri.

Girdi: şirket dosyasındaki `series` (bkz. series.py), TÜFE, son fiyat.
Birimler: akışlar 12A (son 12 ay), bilanço dönem sonu; bir yıl önceki değerler TÜFE ile bugünkü
döneme taşınır (reel karşılaştırma). Çarpanlar piyasa değeri / 12A (TMS 29 raporlarıyla aynı birim).
"""
from __future__ import annotations

import math
from statistics import median

# ---------- yardımcılar ----------


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _clip01(x):
    return max(0.0, min(1.0, x))


def _year_ago(pk: str) -> str:
    y, m = pk.split("/")
    return f"{int(y) - 1}/{m}"


class View:
    """Seri erişimi: değer(grup, kalem, dönem), TÜFE dönüşümü, ortalama bilanço."""

    def __init__(self, ser: dict, currency: str = "TRY"):
        self.s = ser
        self.p = ser.get("periods", [])
        self.pos = {pk: i for i, pk in enumerate(self.p)}
        self.cpi = dict(zip(self.p, ser.get("cpi", [])))
        self.cur = currency

    def v(self, grp: str, item: str, pk: str):
        i = self.pos.get(pk)
        if i is None:
            return None
        arr = self.s.get(grp, {}).get(item)
        return arr[i] if arr and i < len(arr) else None

    def conv(self, frm: str, to: str) -> float:
        if self.cur != "TRY":
            return 1.0
        a, b = self.cpi.get(to), self.cpi.get(frm)
        return a / b if a and b else 1.0

    def ya(self, grp: str, item: str, pk: str):
        """Bir yıl önceki değer, bugünkü dönemin TL'sine taşınmış."""
        prev = _year_ago(pk)
        v = self.v(grp, item, prev)
        return v * self.conv(prev, pk) if v is not None else None

    def avg_bs(self, item: str, pk: str):
        now, old = self.v("bs", item, pk), self.ya("bs", item, pk)
        if now is None:
            return None
        return (now + old) / 2 if old is not None else now


# ---------- şirket oranları ----------

def ratios(view: View, pk: str) -> dict:
    t = lambda k: view.v("ttm", k, pk)  # noqa: E731
    b = lambda k: view.v("bs", k, pk)   # noqa: E731
    rev = t("revenue")
    r: dict = {}
    # Karlılık
    r["gross_margin"] = _div(t("gross"), rev)
    r["ebitda_margin"] = _div(t("ebitda"), rev)
    r["op_margin"] = _div(t("op_profit"), rev)
    core = (t("ebitda") - t("da")) if t("ebitda") is not None and t("da") is not None else None
    r["core_margin"] = _div(core, rev)
    r["net_margin"] = _div(t("net_parent"), rev)
    r["roe"] = _div(t("net_parent"), view.avg_bs("equity_parent", pk))
    r["roa"] = _div(t("net_parent"), view.avg_bs("total_assets", pk))
    ic_now = _invested(view, pk)
    nopat = t("op_profit") * 0.75 if t("op_profit") is not None else None
    r["roic"] = _div(nopat, ic_now) if ic_now and ic_now > 0 else None
    # Reel büyüme (12A, bir yıl öncesine göre)
    for k, item in (("rev_growth", "revenue"), ("ebitda_growth", "ebitda"), ("net_growth", "net_parent")):
        old = view.ya("ttm", item, pk)
        r[k] = (t(item) / old - 1) if t(item) is not None and old and old > 0 else None
    old_ta = view.ya("bs", "total_assets", pk)
    r["asset_growth"] = (b("total_assets") / old_ta - 1) if b("total_assets") and old_ta else None
    # Finansal yapı
    r["net_debt_ebitda"] = _div(b("net_debt"), t("ebitda")) if (t("ebitda") or 0) > 0 else None
    r["debt_equity"] = _div(b("total_liab"), b("equity_parent")) if (b("equity_parent") or 0) > 0 else None
    r["fin_debt_equity"] = _div(b("fin_debt"), b("equity_parent")) if (b("equity_parent") or 0) > 0 else None
    r["liab_assets"] = _div(b("total_liab"), b("total_assets"))
    fe = t("fin_exp")
    r["interest_cov"] = _div(t("ebitda"), abs(fe)) if fe else None
    # Likidite
    r["current"] = _div(b("current_assets"), b("current_liab"))
    ca, inv = b("current_assets"), b("inventories") or 0
    r["quick"] = _div(ca - inv, b("current_liab")) if ca is not None else None
    r["cash_ratio"] = _div((b("cash") or 0) + (b("st_fin_inv") or 0), b("current_liab"))
    # Nakit akışı & kar kalitesi
    ni = t("net_parent")
    r["cfo_ni"] = _div(t("cfo"), ni) if (ni or 0) > 0 else None
    r["fcf_margin"] = _div(t("fcf"), rev)
    r["accruals"] = _div((ni - t("cfo")) if ni is not None and t("cfo") is not None else None,
                         view.avg_bs("total_assets", pk))
    # Verimlilik
    r["asset_turnover"] = _div(rev, view.avg_bs("total_assets", pk))
    cogs = abs(t("cogs")) if t("cogs") else None
    r["inv_days"] = _div(b("inventories"), cogs) * 365 if _div(b("inventories"), cogs) is not None else None
    r["rec_days"] = _div(b("receivables"), rev) * 365 if _div(b("receivables"), rev) is not None else None
    r["pay_days"] = _div(b("payables"), cogs) * 365 if _div(b("payables"), cogs) is not None else None
    if None not in (r["inv_days"], r["rec_days"], r["pay_days"]):
        r["ccc"] = r["inv_days"] + r["rec_days"] - r["pay_days"]
    else:
        r["ccc"] = None
    return r


def _invested(view: View, pk: str):
    eq, debt = view.v("bs", "equity_total", pk), view.v("bs", "fin_debt", pk)
    if eq is None:
        return None
    cash = (view.v("bs", "cash", pk) or 0) + (view.v("bs", "st_fin_inv", pk) or 0)
    return eq + (debt or 0) - cash


def valuation(view: View, pk: str, price: float | None) -> dict:
    t = lambda k: view.v("ttm", k, pk)  # noqa: E731
    b = lambda k: view.v("bs", k, pk)   # noqa: E731
    shares = b("paid_capital")          # BIST'te pay başına nominal 1 TL
    out: dict = {"shares": shares}
    if not price or not shares:
        return out
    mcap = price * shares
    ev = mcap + (b("net_debt") or 0) + (b("minority") or 0)
    ni, eq, ebitda, rev = t("net_parent"), b("equity_parent"), t("ebitda"), t("revenue")
    out.update({
        "price": price, "mcap": mcap, "ev": ev,
        "eps": _div(ni, shares), "bvps": _div(eq, shares),
        "pe": _div(mcap, ni) if (ni or 0) > 0 else None,
        "pb": _div(mcap, eq) if (eq or 0) > 0 else None,
        "ev_ebitda": _div(ev, ebitda) if (ebitda or 0) > 0 else None,
        "ev_sales": _div(ev, rev) if (rev or 0) > 0 else None,
        "ps": _div(mcap, rev) if (rev or 0) > 0 else None,
        "earnings_yield": _div(t("op_profit"), ev) if ev > 0 else None,
        "fcf_yield": _div(t("fcf"), mcap),
        "div_yield": _div(abs(t("dividends_paid")), mcap) if t("dividends_paid") else 0.0,
    })
    return out


# ---------- skorlar ----------

def altman_z2(view: View, pk: str) -> float | None:
    """Altman Z'' (gelişmekte olan piyasalar / imalat dışı): 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4."""
    b = lambda k: view.v("bs", k, pk)  # noqa: E731
    ta, tl = b("total_assets"), b("total_liab")
    if not ta or not tl or b("current_assets") is None or b("current_liab") is None:
        return None
    x1 = (b("current_assets") - b("current_liab")) / ta
    x2 = ((b("retained") or 0) + (view.v("cum", "net_parent", pk) or 0)) / ta
    x3 = (view.v("ttm", "op_profit", pk) or 0) / ta
    x4 = (b("equity_total") or 0) / tl
    return 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4


def piotroski(view: View, pk: str) -> dict:
    """9 kriter; bir yıl önceki 12A ve bilançoyla. Veri yoksa kriter None."""
    ya = _year_ago(pk)
    if ya not in view.pos:
        return {"score": None, "items": []}
    t = lambda k, p=pk: view.v("ttm", k, p)  # noqa: E731
    b = lambda k, p=pk: view.v("bs", k, p)   # noqa: E731

    def roa(p):
        return _div(t("net_parent", p), b("total_assets", p))

    def lev(p):
        return _div(b("lt_borrowings", p) or 0, b("total_assets", p))

    def cur(p):
        return _div(b("current_assets", p), b("current_liab", p))

    def gm(p):
        return _div(t("gross", p), t("revenue", p))

    def at(p):
        return _div(t("revenue", p), b("total_assets", p))

    def gt(a, c):
        return None if a is None or c is None else a > c

    items = [
        ("ROA pozitif", None if roa(pk) is None else roa(pk) > 0),
        ("İşletme nakit akışı pozitif", None if t("cfo") is None else t("cfo") > 0),
        ("ROA arttı", gt(roa(pk), roa(ya))),
        ("Nakit akışı > net kar", gt(t("cfo"), t("net_parent"))),
        ("Uzun vadeli borç/varlık azaldı", gt(lev(ya), lev(pk)) if lev(pk) != lev(ya) else True),
        ("Cari oran arttı", gt(cur(pk), cur(ya))),
        ("Sermaye artırımı yok", None if b("paid_capital") is None or b("paid_capital", ya) is None
         else b("paid_capital") <= b("paid_capital", ya)),
        ("Brüt marj arttı", gt(gm(pk), gm(ya))),
        ("Aktif devir hızı arttı", gt(at(pk), at(ya))),
    ]
    known = [v for _, v in items if v is not None]
    return {"score": sum(1 for v in known if v) if len(known) >= 7 else None, "items": items}


def beneish(view: View, pk: str) -> float | None:
    """Beneish M (8 değişken). −1,78 üstü kazanç manipülasyonu riski."""
    ya = _year_ago(pk)
    if ya not in view.pos:
        return None
    k = view.conv(ya, pk)
    t = lambda key, p=pk: view.v("ttm", key, p)  # noqa: E731
    b = lambda key, p=pk: view.v("bs", key, p)   # noqa: E731
    try:
        rev1, rev0 = t("revenue"), t("revenue", ya) * k
        rec1, rec0 = b("receivables") or 0, (b("receivables", ya) or 0) * k
        dsri = (rec1 / rev1) / (rec0 / rev0) if rec0 else 1.0
        gm0 = t("gross", ya) / t("revenue", ya)
        gm1 = t("gross") / rev1
        gmi = gm0 / gm1 if gm1 else 1.0

        def aq(p, kk=1.0):
            ta = b("total_assets", p) * kk
            return 1 - ((b("current_assets", p) or 0) * kk + (b("ppe", p) or 0) * kk) / ta
        aqi = aq(pk) / aq(ya, k) if aq(ya, k) else 1.0
        sgi = rev1 / rev0
        d1, d0 = t("da") or 0, (t("da", ya) or 0) * k
        p1, p0 = b("ppe") or 0, (b("ppe", ya) or 0) * k
        depi = (d0 / (d0 + p0)) / (d1 / (d1 + p1)) if d1 and d0 and (d0 + p0) and (d1 + p1) else 1.0
        sga1 = -((t("gna") or 0) + (t("selling") or 0))
        sga0 = -((t("gna", ya) or 0) + (t("selling", ya) or 0)) * k
        sgai = (sga1 / rev1) / (sga0 / rev0) if sga0 and sga1 else 1.0

        def lv(p, kk=1.0):
            return ((b("current_liab", p) or 0) + (b("lt_borrowings", p) or 0)) * kk / (b("total_assets", p) * kk)
        lvgi = lv(pk) / lv(ya, k) if lv(ya, k) else 1.0
        tata = ((t("net") or 0) - (t("cfo") or 0)) / b("total_assets")
    except (TypeError, ZeroDivisionError):
        return None
    return (-4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
            - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)


# Kategori puanları: (oran, kötü, iyi) — kötüden iyiye doğrusal 0–100
CATEGORIES = {
    "Karlılık": [("roe", 0.0, 0.30), ("roa", 0.0, 0.12), ("net_margin", 0.0, 0.20),
                 ("ebitda_margin", 0.0, 0.30), ("gross_margin", 0.05, 0.45)],
    "Reel Büyüme": [("rev_growth", -0.10, 0.20), ("ebitda_growth", -0.20, 0.25), ("net_growth", -0.30, 0.30)],
    "Finansal Yapı": [("net_debt_ebitda", 4.0, 0.0), ("fin_debt_equity", 1.5, 0.2),
                      ("interest_cov", 1.0, 8.0), ("liab_assets", 0.8, 0.3)],
    "Likidite": [("current", 0.8, 2.0), ("quick", 0.5, 1.5), ("cash_ratio", 0.1, 0.8)],
    "Nakit Akışı & Kar Kalitesi": [("cfo_ni", 0.0, 1.2), ("fcf_margin", -0.05, 0.12), ("accruals", 0.10, -0.05)],
    "Verimlilik": [("asset_turnover", 0.2, 1.5), ("ccc", 180.0, 30.0), ("roic", 0.0, 0.25)],
}


def _lin(v, bad, good):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(_clip01((v - bad) / (good - bad)) * 100)


def category_scores(r: dict) -> dict:
    out = {}
    for cat, specs in CATEGORIES.items():
        vals = []
        for key, bad, good in specs:
            v = r.get(key)
            if key == "net_debt_ebitda" and v is not None and v < 0:
                v = 0.0                         # net nakit: en iyi
            s = _lin(v, bad, good)
            if s is not None:
                vals.append(s)
        out[cat] = round(sum(vals) / len(vals)) if vals else None
    return out


def grade(score: float | None) -> tuple[str, str] | tuple[None, None]:
    if score is None:
        return None, None
    for cut, g, label in ((80, "A", "Çok güçlü"), (65, "B", "Güçlü"), (50, "C", "Orta"), (35, "D", "Zayıf")):
        if score >= cut:
            return g, label
    return "E", "Çok zayıf"


# ---------- kriter setleri ----------

def _annual_pks(view: View) -> list[str]:
    return [p for p in view.p if p.endswith("/12")]


def criteria(view: View, pk: str, r: dict, val: dict, z, f, m) -> dict:
    t = lambda k: view.v("ttm", k, pk)  # noqa: E731
    b = lambda k: view.v("bs", k, pk)   # noqa: E731
    annual = _annual_pks(view)
    ann_net = [view.v("cum", "net_parent", p) for p in annual]
    ann_div = [view.v("cum", "dividends_paid", p) for p in annual]
    pe, pb = val.get("pe"), val.get("pb")
    nwc = (b("current_assets") - b("current_liab")) if b("current_assets") is not None and b("current_liab") is not None else None

    def chk(cond):
        try:
            return bool(cond())
        except TypeError:
            return None

    sets = {
        "Temel Sağlık Kontrolü": [
            ("Net kar pozitif (12A)", chk(lambda: t("net_parent") > 0)),
            ("İşletme nakit akışı pozitif", chk(lambda: t("cfo") > 0)),
            ("Özkaynak pozitif", chk(lambda: b("equity_parent") > 0)),
            ("Cari oran ≥ 1", chk(lambda: r["current"] >= 1)),
            ("Net borç/FAVÖK < 3", chk(lambda: (r["net_debt_ebitda"] if r["net_debt_ebitda"] is not None
                                                else (0 if b("net_debt") < 0 else None)) < 3)),
            ("FAVÖK/finansman gideri > 2", chk(lambda: r["interest_cov"] > 2)),
            ("Brüt marj pozitif", chk(lambda: r["gross_margin"] > 0)),
            ("Reel satış büyümesi pozitif", chk(lambda: r["rev_growth"] > 0)),
            ("Nakit akışı / net kar ≥ 0,8", chk(lambda: r["cfo_ni"] >= 0.8)),
            ("Altman Z'' güvenli bölge (> 2,6)", chk(lambda: z > 2.6)),
            ("Beneish M düşük risk (< −1,78)", chk(lambda: m < -1.78)),
            ("Son 4 çeyrekte zarar yok", chk(lambda: _no_quarter_loss(view, pk))),
        ],
        "Piotroski F-Skor": [(name, v) for name, v in (f or {}).get("items", [])],
        "Benjamin Graham — Savunmacı Yatırımcı": [
            ("Yeterli büyüklük: yıllık hasılat ≥ 20 milyar TL", chk(lambda: t("revenue") >= 20e9)),
            ("Güçlü finansal durum: cari oran ≥ 2", chk(lambda: r["current"] >= 2)),
            ("UV finansal borç ≤ net işletme sermayesi", chk(lambda: (b("lt_borrowings") or 0) <= nwc)),
            ("Kar istikrarı: tüm yıllık dönemlerde net kar pozitif",
             chk(lambda: bool(ann_net) and all(x is not None and x > 0 for x in ann_net))),
            ("Temettü sürekliliği: her yıl nakit temettü ödendi",
             chk(lambda: bool(ann_div) and all(x is not None and x < 0 for x in ann_div))),
            ("Kar büyümesi: reel net kar bir yıl öncesinden yüksek", chk(lambda: r["net_growth"] > 0)),
            ("Makul F/K ≤ 15", chk(lambda: pe <= 15)),
            ("PD/DD ≤ 1,5 veya F/K × PD/DD ≤ 22,5", chk(lambda: pb <= 1.5 or (pe * pb) <= 22.5)),
        ],
        "Warren Buffett — Kalıcı Rekabet Avantajı": [
            ("ROE ≥ %15", chk(lambda: r["roe"] >= 0.15)),
            ("Net kar marjı ≥ %10", chk(lambda: r["net_margin"] >= 0.10)),
            ("Brüt marj ≥ %40", chk(lambda: r["gross_margin"] >= 0.40)),
            ("Finansal borç/özkaynak < 0,5", chk(lambda: r["fin_debt_equity"] < 0.5)),
            ("FAVÖK/finansman gideri ≥ 5", chk(lambda: r["interest_cov"] >= 5)),
            ("Serbest nakit akışı pozitif", chk(lambda: t("fcf") > 0)),
            ("Yatırım harcaması < net karın %50'si", chk(lambda: abs(t("capex")) < 0.5 * t("net_parent"))),
            ("Reel FAVÖK büyümesi pozitif", chk(lambda: r["ebitda_growth"] > 0)),
        ],
        "Peter Lynch — Makul Fiyata Büyüme": [
            ("PEG ≤ 1", chk(lambda: val.get("peg") <= 1)),
            ("F/K ≤ 20", chk(lambda: pe <= 20)),
            ("Borç/özkaynak < 0,8", chk(lambda: r["fin_debt_equity"] < 0.8)),
            ("Reel net kar büyümesi ≥ %10", chk(lambda: r["net_growth"] >= 0.10)),
            ("Net nakit ya da stok artışı satıştan yavaş", chk(lambda: b("net_debt") < 0 or _inv_slower(view, pk))),
        ],
        "Joel Greenblatt — Sihirli Formül": [
            ("Kazanç getirisi (FVÖK/FD) ≥ %10", chk(lambda: val.get("earnings_yield") >= 0.10)),
            ("Sermaye getirisi (ROIC) ≥ %20", chk(lambda: r["roic"] >= 0.20)),
        ],
    }
    out = {}
    for name, items in sets.items():
        known = [v for _, v in items if v is not None]
        out[name] = {"items": [[label, v] for label, v in items], "pass": sum(1 for v in known if v),
                     "total": len(items), "known": len(known)}
    return out


def _no_quarter_loss(view: View, pk: str) -> bool:
    i = view.pos[pk]
    qs = [view.v("q", "net_parent", p) for p in view.p[max(0, i - 3): i + 1]]
    if len(qs) < 4 or any(q is None for q in qs):
        raise TypeError
    return all(q >= 0 for q in qs)


def _inv_slower(view: View, pk: str) -> bool:
    inv_now, inv_old = view.v("bs", "inventories", pk), view.ya("bs", "inventories", pk)
    rev_now, rev_old = view.v("ttm", "revenue", pk), view.ya("ttm", "revenue", pk)
    return (inv_now / inv_old) <= (rev_now / rev_old)


# ---------- şirket bazında toplam ----------

HISTORY_KEYS = ["roe", "roa", "net_margin", "ebitda_margin", "gross_margin", "current", "net_debt_ebitda",
                "debt_equity", "rev_growth", "net_growth", "asset_growth", "cfo_ni", "asset_turnover"]


def company(doc: dict, price: float | None) -> dict | None:
    ser = doc.get("series")
    if not ser or not ser.get("periods") or doc.get("template") != "sanayi":
        return None
    view = View(ser, doc.get("currency") or "TRY")
    pk = next((p for p in reversed(view.p) if view.v("ttm", "revenue", p) is not None), None)
    if pk is None:
        return None
    r = ratios(view, pk)
    val = valuation(view, pk, price)
    if val.get("pe") and r.get("net_growth") and r["net_growth"] > 0:
        val["peg"] = val["pe"] / (r["net_growth"] * 100)
    z, f, m = altman_z2(view, pk), piotroski(view, pk), beneish(view, pk)
    hist = {k: [] for k in HISTORY_KEYS}
    for p in view.p:
        rp = ratios(view, p) if view.v("ttm", "revenue", p) is not None else {}
        for k in HISTORY_KEYS:
            v = rp.get(k)
            hist[k].append(round(v, 4) if isinstance(v, float) else v)
    return {
        "period": pk, "ratios": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()},
        "valuation": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in val.items()},
        "altman_z2": round(z, 2) if z is not None else None,
        "piotroski": f["score"], "piotroski_items": [[n, v] for n, v in f["items"]],
        "beneish_m": round(m, 2) if m is not None else None,
        "categories": category_scores(r),
        "criteria": criteria(view, pk, r, val, z, f, m),
        "history": {"periods": view.p, **hist},
    }


# ---------- evren aşaması: sektör medyanları, değerleme puanı, genel skor ----------

VAL_KEYS = ("pe", "pb", "ev_ebitda", "ev_sales")


def sector_medians(rows: list[dict], min_peers: int = 3) -> dict:
    by_sector: dict[str, dict[str, list]] = {}
    for row in rows:
        sec = row.get("sector") or "Diğer"
        for k in VAL_KEYS + ("roe", "net_margin", "ebitda_margin", "current", "net_debt_ebitda"):
            v = (row["m"]["valuation"].get(k) if k in VAL_KEYS else row["m"]["ratios"].get(k))
            if v is not None and v > 0 or (v is not None and k not in VAL_KEYS):
                by_sector.setdefault(sec, {}).setdefault(k, []).append(v)
                by_sector.setdefault("_tümü", {}).setdefault(k, []).append(v)
    out = {}
    for sec, d in by_sector.items():
        out[sec] = {k: (median(vs) if len(vs) >= min_peers else None) for k, vs in d.items()}
    return out


def finalize(rows: list[dict]) -> None:
    """rows: [{'code','sector','m': company(...)}]; m'ye değerleme puanı, içsel değer, genel skor ekler."""
    med = sector_medians(rows)
    allm = med.get("_tümü", {})
    for row in rows:
        m = row["m"]
        sec = med.get(row.get("sector") or "Diğer", {})
        ref = {k: (sec.get(k) or allm.get(k)) for k in VAL_KEYS}
        m["sector_median"] = {k: (round(v, 3) if v else None) for k, v in ref.items()}
        val = m["valuation"]
        parts = []
        for k in VAL_KEYS:
            v, md = val.get(k), ref.get(k)
            if v and md and v > 0:
                parts.append(_clip01((2 - v / md) / 1.5) * 100)
        # İçsel değer: sektör medyan çarpanlarıyla F/K, PD/DD ve FD/FAVÖK değerlerinin ortalaması
        ivs = []
        shares = val.get("shares")
        if shares and val.get("price"):
            if ref.get("pe") and (val.get("eps") or 0) > 0:
                ivs.append(ref["pe"] * val["eps"])
            if ref.get("pb") and (val.get("bvps") or 0) > 0:
                ivs.append(ref["pb"] * val["bvps"])
            ebitda = val["ev"] / val["ev_ebitda"] if val.get("ev_ebitda") else None
            if ref.get("ev_ebitda") and ebitda:
                eq = ref["ev_ebitda"] * ebitda - (val["ev"] - val["mcap"])
                if eq > 0:
                    ivs.append(eq / shares)
        if ivs:
            iv = sum(ivs) / len(ivs)
            m["intrinsic"] = round(iv, 2)
            m["potential"] = round(iv / val["price"] - 1, 4)
            parts.append(_lin(m["potential"], -0.4, 0.6))
        vs = round(sum(parts) / len(parts)) if parts else None
        cats = [v for v in m["categories"].values() if v is not None]
        q = round(sum(cats) / len(cats)) if cats else None
        m["quality"] = q
        m["valuation_score"] = vs
        overall = round(0.6 * q + 0.4 * vs) if q is not None and vs is not None else q
        m["overall"] = overall
        m["grade"], m["grade_label"] = grade(overall)
        m["quality_grade"], _ = grade(q)
        m["valuation_grade"], _ = grade(vs)
