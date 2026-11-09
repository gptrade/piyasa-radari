"""Aracı kurumların kredili işlemleri (hisse senedi teminatlı kredi), Türkiye Sermaye Piyasaları Birliği (TSPB).

Kaynak: https://tspb.org.tr/veriler/ — "Aracı Kurumların Kredili İşlemleri" (2026'dan, aylık) ve arşiv (2002–2025; 2024
sonuna kadar çeyreklik, 2025'ten aylık). Dosya adları her güncellemede değiştiği için bağlantılar sayfadan okunur.
TSPB kullanım koşulları: yayınlar kaynak gösterilerek izinsiz kullanılabilir; ticari kullanım yazılı izne tabidir
(site ücretli bir ürüne dönüşürse izin alınmalı). Veri, ay sonundan ~1 ay sonra yayımlanır.

Çıktı (guc dalı, yayımlanmaz): kredili.json {"updated", "rows": [[YYYY-MM, kredi_tl, kullanan, sozlesmeli], ...]}.
Korku endeksi bileşeni: son 3 ayda kredi bakiyesindeki büyümenin XU100 getirisinden farkı (kaldıraç ivmesi).
"""
from __future__ import annotations

import io
import json
import math
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import http

log = logging.getLogger("radar.kredili")

PAGE = "https://tspb.org.tr/veriler/"
UA = "Mozilla/5.0 (compatible; LyraRadar/1.0; kisisel arastirma)"
LINK = re.compile(r"https://tspb\.org\.tr/wp-content/uploads/[^\"'\s]+\.xlsx")
REFRESH_DAYS = 3


def parse_xlsx(raw: bytes) -> dict[str, tuple]:
    """'2026 - 10' ya da '2002-03' tarihli satırlar → {YYYY-MM: (kredi_tl, kullanan, sozlesmeli)}."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(raw), data_only=True).worksheets[0]
    out = {}
    for r in ws.iter_rows(values_only=True):
        t = r[1] if len(r) > 5 else None
        m = re.match(r"^\s*(\d{4})\s*-\s*(\d{1,2})\s*$", t) if isinstance(t, str) else None
        if m and isinstance(r[5], (int, float)) and r[5] > 0:
            out[f"{m[1]}-{int(m[2]):02d}"] = (float(r[5]), int(r[4] or 0), int(r[3] or 0))
    return out


def links(html: str) -> list[str]:
    """Kredili işlem dosyaları: güncel ("Kredili_Islemleri") ve arşiv ("Krediler_2002")."""
    return sorted({u for u in LINK.findall(html) if "Kredili_Islemleri" in u or "Krediler_2002" in u})


def update(path: Path, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if old and now - datetime.fromisoformat(old["updated"]) < timedelta(days=REFRESH_DAYS):
        return old
    r = http.get(PAGE, headers={"User-Agent": UA}, timeout=30, retries=1)
    if r is None or r.status_code != 200:
        log.warning("TSPB veriler sayfası alınamadı")
        return old
    rows: dict[str, tuple] = {}
    for u in sorted(links(r.text), key=lambda u: "Krediler_2002" not in u):    # önce arşiv, güncel üstüne yazar
        x = http.get(u, headers={"User-Agent": UA}, timeout=60, retries=1)
        if x is None or x.status_code != 200:
            continue
        try:
            rows.update(parse_xlsx(x.content))
        except Exception:  # noqa: BLE001
            log.exception("TSPB dosyası okunamadı: %s", u)
    if not rows:
        return old
    doc = {"updated": now.isoformat(timespec="seconds"), "source": PAGE,
           "rows": [[k, *rows[k]] for k in sorted(rows)]}
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("TSPB kredili işlemler: %d dönem, son %s", len(rows), doc["rows"][-1][0])
    return doc


def lag_days(ym: str) -> int:
    """Yayım gecikmesi: 2025'ten beri aylık ve ay başında (Ekim verisi 4 Kasım); öncesi çeyreklik raporlarla, daha geç."""
    return 7 if ym >= "2025-01" else 45


def leverage(doc: dict | None, bench: pd.Series) -> pd.Series | None:
    """Kaldıraç ivmesi: son 3 ayda kredi bakiyesinin XU100'den ne kadar hızlı büyüdüğü (log fark). Seviye yerine
    değişim kullanılır, çünkü bakiye yatırımcı tabanıyla birlikte yıllar içinde yapısal olarak büyüyor. Değer yayım
    tarihinden itibaren geçerli, günlük ileri taşınır."""
    if not doc or not doc.get("rows"):
        return None
    b = bench.dropna()
    k = {ym: kredi for ym, kredi, *_ in doc["rows"]}
    vals = {}
    for ym, kredi in k.items():
        p = pd.Period(ym, "M")
        ym3 = str(p - 3)
        if ym3 not in k:
            continue
        me, me3 = p.to_timestamp(how="end").normalize(), (p - 3).to_timestamp(how="end").normalize()
        x, x3 = b.loc[:me], b.loc[:me3]
        if x.empty or x3.empty or (me - x.index[-1]).days > 10 or (me3 - x3.index[-1]).days > 10:
            continue
        vals[me + pd.Timedelta(days=lag_days(ym))] = math.log(kredi / k[ym3]) - math.log(float(x.iloc[-1]) / float(x3.iloc[-1]))
    if not vals:
        return None
    s = pd.Series(vals).sort_index()
    return s.reindex(s.index.union(b.index)).ffill().reindex(b.index)


def latest(doc: dict | None) -> dict | None:
    if not doc or not doc.get("rows"):
        return None
    rows = doc["rows"]
    ym, kredi, users, contracts = rows[-1]
    prev = next((r for r in reversed(rows[:-1]) if r[0] < ym), None)
    yago = next((r for r in rows if r[0] == f"{int(ym[:4]) - 1}{ym[4:]}"), None)
    return {"ym": ym, "kredi": kredi, "users": users, "contracts": contracts,
            "m1": round(kredi / prev[1] - 1, 4) if prev else None, "y1": round(kredi / yago[1] - 1, 4) if yago else None,
            "peak": max(r[1] for r in rows[-12:]), "peak_ym": max(rows[-12:], key=lambda r: r[1])[0]}
