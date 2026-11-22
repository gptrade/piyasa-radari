"""VİOP panosu: BIST 30 vadeli ve dolar/TL vadeli, Borsa İstanbul'un ücretsiz gün sonu bülteninden.

Kaynak: https://www.borsaistanbul.com/data/vadeli/viop_YYYYAAGG.csv (Vadeli İşlem ve Opsiyon Piyasası Günlük Bülteni;
her kontrat için uzlaşma, ağırlıklı ortalama fiyat, hacim, açık pozisyon ve açık pozisyon değişimi). Kurum bazında
pozisyon (VAKD) ücretli lisanslı veridir ve burada YOKTUR; bu panodaki her şey piyasa geneli içindir.

Üretilen göstergeler (guc/viop.json, yayımlanır):
- XU030 yakın vade: uzlaşma, açık pozisyon (tüm vadeler toplamı ve yakın vade), günlük değişim.
- Açık pozisyonun tahmini ortalama maliyeti (piyasa geneli): açık pozisyon artınca yeni pozisyonlar o günün ağırlıklı
  ortalama fiyatından eklenir, azalınca kalanların maliyeti değişmez (orantılı kapanış varsayımı). Yaklaşıktır.
- Fiyat × açık pozisyon okuması: ↑↑ yeni long · ↓↑ yeni short · ↑↓ short kapama · ↓↓ long kapama.
- Baz: vadeli − spot XU030 (Yahoo kapanışı) ve yıllıklandırılmış taşıma oranı.
- Vade geçişi: vade sonuna 20 iş günü kala sonraki vadenin açık pozisyondaki payı, önceki vadenin aynı noktasıyla.
- Dolar/TL vadelilerinden ima edilen TL faizi: ((F/S)·(1 + r_usd·d/360) − 1)·365/d; r_usd = ABD 3 aylık bono (^IRX).
  Spot kur Yahoo kapanışı olduğu için 1 aydan kısa vadelerde gürültülüdür; eğri ≥ 20 gün vadeler için verilir.

Ham bülten yeniden yayımlanmaz: viop_hist.json yalnız XU030 ve USDTRY vadelilerinin seçili alanlarını tutar ve
`guc` dalında kalır (radar.yml yalnız viop.json'u siteye kopyalar).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from .config import DATA

log = logging.getLogger("radar.viop")

BASE = "https://www.borsaistanbul.com/data/vadeli/viop_{d}.csv"
OUT = DATA / "guc"
HIST = OUT / "viop_hist.json"
DOC = OUT / "viop.json"
KEEP_DAYS = 400               # takvim günü
MAX_FETCH = 300               # tur başına indirme (ilk turda ~1 yıl; sonra yalnız yeni günler)
XU = re.compile(r"^F_XU030(\d{4})$")
FX = re.compile(r"^F_USDTRY(\d{4})$")
FIELDS = ["code", "exp", "settle", "prev", "close", "vwap", "value", "qty", "oi", "oichg"]
ROLL_N = 20                   # iş günü: vade geçişi penceresi
STATES = {"lb": "Yeni long", "sb": "Yeni short", "sc": "Short kapama", "lu": "Long kapama"}


def _num(x) -> float | None:
    x = (x or "").strip().replace(",", ".")
    try:
        v = float(x)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_bulletin(text: str) -> list[list]:
    """Bülten CSV'si (';' ayraçlı; 1. satır Türkçe, 2. satır İngilizce başlık) → XU030 ve USDTRY vadeli satırları."""
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if len(rows) < 3:
        return []
    h = {c.strip().upper(): i for i, c in enumerate(rows[0])}

    def g(r, name):
        i = h.get(name)
        return r[i] if i is not None and i < len(r) else ""
    out = []
    for r in rows[2:]:
        code = g(r, "SOZLESME KODU").strip()
        if not (XU.match(code) or FX.match(code)):
            continue
        settle = _num(g(r, "UZLASMA FIYATI"))
        if not settle:
            continue
        vw = _num(g(r, "AGIRLIKLI ORTALAMA FIYAT"))
        out.append([code, g(r, "VADE TARIHI").strip()[:10], settle, _num(g(r, "ONCEKI UZLASMA FIYATI")),
                    _num(g(r, "KAPANIS FIYATI")), vw if vw else None, _num(g(r, "ISLEM HACMI")) or 0.0,
                    _num(g(r, "ISLEM MIKTARI")) or 0.0, _num(g(r, "ACIK POZISYON")) or 0.0, _num(g(r, "ACIK POZISYON DEGISIMI")) or 0.0])
    return out


def _bdays(end: date, n_days: int) -> list[date]:
    d, out = end, []
    while (end - d).days <= n_days:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def update(hist: dict, today: date | None = None, max_fetch: int = MAX_FETCH, get=None) -> dict:
    """Eksik iş günlerini en yeniden geriye indirir. Yayımlanmamış (404) gün: 2 günden eskiyse tatil sayılır."""
    from . import http
    today = today or date.today()
    days, missing = hist.setdefault("days", {}), set(hist.setdefault("missing", []))
    get_default = get is None
    if get is None:
        def get(url):
            r = http._session.get(url, headers={"User-Agent": http.DEFAULT_UA}, timeout=60)
            return r.text if r.status_code == 200 and len(r.content) > 500 else None
    n = 0
    for d in _bdays(today, KEEP_DAYS):
        k = d.isoformat()
        if k in days or k in missing:
            continue
        if n >= max_fetch:
            break
        n += 1
        try:
            raw = get(BASE.format(d=d.strftime("%Y%m%d")))
        except Exception as e:  # noqa: BLE001
            log.warning("VİOP bülteni %s: %s", k, e)
            raw = None
        rows = parse_bulletin(raw) if raw else []
        if rows:
            days[k] = rows
        elif (today - d).days > 2:
            missing.add(k)
        if get_default:
            time.sleep(0.4)
    cut = (today - timedelta(days=KEEP_DAYS)).isoformat()
    hist["days"] = {k: v for k, v in sorted(days.items()) if k >= cut}
    hist["missing"] = sorted(m for m in missing if m >= cut)
    log.info("VİOP: %d yeni gün indirildi, %d gün kayıtlı", n, len(hist["days"]))
    return hist


def _rows(hist: dict, pat) -> dict[str, dict[str, dict]]:
    """gün → kod → satır sözlüğü"""
    out = {}
    for k, rows in sorted(hist.get("days", {}).items()):
        m = {r[0]: dict(zip(FIELDS, r)) for r in rows if pat.match(r[0])}
        if m:
            out[k] = m
    return out


def near_codes(day: str, m: dict) -> list[str]:
    """Vadesi geçmemiş kontratlar, vadeye göre sıralı."""
    return [c for c, r in sorted(m.items(), key=lambda kv: kv[1]["exp"]) if r["exp"] >= day]


def state(dp: float | None, doi: float | None) -> str | None:
    if dp is None or doi is None or dp == 0 or doi == 0:
        return None
    return ("lb" if doi > 0 else "sc") if dp > 0 else ("sb" if doi > 0 else "lu")


def cost_series(xu: dict, code: str) -> list[list]:
    """Bir kontratın açık pozisyonunun tahmini ortalama maliyeti: [[gün, maliyet, oi, uzlaşma], …]."""
    cost, prev_oi, out = None, 0.0, []
    for k, m in xu.items():
        r = m.get(code)
        if not r:
            continue
        oi, px = r["oi"] or 0.0, r["vwap"] or r["settle"]
        add = oi - prev_oi if prev_oi else oi
        if oi <= 0:
            cost = None
        elif cost is None or prev_oi <= 0:
            cost = px
        elif add > 0:
            cost = (cost * prev_oi + px * add) / oi
        prev_oi = oi
        if cost is not None:
            out.append([k, round(cost, 1), int(oi), r["settle"]])
    return out


def _spot(px, sym: str) -> dict[str, float]:
    if px is None:
        return {}
    s = px[px["sym"] == sym]
    col = "close" if "close" in s.columns else "adj"
    return {str(d)[:10]: float(v) for d, v in zip(s["date"], s[col]) if v == v}


def fx_implied(day: str, m: dict, spot: float | None, r_usd: float | None) -> list[dict]:
    out = []
    if not spot or r_usd is None:
        return out
    d0 = date.fromisoformat(day)
    for c, r in sorted(m.items(), key=lambda kv: kv[1]["exp"]):
        dd = (date.fromisoformat(r["exp"]) - d0).days
        if dd < 20 or not (r["oi"] or r["qty"]):
            continue
        rate = ((r["settle"] / spot) * (1 + r_usd * dd / 360) - 1) * 365 / dd
        out.append({"code": c, "exp": r["exp"], "d": dd, "f": r["settle"], "oi": int(r["oi"]), "r": round(rate, 4)})
    return out


def _interp(curve: list[dict], d: int) -> float | None:
    pts = [(c["d"], c["r"]) for c in curve]
    if not pts:
        return None
    if d <= pts[0][0]:
        return pts[0][1] if pts[0][0] - d <= 15 else None
    for (d1, r1), (d2, r2) in zip(pts, pts[1:]):
        if d1 <= d <= d2:
            return r1 + (r2 - r1) * (d - d1) / (d2 - d1)
    return pts[-1][1] if d - pts[-1][0] <= 15 else None


def build(hist: dict, px=None) -> dict | None:
    xu, fx = _rows(hist, XU), _rows(hist, FX)
    if not xu:
        return None
    s30, sfx, irx = _spot(px, "XU030"), _spot(px, "USDTRY"), _spot(px, "IRX")
    days = list(xu)
    ser = []
    for k in days:
        m = xu[k]
        nc = near_codes(k, m)
        if not nc:
            continue
        a = m[nc[0]]
        b = m[nc[1]] if len(nc) > 1 else None
        dp = a["settle"] - a["prev"] if a["prev"] else None
        S = s30.get(k)
        dd = (date.fromisoformat(a["exp"]) - date.fromisoformat(k)).days
        ann = ((a["settle"] / S) ** (365 / dd) - 1) if S and dd >= 5 else None
        ser.append({"d": k, "c": nc[0], "f": a["settle"], "vw": a["vwap"], "chg": round(a["settle"] / a["prev"] - 1, 5) if a["prev"] else None,
                    "oi": int(a["oi"]), "doi": int(a["oichg"]), "oi_all": int(sum(r["oi"] for r in m.values())),
                    "oi_next": int(b["oi"]) if b else None, "qty": int(a["qty"]), "val": round(a["value"]),
                    "s": round(S, 2) if S else None, "basis": round(a["settle"] - S, 1) if S else None,
                    "ann": round(ann, 4) if ann is not None else None, "dte": dd, "st": state(dp, a["oichg"])})
    if not ser:
        return None
    last = ser[-1]
    m = xu[last["d"]]
    nc = near_codes(last["d"], m)
    contracts = [{"code": c, "exp": m[c]["exp"], "f": m[c]["settle"], "chg": round(m[c]["settle"] / m[c]["prev"] - 1, 5) if m[c]["prev"] else None,
                  "oi": int(m[c]["oi"]), "doi": int(m[c]["oichg"]), "qty": int(m[c]["qty"])} for c in nc if m[c]["oi"] or m[c]["qty"]]
    costs = {c: cost_series(xu, c) for c in nc[:2]}
    win = ser[-20:]
    counts = {k: sum(1 for x in win if x["st"] == k) for k in STATES}
    # vade geçişi: yakın vadenin son ROLL_N iş günü; önceki vadenin aynı noktası
    roll = None
    bd_left = sum(1 for i in range(1, (date.fromisoformat(m[nc[0]]["exp"]) - date.fromisoformat(last["d"])).days + 1)
                  if (date.fromisoformat(last["d"]) + timedelta(days=i)).weekday() < 5)
    if len(nc) > 1 and bd_left <= ROLL_N:
        cur = [{"d": x["d"], "share": round(x["oi_next"] / (x["oi"] + x["oi_next"]), 4)} for x in ser
               if x["c"] == nc[0] and x["oi_next"] is not None and (x["oi"] + x["oi_next"]) > 0][-ROLL_N:]
        prev_exp = None
        for x in reversed(ser):
            if x["c"] != nc[0]:
                prev_exp = x["c"]
                break
        prev = [x for x in ser if x["c"] == prev_exp and x["oi_next"] is not None and (x["oi"] + x["oi_next"]) > 0]
        same = prev[-(bd_left + 1)] if prev_exp and len(prev) > bd_left else None
        roll = {"code": nc[0], "next": nc[1], "bd_left": bd_left, "series": cur,
                "share": cur[-1]["share"] if cur else None,
                "prev_code": prev_exp, "prev_same": round(same["oi_next"] / (same["oi"] + same["oi_next"]), 4) if same else None}
    # dolar/TL ima edilen TL faizi
    fxs, fx_last = [], None
    for k, mm in fx.items():
        r = irx.get(k)
        curve = fx_implied(k, mm, sfx.get(k), r / 100 if r is not None else None)
        if curve:
            fx_last = (k, curve)
            fxs.append({"d": k, "m1": _round(_interp(curve, 30)), "m3": _round(_interp(curve, 91)), "m6": _round(_interp(curve, 182))})
    tl3 = fxs[-1]["m3"] if fxs else None
    tl_d = _interp(fx_last[1], last["dte"]) if fx_last and fx_last[0] == last["d"] else None
    return {
        "generated": _now(), "asof": last["d"], "source": "Borsa İstanbul VİOP günlük bülteni (gün sonu, ücretsiz)",
        "last": last, "contracts": contracts, "states": STATES, "counts20": counts,
        "cost": {c: s[-260:] for c, s in costs.items()},
        "series": [{k: x[k] for k in ("d", "c", "f", "chg", "oi", "doi", "oi_all", "s", "basis", "ann", "st", "vw")} for x in ser[-260:]],
        "roll": roll,
        "fx": {"asof": fx_last[0] if fx_last else None, "curve": fx_last[1] if fx_last else [], "hist": fxs[-260:],
               "note": "Dolar/TL vadelilerinden ima edilen TL faizi; spot kur Yahoo kapanışı, ABD faizi 3 aylık bono"},
        "carry": {"xu_ann": last["ann"], "tl_same": _round(tl_d), "tl3": tl3,
                  "excess": _round(last["ann"] - tl_d) if last["ann"] is not None and tl_d is not None else None},
    }


def _round(v, n=4):
    return round(v, n) if v is not None else None


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(px=None) -> dict | None:
    OUT.mkdir(parents=True, exist_ok=True)
    hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
    hist = update(hist)
    HIST.write_text(json.dumps(hist, separators=(",", ":")), encoding="utf-8")
    if px is None:
        try:
            import pandas as pd
            p = OUT / "px.parquet"
            px = pd.read_parquet(p) if p.exists() else None
        except Exception:  # noqa: BLE001
            px = None
    doc = build(hist, px)
    if doc:
        DOC.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log.info("VİOP: %s · %s %.0f · OI %d · %s", doc["asof"], doc["last"]["c"], doc["last"]["f"], doc["last"]["oi"], doc["last"]["st"])
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run()
    sys.exit(0)
