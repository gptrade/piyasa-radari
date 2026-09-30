"""SPK bültenleri: yıllık bülten sayfasındaki PDF'leri indirir, izleme listesindeki şirketleri bulur.

Bültende sermaye artırımı onayı, halka arz, işlem yasağı, idari para cezası, pay satış
izinleri gibi kararlar şirket adıyla geçer. Eşleşen şirketler için ilgili paragraflar Claude'a
gönderilir; eşleşme yoksa bülten sadece listelenir.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from .. import http
from ..models import Item, iso, make_id, now_utc
from . import Context
from .feeds import parse_tr_date

log = logging.getLogger("radar.spk")

IST = ZoneInfo("Europe/Istanbul")
LIST_URL = "https://spk.gov.tr/spk-bultenleri/{year}-yili-spk-bultenleri"
PDF_RE = re.compile(r'href="([^"]*/(\d{4})-(\d{1,3})\.pdf)"', re.I)
MONTHS = {m: i for i, m in enumerate(
    ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos",
     "eylül", "ekim", "kasım", "aralık"], 1)}
DATE_RE = re.compile(r"(\d{1,2})\s+(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s+(\d{4})", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def parse_listing(html: str, base: str) -> list[dict]:
    """Sayfadaki bülten bağlantıları: [{url, no, date}], en yeni önce."""
    out, seen = [], set()
    for m in PDF_RE.finditer(html):
        url = urljoin(base, m.group(1))
        if url in seen:
            continue
        seen.add(url)
        # Tarih bağlantı metninde, hemen sonrasında ya da öncesinde olabilir; en yakınını al.
        after = TAG_RE.sub(" ", html[m.end(): m.end() + 600])
        before = TAG_RE.sub(" ", html[max(0, m.start() - 400): m.start()])
        date = parse_tr_date(after)
        if date is None:
            prev = [parse_tr_date(x) for x in re.split(r"Bülten No", before)[-1:]]
            date = prev[0] if prev and prev[0] else None
        if date is not None and date.hour == 0 and date.minute == 0:
            date = date.replace(hour=18)
        out.append({"url": url, "no": f"{m.group(2)}/{int(m.group(3))}", "n": int(m.group(3)),
                    "year": int(m.group(2)), "date": date})
    out.sort(key=lambda b: (b["year"], b["n"]), reverse=True)
    return out


def excerpts(text: str, matcher, symbols: list[str], width: int = 1500, limit: int = 40000) -> str:
    """Eşleşen şirket adlarının geçtiği bölümleri kes (Claude'a tüm bülten yerine)."""
    spans = []
    for sym in symbols:
        st = matcher.by_symbol(sym)
        names = [a for a in [st.name, *st.aliases] if len(a) > 3] if st else []
        for n in names:
            for m in re.finditer(re.escape(n), text, re.I):
                spans.append((max(0, m.start() - width // 3), min(len(text), m.end() + width)))
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return "\n...\n".join(text[a:b] for a, b in merged)[:limit]


def collect(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("spk")
    if not cfg.get("enabled", True):
        return []
    year = now_utc().astimezone(IST).year
    base = LIST_URL.format(year=year)
    r = http.get(base)
    if r is None:
        return []
    bulletins = parse_listing(r.text, base)[: int(cfg.get("max_per_run", 3))]
    from pypdf import PdfReader
    out: list[Item] = []
    for b in bulletins:
        iid = make_id("spk", b["url"])
        if iid in ctx.seen:
            continue
        if b["date"] and b["date"] < ctx.since:
            continue
        if b["date"] is None and not ctx.seen and bulletins.index(b) > 0:
            continue                          # ilk çalıştırma, tarih yok: sadece en yeni bülten
        pdf = http.get(b["url"], timeout=60)
        if pdf is None:
            continue
        try:
            reader = PdfReader(io.BytesIO(pdf.content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages[:60])
            if b["date"] is None:            # listede tarih yoksa: PDF'in kendi tarihi
                try:
                    b["date"] = reader.metadata.creation_date if reader.metadata else None
                except Exception:
                    b["date"] = None
                if b["date"] is None:
                    b["date"] = parse_tr_date(text[:1500])
                if b["date"] is not None and b["date"].tzinfo is None:
                    b["date"] = b["date"].replace(tzinfo=IST)
        except Exception as e:
            log.warning("SPK %s okunamadı: %s", b["no"], e)
            continue
        tickers = ctx.matcher.match(text, market="BIST")
        body = excerpts(text, ctx.matcher, tickers) if tickers else ""
        names = ", ".join(tickers) if tickers else "izleme listesinden şirket yok"
        out.append(Item(
            id=iid, source="SPK Bülteni", source_type="regulator", market="BIST",
            title=f"SPK Bülteni {b['no']} — {names}",
            summary=("İzleme listesindeki şirketler geçiyor: " + ", ".join(tickers)) if tickers
            else "Bu bültende izleme listesindeki şirketlere dair karar bulunamadı.",
            url=b["url"], published=iso(b["date"] or now_utc()), tickers=tickers, lang="tr",
            extra={"bulletin": b["no"], "full_text": body},
        ))
    log.info("SPK: %d bülten", len(out))
    return out
