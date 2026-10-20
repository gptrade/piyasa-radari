"""Olay karnesi (Faz 2): olay veritabanından (radar/eventdb.py) olay tipine ve yöne göre anormal getiri.

Çıktı: site/data/olay/karne.json (radar iş akışı yayımlar). İçerik:
  rows    son 1 yılın küme başı olayları (idari hariç) · tarayıcıda süzülüp toplanır (pazar, tip, yön, Benimkiler)
  paths   pazar × tip × yön için 0–20 seans ortalama anormal getiri yolu ve gün kümelenmiş %95 aralık
Anormal getiri: BIST'te eşit ağırlıklı BIST Tüm'e göre (ae), ABD'de S&P 500'e göre (ar).
Aralıklar olay gününe göre kümelenmiş standart hatayla: aynı gün çok sayıda olay (ör. piyasa geneli düşüş günü) birbirinden
bağımsız sayılmaz.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import timedelta

import numpy as np
import pandas as pd

log = logging.getLogger("radar.eventstudy")

N = 20
RECENT_TEXT = 800
SKIP = {"idari"}
REACT = {"borsa_tedbir"}                       # fiyat hareketinin sonucu (devre kesici): "Tüm olaylar" yoluna girmez
LABELS = {
    "finansal": "Finansal sonuç", "temettu": "Kâr payı", "geri_alim": "Pay geri alımı", "sermaye": "Sermaye işlemi", "birlesme": "Birleşme / pay alım teklifi",
    "is_iliskisi": "Yeni iş / sipariş", "yatirim": "Yatırım / varlık alım-satım", "iceriden": "İçeriden işlem", "borclanma": "Borçlanma aracı",
    "derecelendirme": "Derecelendirme", "endeks": "Endeks değişikliği", "borsa_tedbir": "Borsa tedbiri / devre kesici", "kap_ozel": "Özel durum açıklaması",
    "kap_diger": "Diğer KAP bildirimi", "genel_kurul": "Genel kurul", "hukuki": "Hukuki", "beklenti": "Geleceğe dönük beklenti", "broker_not": "Aracı kurum notu",
    "hedef_degisim": "Hedef fiyat değişimi", "haber": "Haber", "sosyal": "Sosyal medya", "teknik": "Teknik sinyal", "regulasyon": "Regülasyon",
    "anomali": "Fiyat/hacim anomalisi", "makro": "Makro veri",
}
BENCH = {"BIST": "eşit ağırlıklı BIST Tüm", "US": "S&P 500"}


def _s(v) -> str:
    return v if isinstance(v, str) else ""


def clustered_mean(x: np.ndarray, g: np.ndarray) -> tuple[float, float]:
    """Ortalama ve gün kümelenmiş standart hata (küme sayısı < 2 ise klasik)."""
    n = len(x)
    if n == 0:
        return float("nan"), float("nan")
    m = float(x.mean())
    if n < 2:
        return m, float("nan")
    df = pd.DataFrame({"e": x - m, "g": g})
    s = df.groupby("g")["e"].sum().to_numpy()
    G = len(s)
    if G < 2:
        return m, float(x.std(ddof=1) / math.sqrt(n))
    var = (G / (G - 1)) * (s ** 2).sum() / n ** 2
    return m, float(math.sqrt(var))


def paths(ev: pd.DataFrame, px: pd.DataFrame, universe: list[str]) -> dict:
    """Pazar × tip × yön için 0..N seans ortalama yol. ev: küme başı olaylar (id, sym, market, type, dir, ts_eff)."""
    from .eventdb import JUMP, SESS, INDEX, ew_index
    px = px.assign(date=pd.to_datetime(px["date"]).dt.date)
    wide = px.pivot_table(index="date", columns="sym", values="adj_close", aggfunc="last").sort_index()
    jumps = wide.pct_change(fill_method=None).abs() > JUMP
    out = {}
    for mkt in ("BIST", "US"):
        idx = INDEX[mkt]
        if idx not in wide.columns:
            continue
        cal = wide[idx].dropna()
        bench = ew_index(wide, universe).reindex(cal.index) if mkt == "BIST" else cal
        W = wide.reindex(cal.index)
        J = jumps.reindex(cal.index).fillna(False)
        dates = list(cal.index)
        pos = {d: i for i, d in enumerate(dates)}
        g = ev[(ev.market == mkt) & ev.sym.isin(W.columns)]
        recs = []
        for r in g.itertuples(index=False):
            de = pd.Timestamp(r.ts_eff).tz_convert(SESS[mkt][0]).date()
            i = pos.get(de)
            if i is None:
                nxt = [k for k, d in enumerate(dates) if d >= de]
                if not nxt:
                    continue
                i = nxt[0]
            if i == 0:
                continue
            s = W[r.sym].to_numpy()
            b = bench.to_numpy()
            p0, b0 = s[i - 1], b[i - 1]
            if not p0 or np.isnan(p0):
                continue
            j_end = min(len(dates), i + N)
            seg = s[i:j_end] / p0 - 1
            bseg = b[i:j_end] / b0 - 1
            jm = J[r.sym].to_numpy()[i:j_end]
            if jm.any():
                cut = int(np.argmax(jm))
                seg, bseg = seg[:cut], bseg[:cut]
            path = np.full(N + 1, np.nan)
            path[0] = 0.0
            path[1:1 + len(seg)] = (seg - bseg) * 100
            recs.append((r.type, int(r.dir) if pd.notna(r.dir) else 0, dates[i - 1], path))
        if not recs:
            continue
        types = sorted({t for t, *_ in recs})
        for t in types + ["*"]:
            sel = [x for x in recs if (t == "*" and x[0] not in REACT) or x[0] == t]
            for dk, dsel in (("all", sel), ("pos", [x for x in sel if x[1] > 0]), ("neg", [x for x in sel if x[1] < 0])):
                if len(dsel) < 20:
                    continue
                P = np.vstack([x[3] for x in dsel]); G = np.array([str(x[2]) for x in dsel])
                m, lo, hi, n = [], [], [], []
                for k in range(N + 1):
                    col = P[:, k]; ok = ~np.isnan(col)
                    if ok.sum() < 10:
                        break
                    mm, se = clustered_mean(col[ok], G[ok])
                    m.append(round(mm, 3)); n.append(int(ok.sum()))
                    lo.append(round(mm - 1.96 * se, 3) if not math.isnan(se) else round(mm, 3))
                    hi.append(round(mm + 1.96 * se, 3) if not math.isnan(se) else round(mm, 3))
                out[f"{mkt}|{t}|{dk}"] = {"m": m, "lo": lo, "hi": hi, "n": n}
    return out


def build(ev: pd.DataFrame, ret: pd.DataFrame, px: pd.DataFrame | None, universe: list[str], now: pd.Timestamp) -> dict:
    since = now - timedelta(days=365)
    e = ev[(ev.cluster == ev.id) & ~ev.type.isin(SKIP) & ev.sym.fillna("").ne("") & ev.market.isin(["BIST", "US"])]
    e = e[pd.to_datetime(e.ts, utc=True) >= since]
    m = e.merge(ret, on=["id", "sym"], how="inner")
    rows = []
    for k, r in enumerate(m.sort_values("ts", ascending=False).itertuples(index=False)):
        txt = k < RECENT_TEXT                                # metin yalnız son olaylarda (liste); gerisi yalnız sayı
        a = (lambda h: getattr(r, f"ae{h}", None)) if r.market == "BIST" else (lambda h: getattr(r, f"ar{h}", None))
        v = [a(h) for h in (1, 5, 20)]
        if all(x is None or pd.isna(x) for x in v):
            continue
        rows.append([r.sym, r.market, r.type, int(r.dir) if pd.notna(r.dir) else 0,
                     1 if (pd.notna(r.conf) and r.conf >= 0.7 and r.mat in ("high", "medium")) else 0,
                     pd.Timestamp(r.ts).tz_convert("Europe/Istanbul").strftime("%Y-%m-%d %H:%M"), str(r.d0),
                     *[None if x is None or pd.isna(x) else round(float(x), 2) for x in v],
                     None if pd.isna(r.pre5) else round(float(r.pre5), 2),
                     _s(r.subtype)[:50] if txt else "", _s(r.title)[:140] if txt else "", _s(r.url) if txt else ""])
    doc = {
        "generated": now.isoformat(timespec="seconds"), "since": since.date().isoformat(),
        "cols": ["sym", "m", "type", "dir", "strong", "ts", "d0", "a1", "a5", "a20", "pre5", "sub", "title", "url"],
        "rows": rows, "labels": LABELS, "bench": BENCH,
        "paths": paths(e, px, universe) if px is not None and not px.empty else {},
    }
    return doc


def write(path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    log.info("Olay karnesi: %d olay, %d yol", len(doc["rows"]), len(doc["paths"]))
