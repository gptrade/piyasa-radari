"""Rapor kutusu: inbox/ klasörüne bırakılan PDF/TXT/MD raporlarını (aracı kurum,
değerleme, sektör raporu) okur. GitHub web arayüzünden dosya yüklemek yeterli.

Dosya adında hisse kodu geçerse eşleşir: ör. `2026-09-27_VAKBN_IsYatirim.pdf`.
Geçmezse metin içinden izleme listesiyle eşleştirilir.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from ..config import INBOX
from ..models import UTC, Item, iso, make_id
from . import Context

log = logging.getLogger("radar.reports")


def extract_text(path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:40])
    return path.read_text(encoding="utf-8", errors="ignore")


def collect(ctx: Context) -> list[Item]:
    if not ctx.cfg("reports_inbox").get("enabled", True) or not INBOX.exists():
        return []
    out: list[Item] = []
    for path in sorted(INBOX.iterdir()):
        if path.suffix.lower() not in (".pdf", ".txt", ".md") or path.name.startswith(".") \
                or path.stem.upper() == "README":
            continue
        try:
            text = extract_text(path)
        except Exception as e:  # bozuk PDF paneli durdurmasın
            log.warning("%s okunamadı: %s", path.name, e)
            continue
        stem = path.stem.replace("_", " ").replace("-", " ")
        tickers = ctx.matcher.match(stem) or ctx.matcher.match(text[:20000])
        if not tickers:
            log.info("%s: izleme listesinden hisse bulunamadı, atlandı", path.name)
            continue
        st = ctx.matcher.by_symbol(tickers[0])
        m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        ts = datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC) if m else \
            datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        out.append(Item(
            id=make_id("report", path.name),
            source="Rapor kutusu", source_type="report", market=st.market if st else "BIST",
            # Rapor metni panele (herkese açık Pages) YAZILMAZ; sadece AI özeti yayınlanır.
            title=f"Rapor: {path.stem}", summary="",
            url="", published=iso(ts), tickers=tickers,
            lang="tr", extra={"file": path.name, "full_text": text[:60000]},
        ))
    log.info("Rapor kutusu: %d rapor", len(out))
    return out
