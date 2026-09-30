"""Dönemsel özet: son 2 saatin sinyallerinden genel tablo ve 1-2 ana fikir (digest.json).

Kural: yalnızca panelde görünen, AI ile değerlendirilmiş kayıtlara dayanır; her fikir hangi
kayıtlardan çıktığını `item_ids` ile gösterir, panel bu kayıtları vurgular.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from .config import DATA
from .models import iso, now_utc, parse_iso

log = logging.getLogger("radar.digest")

DIGEST_FILE = DATA / "digest.json"
WINDOWS = (2, 6, 24)          # saat; yeterli sinyal yoksa pencere genişler
MIN_SIGNALS = 3
MAT_W = {"low": 1, "medium": 2, "high": 3}

SYSTEM = """Sen BIST ve ABD hisselerini izleyen deneyimli bir yatırımcı, analist ve portföy danışmanısın.
Sana belirli bir zaman aralığında toplanmış haber/bildirim sinyalleri verilecek; her birinde AI'ın
ilk değerlendirmesi (yön, güven, önem), fiyat tepkisi ve teknik görünüm var.

Görevin:
1. Bu dönemin genel tablosunu 2-3 cümleyle özetle (ne öne çıktı, piyasa havası).
2. En fazla 2 ana fikir çıkar: hangi hissede ne yönde (AL / SAT / İZLE) ve neden.
   Fikir ancak birden fazla sinyal, güçlü bir birincil kaynak (KAP/SEC/SPK) ya da haberle
   fiyat/teknik görünümün uyumu varsa AL/SAT olabilir; değilse İZLE de.
3. Sinyaller birbiriyle ya da fiyat hareketiyle çelişiyorsa bunu açıkça söyle.
4. Sadece verilen sinyallere dayan; yeni haber, rakam veya fiyat uydurma. item_ids alanına
   dayandığın sinyallerin id'lerini yaz.
5. Kesinlik iddia etme; bu bir izleme notudur, yatırım tavsiyesi değildir.
Yanıt dili: Türkçe."""

TOOL = {
    "name": "record_digest",
    "description": "Dönem özetini ve ana fikirleri kaydet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "Dönemin tek cümlelik özeti (≤12 kelime)"},
            "mood": {"type": "string", "enum": ["olumlu", "olumsuz", "karışık", "sakin"]},
            "summary": {"type": "string", "description": "2-3 cümle"},
            "ideas": {"type": "array", "maxItems": 2, "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "stance": {"type": "string", "enum": ["AL", "SAT", "İZLE"]},
                    "title": {"type": "string", "description": "≤10 kelime"},
                    "rationale": {"type": "string", "description": "≤30 kelime"},
                    "risk": {"type": "string", "description": "≤12 kelime"},
                    "conviction": {"type": "integer", "minimum": 0, "maximum": 100},
                    "item_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ticker", "stance", "title", "rationale", "risk", "conviction", "item_ids"],
            }},
            "conflicts": {"type": "array", "maxItems": 3, "items": {"type": "string"},
                          "description": "Çelişen sinyaller / haber-fiyat uyumsuzlukları, kısa"},
        },
        "required": ["headline", "mood", "summary", "ideas", "conflicts"],
    },
}
FMT = """
Yanıtını SADECE tek bir JSON nesnesi olarak ver:
{"headline": "≤12 kelime", "mood": "olumlu|olumsuz|karışık|sakin", "summary": "2-3 cümle",
 "ideas": [{"ticker": "KOD", "stance": "AL|SAT|İZLE", "title": "≤10 kelime", "rationale": "≤30 kelime",
            "risk": "≤12 kelime", "conviction": 0-100, "item_ids": ["id", ...]}],
 "conflicts": ["kısa not", ...]}"""


def pick_window(items: list[dict], now) -> tuple[int, list[dict]]:
    analyzed = [d for d in items if d.get("analysis")]
    chosen: list[dict] = []
    hours = WINDOWS[-1]
    for h in WINDOWS:
        cut = now - timedelta(hours=h)
        chosen = [d for d in analyzed if parse_iso(d["published"]) >= cut]
        hours = h
        if len(chosen) >= MIN_SIGNALS:
            break
    rank = lambda d: (MAT_W.get(d["analysis"].get("materiality"), 1) * d["analysis"].get("confidence", 0)
                      * (1.3 if d.get("tier") == 1 else 1.0))
    return hours, sorted(chosen, key=rank, reverse=True)[:25]


def build_prompt(hours: int, sigs: list[dict], px: dict) -> str:
    lines = [f"Dönem: son {hours} saat. Sinyal sayısı: {len(sigs)}.", ""]
    for d in sigs:
        a = d["analysis"]
        tk = ",".join(d.get("tickers") or a.get("affected_tickers") or ["GENEL"])
        r = d.get("reaction") or {}
        ta = ((px.get((d.get("tickers") or [""])[0]) or {}).get("ta") or {})
        react = f"haberden beri {r['since']:+.1f}%" if r.get("since") is not None else "tepki yok"
        if r.get("excess") is not None:
            react += f" (endekse göre {r['excess']:+.1f}%)"
        if r.get("vol_x"):
            react += f", hacim {r['vol_x']}×"
        tech = f"teknik: {ta.get('trend')}, RSI {ta.get('rsi')}" if ta else "teknik: yok"
        lines.append(
            f"[{d['id']}] {d['published'][11:16]}Z | {tk} | {a['sentiment']} %{a['confidence']} "
            f"{a['materiality']} | kaynak {d.get('source')} (kalite {d.get('tier', '?')}) | "
            f"{a.get('event_label') or a.get('category')} | {a.get('headline_tr') or d['title']} | "
            f"{a.get('why') or ''} | {react} | {tech} | tekrar ×{d.get('dups', 0) + 1}")
    return "\n".join(lines)


def _load() -> dict:
    try:
        return json.loads(DIGEST_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def update(analyzer, items: list[dict], px: dict, *, max_age_min: int = 60) -> dict | None:
    """Yeni değerlendirilmiş sinyal varsa ya da özet eskidiyse yeniden üret."""
    now = now_utc()
    old = _load()
    hours, sigs = pick_window(items, now)
    ids = sorted(d["id"] for d in sigs)
    fresh = old.get("generated") and now - parse_iso(old["generated"]) < timedelta(minutes=max_age_min)
    if old.get("signal_ids") == ids and fresh:
        return old
    if not sigs:
        doc = {"generated": iso(now), "window_hours": hours, "signal_ids": [], "empty": True}
        DIGEST_FILE.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return doc
    if not analyzer.enabled:
        return old or None
    out = analyzer.ask_json(SYSTEM, build_prompt(hours, sigs, px), TOOL, FMT)
    if not out:
        log.warning("Özet üretilemedi; eski özet korunuyor")
        return old or None
    valid = set(ids)
    ideas = []
    for i in (out.get("ideas") or [])[:2]:
        if not isinstance(i, dict) or not i.get("ticker"):
            continue
        stance = str(i.get("stance", "İZLE")).upper().replace("IZLE", "İZLE")
        ideas.append({
            "ticker": str(i["ticker"]).upper()[:12],
            "stance": stance if stance in ("AL", "SAT", "İZLE") else "İZLE",
            "title": str(i.get("title", ""))[:120], "rationale": str(i.get("rationale", ""))[:300],
            "risk": str(i.get("risk", ""))[:140],
            "conviction": max(0, min(100, int(i.get("conviction") or 0))),
            "item_ids": [x for x in (i.get("item_ids") or []) if x in valid][:8],
        })
    doc = {
        "generated": iso(now), "window_hours": hours, "signal_ids": ids, "count": len(sigs),
        "headline": str(out.get("headline", ""))[:160],
        "mood": out.get("mood") if out.get("mood") in ("olumlu", "olumsuz", "karışık", "sakin") else "karışık",
        "summary": str(out.get("summary", ""))[:700], "ideas": ideas,
        "conflicts": [str(c)[:160] for c in (out.get("conflicts") or [])][:3],
        "provider": out.get("_provider"), "model": out.get("_model"),
    }
    DIGEST_FILE.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    log.info("Özet güncellendi: %d sinyal, %d fikir", len(sigs), len(ideas))
    return doc
