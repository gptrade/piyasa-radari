"""Yöntem Karnesi — hangi tarama yöntemi BIST'te gerçekten işe yarıyor?

Aylık, nokta-zamanlı (point-in-time) faktör testi:
  * Her ay sonunda (t) her şirket için o ana kadar **KAP'ta yayımlanmış** son mali tablo kullanılır
    (yayın anı bilinmiyorsa SPK'nın yasal son günü: 1. ve 3. çeyrek +41, 2. çeyrek +61, yıl sonu +71 gün).
  * Fiyat: t ay sonundaki gerçek kapanış; pay sayısı = dönemin ödenmiş sermayesi × dönem sonundan t'ye kadarki
    bölünme/bedelsiz katsayısı (bedelsiz sonrası hisse yanlışlıkla "ucuz" görünmesin).
  * Mali tablo tutarları t ayının TL'sine TÜFE ile taşınır (dönem sonu ile t arasındaki enflasyon).
  * Getiri: t → t+1 temettü ve bölünme düzeltilmiş (Yahoo Adj Close). Karşılaştırma ölçütü aynı ay uygun
    hisselerin eşit ağırlıklı ortalaması; yani her sonuç "piyasaya göre fazla getiri".
  * Likidite süzgeci: son 3 ayın medyan işlem hacmi, o ayın evreninin alt %20'sinde olanlar ve aylarca aynı
    fiyatta kalanlar (işlem görmeyen) dışarıda.
  * Beşli dilimler (eşit ağırlık), en iyi − en kötü dilim farkı, sıralama korelasyonu (rank IC), Newey-West t (3 gecikme),
    en iyi dilimin %0,2/işlem maliyeti sonrası fazla getirisi ve devir hızı; alt dönemler ve reel TL / USD getiri.

Sınırlar: borsadan çıkmış şirketler Yahoo'da yok (hayatta kalma yanlılığı, sonuçları biraz iyimser yapar);
2016 öncesi KAP tabloları okunamıyor; ~100 aylık örneklem. Çok sayıda yöntem test edildiği için "güçlü kanıt"
eşiği t ≥ 3 (Harvey, Liu ve Zhu 2016).

`python -m radar.yontem` (yontem.yml, haftalık) → site/data/yontem/yontem.json. Ham fiyatlar yayımlanmaz.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("radar.yontem")

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "site" / "data" / "fin"
OUT = ROOT / "site" / "data" / "yontem" / "yontem.json"
START = "2017-01"
COST = 0.002          # tek yön işlem maliyeti
MIN_N = 30            # bir ayda dilim kurmak için en az hisse
MIN_MONTHS = 24       # karar için en az ay
LIQ_Q = 0.2           # likidite süzgeci: alt %20
STALE_MONTHS = 9      # dönem sonundan bu kadar ay geçtiyse tablo bayat sayılır
LAG = {3: 41, 6: 61, 9: 41, 12: 71}
SUBS = (("2017–2019", "2017-01", "2019-12"), ("2020–2022", "2020-01", "2022-12"), ("2023–", "2023-01", "2099-12"))

# anahtar, ad, grup, açıklama, kapsam ("sanayi" = mali kuruluşlar hariç, "all" = tümü)
FACTORS = [
    ("ep", "Kâr verimi (1 / F/K)", "Değer", "Son 12 ay ana ortaklık net kârı / piyasa değeri. Yüksek = ucuz.", "sanayi"),
    ("ep_xmon", "Parasal kazanç hariç kâr verimi", "Değer", "Vergi öncesi kâr − net parasal pozisyon kazancı (×0,75) / piyasa değeri. Enflasyon muhasebesinin nakit yaratmayan kârı ayıklanır.", "sanayi"),
    ("bp", "Defter / piyasa (1 / PD/DD)", "Değer", "Ana ortaklık özkaynağı / piyasa değeri. Yüksek = ucuz.", "sanayi"),
    ("ebitda_ev", "FAVÖK / FD (1 / FD/FAVÖK)", "Değer", "Son 12 ay FAVÖK / firma değeri (piyasa değeri + net borç + azınlık).", "sanayi"),
    ("sp", "Satış / piyasa değeri", "Değer", "Son 12 ay hasılat / piyasa değeri.", "sanayi"),
    ("dy", "Temettü verimi", "Değer", "Son 12 ayda ödenen temettü / piyasa değeri.", "sanayi"),
    ("pb_resid", "Hak edilen PD/DD'ye göre iskonto", "Değer", "Her ay PD/DD (log) özkaynak kârlılığına göre regresyonla açıklanır; beklenenden düşük PD/DD = ucuz.", "sanayi"),
    ("roe", "Özkaynak kârlılığı (ROE)", "Kalite", "Son 12 ay net kâr / ortalama özkaynak.", "sanayi"),
    ("roic", "Yatırılan sermaye getirisi (ROIC)", "Kalite", "Faaliyet kârı × 0,75 / yatırılan sermaye.", "sanayi"),
    ("gp", "Brüt kârlılık (Novy-Marx)", "Kalite", "Son 12 ay brüt kâr / toplam varlık.", "sanayi"),
    ("fscore", "Piotroski F-skoru", "Kalite", "9 maddelik finansal güç puanı.", "sanayi"),
    ("zscore", "Altman Z″ (iflas riski düşüklüğü)", "Kalite", "Yüksek = finansal sıkıntı riski düşük.", "sanayi"),
    ("mscore", "Beneish M (düşük manipülasyon riski)", "Kalite", "M-skoru düşük olan (işaret ters çevrilmiş) yüksek sırada.", "sanayi"),
    ("accruals", "Düşük tahakkuk", "Kalite", "(Net kâr − işletme nakit akışı) / ortalama varlık; düşük = kârın nakit karşılığı güçlü.", "sanayi"),
    ("inv", "Düşük varlık büyümesi", "Kalite", "Toplam varlığın reel yıllık büyümesi; düşük büyüme yüksek sırada (yatırım faktörü).", "sanayi"),
    ("su", "Bilanço sürprizi (PEAD)", "Olay", "Son çeyrek reel net kârının bir yıl öncesine göre sürprizi; yalnız son 3 ayda açıklananlar.", "sanayi"),
    ("mom", "Momentum (12-1 ay)", "Fiyat", "Son 12 ayın getirisi, son ay hariç.", "all"),
    ("rev1", "Kısa vadeli dönüş (1 ay)", "Fiyat", "Geçen ayın getirisinin tersi: geçen ay düşen yüksek sırada.", "all"),
    ("lowvol", "Düşük oynaklık", "Fiyat", "Son 12 ayın günlük getiri oynaklığı; düşük oynaklık yüksek sırada.", "all"),
    ("size", "Küçük şirket", "Fiyat", "Piyasa değeri (log) küçük olan yüksek sırada.", "all"),
    ("vq", "Değer + kalite (tuzak süzgeci)", "Birleşik", "Kâr verimi, defter/piyasa ve FAVÖK/FD sıralarının ortalaması + F-skoru ve Altman Z″ sırası: ucuz ama zayıf şirketler aşağı iner.", "sanayi"),
    ("vm", "Değer + momentum", "Birleşik", "Değer sıraları ortalaması ile momentum sırasının ortalaması.", "sanayi"),
]
KEYS = [f[0] for f in FACTORS]


# ───────────────────────────── yardımcılar

def _mkey(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _madd(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:]) - 1 + k
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


def _mend(m: str) -> date:
    y, mo = int(m[:4]), int(m[5:])
    return (date(y + mo // 12, mo % 12 + 1, 1) - timedelta(days=1))


def months(start: str, end: str) -> list[str]:
    out, m = [], start
    while m <= end:
        out.append(m)
        m = _madd(m, 1)
    return out


def pk_end(pk: str) -> date:
    return _mend(f"{pk[:4]}-{pk[5:]}")


def deadline(pk: str) -> date:
    return pk_end(pk) + timedelta(days=LAG[int(pk[5:])])


def known_at(rep: dict, pk: str, pub: dict) -> date:
    """Raporun piyasaca bilindiği gün: KAP yayın anı, yoksa yasal son gün."""
    s = rep.get("published") or pub.get(str(rep.get("idx")))
    if s:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            pass
    return deadline(pk)


def _div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def rank01(vals: dict) -> dict:
    """{kod: değer} → {kod: 0..1 yüzdelik sıra} (eşitlerde ortalama sıra)."""
    xs = sorted((v, k) for k, v in vals.items() if v is not None and math.isfinite(v))
    n = len(xs)
    out: dict = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        r = ((i + j) / 2) / (n - 1) if n > 1 else 0.5
        for t in range(i, j + 1):
            out[xs[t][1]] = r
        i = j + 1
    return out


def spearman(a: dict, b: dict) -> float | None:
    ks = [k for k in a if k in b]
    if len(ks) < MIN_N:
        return None
    ra, rb = rank01({k: a[k] for k in ks}), rank01({k: b[k] for k in ks})
    ma, mb = sum(ra.values()) / len(ks), sum(rb.values()) / len(ks)
    cov = sum((ra[k] - ma) * (rb[k] - mb) for k in ks)
    va = sum((ra[k] - ma) ** 2 for k in ks)
    vb = sum((rb[k] - mb) ** 2 for k in ks)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def nw_t(xs: list[float], lags: int = 3) -> tuple[float | None, float | None]:
    """Ortalama ve Newey-West t istatistiği."""
    n = len(xs)
    if n < 6:
        return (sum(xs) / n if n else None), None
    m = sum(xs) / n
    e = [x - m for x in xs]
    g0 = sum(v * v for v in e) / n
    s = g0
    for L in range(1, min(lags, n - 1) + 1):
        g = sum(e[i] * e[i - L] for i in range(L, n)) / n
        s += 2 * (1 - L / (lags + 1)) * g
    se = math.sqrt(s / n) if s > 0 else None
    return m, (m / se if se else None)


# ───────────────────────────── fiyatlar

def prepare_prices(daily: dict) -> dict:
    """daily: {kod: {'d': [iso], 'c': [kapanış], 'a': [düzeltilmiş], 'v': [adet], 's': [(iso, oran)]}} →
    {kod: {'raw': {ay: gerçek fiyat}, 'adj': {ay: düzeltilmiş}, 'tv': {ay: TL hacim}, 'vol': {ay: yıllık oynaklık},
           'splits': [(date, oran)]}}"""
    out = {}
    for code, x in daily.items():
        d, c, a, v = x["d"], x["c"], x["a"], x["v"]
        splits = sorted((date.fromisoformat(s[:10]), r) for s, r in x.get("s", []) if r and r > 0)
        raw, adj, tv, vol = {}, {}, {}, {}
        rets: list[tuple[date, float]] = []
        prev = None
        for i, iso in enumerate(d):
            if c[i] is None or a[i] is None or c[i] <= 0 or a[i] <= 0:
                continue
            dd = date.fromisoformat(iso[:10])
            m = _mkey(dd)
            # Yahoo kapanışı sonraki bölünmelere göre geriye düzeltilmiş; gerçek fiyat = kapanış × sonraki bölünme katsayıları
            f = 1.0
            for sd, r in splits:
                if sd > dd:
                    f *= r
            raw[m] = c[i] * f
            adj[m] = a[i]
            tv[m] = tv.get(m, 0.0) + c[i] * (v[i] or 0)      # kapanış × adet: bölünme düzeltmesinden bağımsız
            if prev is not None:
                rets.append((dd, math.log(a[i] / prev)))
            prev = a[i]
        # ay sonu oynaklığı: son ~252 işlem günü
        if rets:
            j0 = 0
            by_m: dict[str, int] = {}
            for i, (dd, _) in enumerate(rets):
                by_m[_mkey(dd)] = i
            for m, iend in by_m.items():
                lo = max(0, iend - 251)
                w = [r for _, r in rets[lo:iend + 1]]
                if len(w) >= 120:
                    mu = sum(w) / len(w)
                    vol[m] = math.sqrt(sum((r - mu) ** 2 for r in w) / (len(w) - 1) * 252)
            del j0
        out[code] = {"raw": raw, "adj": adj, "tv": tv, "vol": vol, "splits": splits}
    return out


def split_factor(splits: list, after: date, upto: date) -> float:
    f = 1.0
    for sd, r in splits:
        if after < sd <= upto:
            f *= r
    return f


# ───────────────────────────── sinyaller

def _view(doc):
    from .fundamentals.metrics import View
    return View(doc["series"], doc.get("currency") or "TRY")


def company_signals(doc: dict, px: dict, cpi: dict, pub: dict, mlist: list[str]) -> dict[str, dict]:
    """Bir şirketin her ay sonundaki sinyalleri {ay: {anahtar: değer}} (yalnız temel sinyaller + mcap)."""
    from .fundamentals import metrics as M
    from .earnings import sue_series
    ser = doc.get("series") or {}
    P = ser.get("periods") or []
    if not P:
        return {}
    view = _view(doc)
    reps = doc.get("reports") or {}
    tmpl = doc.get("template")
    try_cur = (doc.get("currency") or "TRY") == "TRY"
    known = {pk: known_at(reps.get(pk) or {}, pk, pub) for pk in P}
    q = ser.get("q") or {}
    ni_q = q.get("net_parent") or q.get("net")
    sus = sue_series(ni_q, ser.get("cpi") or []) if ni_q and len(ser.get("cpi") or []) == len(P) else [None] * len(P)
    nominal = ser.get("nominal") or [False] * len(P)
    cache: dict[str, dict] = {}
    out: dict[str, dict] = {}
    for m in mlist:
        price = px["raw"].get(m)
        if not price:
            continue
        end = _mend(m)
        cands = [pk for pk in P if known[pk] <= end and (end - pk_end(pk)).days <= STALE_MONTHS * 31]
        if not cands:
            continue
        pk = cands[-1]
        if pk not in cache:
            cache[pk] = _pk_static(view, pk, tmpl, M)
        st = cache[pk]
        shares = st.get("shares")
        if not shares:
            continue
        shares *= split_factor(px["splits"], pk_end(pk), end)
        mcap = price * shares
        if mcap <= 0:
            continue
        ce = cpi.get(m) or cpi.get(_madd(m, -1))
        cp = cpi.get(f"{pk[:4]}-{pk[5:]}")
        conv = (ce / cp) if try_cur and ce and cp else 1.0
        s: dict = {"mcap": mcap, "pk": pk, "fin": tmpl != "sanayi"}
        if tmpl == "sanayi":
            g = lambda k: (st[k] * conv) if st.get(k) is not None else None  # noqa: E731
            ni, eq, ebitda, rev = g("ni"), g("eq"), g("ebitda"), g("rev")
            ev = mcap + (g("net_debt") or 0) + (g("minority") or 0)
            s["ep"] = _div(ni, mcap)
            mon = st.get("mon")
            if mon is None and nominal[P.index(pk)]:
                mon = 0.0
            s["ep_xmon"] = _div((st["pbt"] - mon) * 0.75 * conv, mcap) if st.get("pbt") is not None and mon is not None else None
            s["bp"] = _div(eq, mcap)
            s["ebitda_ev"] = _div(ebitda, ev) if ev > 0 and ebitda is not None else None
            s["sp"] = _div(rev, mcap)
            s["dy"] = _div(abs(g("divs") or 0), mcap)
            for k in ("roe", "roic", "gp", "fscore", "zscore", "mscore", "accruals", "inv"):
                s[k] = st.get(k)
            i = P.index(pk)
            if sus[i] is not None and (end - known[pk]).days <= 92:
                s["su"] = sus[i]["su"]
        else:
            s["bp"] = _div((st.get("eq") or 0) * conv, mcap) if st.get("eq") else None
        out[m] = s
    return out


def _pk_static(view, pk: str, tmpl: str, M) -> dict:
    b = lambda k: view.v("bs", k, pk)   # noqa: E731
    t = lambda k: view.v("ttm", k, pk)  # noqa: E731
    st = {"shares": b("paid_capital"), "eq": b("equity_parent")}
    if tmpl != "sanayi" or t("revenue") is None:
        return st
    r = M.ratios(view, pk)
    st.update({"ni": t("net_parent"), "ebitda": t("ebitda"), "rev": t("revenue"), "pbt": t("pretax"), "mon": t("monetary"),
               "divs": t("dividends_paid"), "net_debt": b("net_debt"), "minority": b("minority"),
               "roe": r.get("roe"), "roic": r.get("roic"),
               "gp": _div(t("gross"), view.avg_bs("total_assets", pk)),
               "accruals": -r["accruals"] if r.get("accruals") is not None else None,
               "inv": -r["asset_growth"] if r.get("asset_growth") is not None else None})
    try:
        st["fscore"] = M.piotroski(view, pk)["score"]
    except Exception:
        st["fscore"] = None
    try:
        st["zscore"] = M.altman_z2(view, pk)
    except Exception:
        st["zscore"] = None
    try:
        mm = M.beneish(view, pk)
        st["mscore"] = -mm if mm is not None else None
    except Exception:
        st["mscore"] = None
    return st


def price_signals(px: dict, m: str) -> dict:
    adj = px["adj"]
    s = {}
    a1, a12, a0 = adj.get(_madd(m, -1)), adj.get(_madd(m, -12)), adj.get(m)
    if a1 and a12:
        s["mom"] = a1 / a12 - 1
    if a0 and a1:
        s["rev1"] = -(a0 / a1 - 1)
    if px["vol"].get(m):
        s["lowvol"] = -px["vol"][m]
    return s


def eligible(px: dict, m: str) -> bool:
    raw = px["raw"]
    if not raw.get(m) or not px["adj"].get(m):
        return False
    last3 = [raw.get(_madd(m, -k)) for k in range(3)]
    return not (None not in last3 and last3[0] == last3[1] == last3[2])     # aylarca aynı fiyat: işlem görmüyor


def fwd_return(px: dict, m: str) -> float | None:
    a0, a1 = px["adj"].get(m), px["adj"].get(_madd(m, 1))
    if not a0 or not a1:
        return None
    r = a1 / a0 - 1
    return None if r > 3 or r < -0.9 else r          # bariz veri hataları (Yahoo bedelsiz kayması)


def pb_residual(sig: dict) -> dict:
    """log(PD/DD) = a + b·ROE (kesitsel EKK); −kalıntı = hak edilene göre ucuzluk."""
    pts = [(k, math.log(1 / s["bp"]), max(-0.5, min(1.0, s["roe"]))) for k, s in sig.items()
           if s.get("bp") and s["bp"] > 0 and s.get("roe") is not None]
    if len(pts) < MIN_N:
        return {}
    mx = sum(p[2] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[2] - mx) ** 2 for p in pts)
    if sxx <= 0:
        return {}
    beta = sum((p[2] - mx) * (p[1] - my) for p in pts) / sxx
    return {k: -(y - (my + beta * (x - mx))) for k, y, x in pts}


def combos(sig: dict) -> None:
    ranks = {k: rank01({c: s.get(k) for c, s in sig.items()}) for k in ("ep", "bp", "ebitda_ev", "fscore", "zscore", "mom")}
    for c, s in sig.items():
        vals = [ranks[k][c] for k in ("ep", "bp", "ebitda_ev") if c in ranks[k]]
        if len(vals) < 2:
            continue
        v = sum(vals) / len(vals)
        q = [ranks[k][c] for k in ("fscore", "zscore") if c in ranks[k]]
        if q:
            s["vq"] = (v + sum(q) / len(q)) / 2
        if c in ranks["mom"]:
            s["vm"] = (v + ranks["mom"][c]) / 2


# ───────────────────────────── değerlendirme

def build_panel(docs: dict, prices: dict, cpi: dict, pub: dict, mlist: list[str]) -> dict[str, dict]:
    """{ay: {kod: {sinyaller..., 'r': ileri getiri}}} — likidite süzgecinden geçmiş."""
    fund = {c: company_signals(d, prices[c], cpi, pub, mlist) for c, d in docs.items() if c in prices}
    panel = {}
    for m in mlist:
        rows = {}
        for c, px in prices.items():
            if not eligible(px, m):
                continue
            r = fwd_return(px, m)
            if r is None:
                continue
            tv3 = sorted(px["tv"].get(_madd(m, -k), 0.0) for k in range(3))[1]
            s = {**(fund.get(c, {}).get(m) or {}), **price_signals(px, m), "r": r, "tv": tv3}
            if s.get("mcap"):
                s["size"] = -math.log(s["mcap"])
            rows[c] = s
        if len(rows) < MIN_N:
            continue
        cut = sorted(s["tv"] for s in rows.values())[int(len(rows) * LIQ_Q)]
        rows = {c: s for c, s in rows.items() if s["tv"] >= cut and s["tv"] > 0}
        for c, v in pb_residual({c: s for c, s in rows.items() if not s.get("fin")}).items():
            rows[c]["pb_resid"] = v
        combos({c: s for c, s in rows.items() if not s.get("fin")})
        panel[m] = rows
    return panel


def evaluate(panel: dict, key: str, scope: str, cpi: dict, usd: dict) -> dict:
    ms = sorted(panel)
    ls, ic, q5x, q1x, top_net, months_used = [], [], [], [], [], []
    q_means = [[] for _ in range(5)]
    raw_top, raw_bench, prev_top = [], [], None
    turn = []
    ns = []
    for m in ms:
        rows = panel[m]
        uni = {c: s for c, s in rows.items() if scope == "all" or not s.get("fin")}
        bench = sum(s["r"] for s in uni.values()) / len(uni) if uni else None
        sig = {c: s[key] for c, s in uni.items() if s.get(key) is not None and math.isfinite(s[key])}
        if len(sig) < MIN_N or bench is None:
            continue
        order = sorted(sig, key=lambda c: (sig[c], c))      # sıralı dilim (eşitler, ör. temettüsüzler, dilimleri boşaltmasın)
        buckets = [order[len(order) * i // 5: len(order) * (i + 1) // 5] for i in range(5)]
        if any(not b for b in buckets):
            continue
        qr = [sum(uni[c]["r"] for c in b) / len(b) for b in buckets]
        for i in range(5):
            q_means[i].append(qr[i] - bench)
        top = set(buckets[4])
        to = 1.0 if prev_top is None else len(top - prev_top) / len(top)
        prev_top = top
        turn.append(to)
        ls.append(qr[4] - qr[0])
        q5x.append(qr[4] - bench)
        q1x.append(qr[0] - bench)
        top_net.append(qr[4] - bench - 2 * COST * to)
        raw_top.append(qr[4] - 2 * COST * to)
        raw_bench.append(bench)
        v = spearman(sig, {c: uni[c]["r"] for c in sig})
        if v is not None:
            ic.append(v)
        months_used.append(m)
        ns.append(len(sig))
    n = len(months_used)
    res: dict = {"n": n, "stocks": round(sum(ns) / n) if n else 0,
                 "from": months_used[0] if n else None, "to": months_used[-1] if n else None}
    if n < 6:
        res["verdict"] = "yetersiz"
        return res
    m_ls, t_ls = nw_t(ls)
    m_ic, t_ic = nw_t(ic) if len(ic) >= 6 else (None, None)
    m_top, t_top = nw_t(top_net)
    res.update({
        "ls": _r(m_ls), "ls_t": _r(t_ls, 2), "ls_ann": _r((1 + m_ls) ** 12 - 1) if m_ls > -1 else None,
        "ic": _r(m_ic), "ic_t": _r(t_ic, 2),
        "top": _r(m_top), "top_t": _r(t_top, 2), "top_ann": _r((1 + m_top) ** 12 - 1) if m_top > -1 else None,
        "turn": _r(sum(turn[1:]) / max(1, len(turn) - 1), 3),
        "hit": _r(sum(1 for x in ls if x > 0) / n, 3),
        "quint": [_r(sum(x) / len(x)) for x in q_means],
    })
    subs = []
    for name, a, b in SUBS:
        xs = [x for x, m in zip(ls, months_used) if a <= m <= b]
        if len(xs) >= 6:
            mm, tt = nw_t(xs)
            subs.append({"name": name, "n": len(xs), "ls": _r(mm), "t": _r(tt, 2)})
    res["subs"] = subs
    # birikimli seriler (grafik): en iyi dilim net fazla, en kötü dilim fazla, fark
    cum = {"m": months_used, "top": [], "bot": [], "ls": []}
    a = b = c = 1.0
    for x, y, z in zip(top_net, q1x, ls):
        a *= 1 + x
        b *= 1 + y
        c *= 1 + z
        cum["top"].append(round(a, 4))
        cum["bot"].append(round(b, 4))
        cum["ls"].append(round(c, 4))
    res["cum"] = cum
    # yıllık reel TL ve USD: en iyi dilim (maliyet sonrası) ve eşit ağırlıklı evren
    res["real"] = _ann_real(months_used, raw_top, raw_bench, cpi)
    res["usd"] = _ann_real(months_used, raw_top, raw_bench, usd)
    res["verdict"] = verdict(res)
    return res


def _ann_real(ms, top, bench, deflator: dict) -> dict | None:
    gt = gb = 1.0
    k = 0
    for m, x, y in zip(ms, top, bench):
        d0, d1 = deflator.get(m), deflator.get(_madd(m, 1))
        if not d0 or not d1:
            continue
        f = d1 / d0
        gt *= (1 + x) / f
        gb *= (1 + y) / f
        k += 1
    if k < 12:
        return None
    return {"top": _r(gt ** (12 / k) - 1), "bench": _r(gb ** (12 / k) - 1), "n": k}


def verdict(res: dict) -> str:
    n, t, ls = res["n"], res.get("ls_t"), res.get("ls")
    if n < MIN_MONTHS or t is None:
        return "yetersiz"
    subs = [s for s in res.get("subs", []) if s.get("ls") is not None]
    same = sum(1 for s in subs if (s["ls"] > 0) == (ls > 0))
    steady = not subs or same >= max(1, len(subs) - 1)
    if t >= 3 and steady:
        # tek bir alt dönemden (ör. yalnız 2023 sonrası) gelen kanıt: rejim değişimine karşı sınanmamış
        return "guclu" if len(subs) >= 2 and n >= 60 else "kisa_guclu"
    if t >= 2:
        return "umut"
    if t <= -3 and steady:
        return "ters"
    if t <= -2:
        return "zayif_ters"
    return "yok"


def _r(v, k: int = 4):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(v, k)


# ───────────────────────────── giriş / çıkış

def load_docs(fin: Path) -> tuple[dict, dict, dict, dict]:
    docs = {}
    for p in sorted(fin.glob("[A-Z0-9]*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if d.get("series", {}).get("periods"):
            docs[d.get("code") or p.stem] = d
    rd = lambda n, dflt: json.loads((fin / n).read_text(encoding="utf-8")) if (fin / n).exists() else dflt  # noqa: E731
    cpi = rd("_cpi.json", {}).get("m", {})
    pub = rd("_state.json", {}).get("pub", {})
    uni = rd("_universe.json", {}).get("members", [])
    return docs, cpi, pub, {m["code"]: m for m in uni}


def download(codes: list[str], start: str = "2015-12-01") -> tuple[dict, dict]:
    import yfinance as yf
    daily: dict = {}
    for i in range(0, len(codes), 40):
        part = codes[i:i + 40]
        df = None
        for _ in range(3):
            try:
                df = yf.download(" ".join(f"{c}.IS" for c in part), start=start, interval="1d", actions=True,
                                 group_by="ticker", auto_adjust=False, threads=True, progress=False)
                break
            except Exception as e:  # ağ / hız sınırı
                log.warning("Yahoo indirme hatası: %s", e)
        if df is None:
            continue
        for c in part:
            try:
                sub = (df[f"{c}.IS"] if len(part) > 1 else df).dropna(subset=["Close"])
            except (KeyError, TypeError):
                continue
            if sub.empty:
                continue
            sp = sub["Stock Splits"] if "Stock Splits" in sub else None
            daily[c] = {"d": [str(x.date()) for x in sub.index], "c": [float(v) for v in sub["Close"]],
                        "a": [float(v) for v in sub["Adj Close"]], "v": [float(v) if v == v else 0.0 for v in sub["Volume"]],
                        "s": [(str(x.date()), float(v)) for x, v in sp.items() if v and v > 0] if sp is not None else []}
    usd = {}
    try:
        fx = yf.download("TRY=X", start=start, interval="1d", auto_adjust=False, progress=False)
        ser = fx["Close"].squeeze().dropna()
        for per, v in ser.groupby(ser.index.to_period("M")).last().items():
            usd[str(per)] = float(v)
    except Exception as e:
        log.warning("USD/TRY alınamadı: %s", e)
    return daily, usd


def run(fin: Path = FIN, out: Path = OUT, daily: dict | None = None, usd: dict | None = None) -> dict:
    docs, cpi, pub, uni = load_docs(fin)
    codes = sorted(set(uni) | set(docs))
    if daily is None:
        daily, usd = download(codes)
    prices = prepare_prices(daily)
    end = _madd(_mkey(date.today()), -1)            # son tamamlanmış ay sonu sinyali, bir sonraki ay getirisi gerekir
    mlist = months(START, _madd(end, -1))
    panel = build_panel(docs, prices, cpi, pub, mlist)
    facs = []
    for key, name, grp, desc, scope in FACTORS:
        r = evaluate(panel, key, scope, cpi, usd or {})
        facs.append({"key": key, "name": name, "group": grp, "desc": desc,
                     "scope": "Mali kuruluşlar hariç" if scope == "sanayi" else "Tüm hisseler", **r})
    reps = [r for d in docs.values() for r in (d.get("reports") or {}).values()]
    have_pub = sum(1 for r in reps if r.get("published") or pub.get(str(r.get("idx"))))
    pks = [pk for d in docs.values() for pk in d["series"]["periods"]]
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": [min(panel), max(panel)] if panel else None, "n_months": len(panel),
        "stocks_avg": round(sum(len(v) for v in panel.values()) / len(panel)) if panel else 0,
        "companies": len(docs), "priced": len(prices),
        "first_period": min(pks) if pks else None,
        "pub_share": round(have_pub / len(reps), 3) if reps else 0,
        "cost": COST, "liq_q": LIQ_Q, "min_n": MIN_N, "min_months": MIN_MONTHS,
        "factors": facs,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Yöntem karnesi: %d ay, %d şirket, %d yöntem", doc["n_months"], doc["companies"], len(facs))
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
    sys.exit(0)
