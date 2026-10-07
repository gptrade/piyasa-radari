"""Gizli rapor kutusu: kullanıcının gizli GitHub reposuna (gptrade/piyasa-radari-raporlar) yüklediği aracı kurum
raporları. İş akışı repoyu RAPOR_REPO_TOKEN ile `_raporlar/` klasörüne çeker (site/ dışında: yayımlanmaz).

Klasörler: sirket/ · sektor/ · strateji/. Her biri altında
- tek dosya = bir rapor: .pdf .txt .md .jpg .jpeg .png
- alt klasör = çok sayfalı rapor (sayfalar ada göre sıralanır: 1.jpg, 2.jpg …)

Yayın ilkesi (kullanıcının seçimi: "a"):
- Sitede (research.json, feed.json): yalnız yapılandırılmış alanlar — kurum, tarih, hisse(ler), tavsiye, hedef fiyat,
  tahmin değişimleri (rakam), AI'ın kendi cümleleriyle kısa tez, katalizör/risk başlıkları, sektör görüşü.
- Ayrıntılı özet yalnız Telegram'a gider. Rapor metni, görseli, dosya adı hiçbir yerde yayımlanmaz.
- İşlenen raporlar içerik özetiyle (sha1) hatırlanır: aynı dosya tekrar okunmaz.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from . import http
from .config import DATA
from .models import UTC, Item, iso, make_id, now_utc

log = logging.getLogger("radar.private_reports")

ROOT = Path(os.environ.get("RAPOR_DIR", "_raporlar"))
DONE = DATA / "private_reports_done.json"         # yalnız sha1 listesi (dosya adı yok)
KINDS = {"sirket": "Şirket raporu", "sektor": "Sektör raporu", "strateji": "Strateji / model portföy"}
TEXT_EXT = {".txt", ".md"}
IMG_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MAX_IMAGES = 12
MAX_CHARS = 60000


def available() -> bool:
    return ROOT.is_dir()


def units(root: Path = ROOT) -> list[dict]:
    """Rapor birimleri: {kind, path, files:[Path], sha}. Gizli/README dosyaları atlanır."""
    out = []
    for folder, kind in KINDS.items():
        base = root / folder
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.name.startswith(".") or p.stem.upper() in ("OKU", "README"):
                continue
            if p.is_dir():
                files = sorted((f for f in p.iterdir() if f.suffix.lower() in IMG_EXT or f.suffix.lower() == ".pdf"),
                               key=lambda f: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", f.stem)])
            elif p.suffix.lower() in IMG_EXT or p.suffix.lower() in TEXT_EXT or p.suffix.lower() == ".pdf":
                files = [p]
            else:
                continue
            if not files:
                continue
            h = hashlib.sha1()
            for f in files:
                h.update(f.read_bytes())
            out.append({"kind": folder, "path": p, "files": files, "sha": h.hexdigest()})
    return out


def name_hints(p: Path) -> dict:
    """Dosya/klasör adından ipuçları: tarih, hisse kodu ya da sektör, kurum (hepsi isteğe bağlı)."""
    stem = p.stem if p.is_file() else p.name
    m = re.match(r"(\d{4}-\d{2}-\d{2})[_\- ]*(.*)", stem)
    date, rest = (m.group(1), m.group(2)) if m else (None, stem)
    parts = [x for x in re.split(r"[_]+", rest) if x]
    return {"date": date, "subject": parts[0] if parts else None, "broker": " ".join(parts[1:]) or None}


def _shrink(data: bytes, mime: str) -> tuple[str, bytes]:
    """Büyük görselleri 2000 px'e küçültür (AI istek sınırları ve kota için)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if max(im.size) <= 2000 and len(data) < 1_500_000:
            return mime, data
        im.thumbnail((2000, 2000))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=85)
        return "image/jpeg", buf.getvalue()
    except Exception:
        return mime, data


def content(unit: dict) -> tuple[str, list]:
    """(metin, medya). Metni çıkan PDF/TXT metin olarak; görseller ve metinsiz (taranmış) PDF'ler medya olarak."""
    texts, media = [], []
    for f in unit["files"]:
        ext = f.suffix.lower()
        data = f.read_bytes()
        if ext in TEXT_EXT:
            texts.append(data.decode("utf-8", "ignore"))
        elif ext in IMG_EXT and len(media) < MAX_IMAGES:
            media.append(_shrink(data, IMG_EXT[ext]))
        elif ext == ".pdf":
            text = ""
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(data))
                text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:40])
            except Exception as e:
                log.warning("PDF okunamadı: %s", e)
            if len(text.strip()) > 500:
                texts.append(text)
            elif len(data) < 18_000_000:
                media.append(("application/pdf", data))     # taranmış PDF: AI sayfa görüntüsünden okur
    return "\n\n".join(texts)[:MAX_CHARS], media


REPORT_TOOL = {
    "name": "record_report",
    "description": "Aracı kurum raporundan yapılandırılmış bilgileri kaydet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["sirket", "sektor", "strateji"]},
            "broker": {"type": "string", "description": "Raporu yayımlayan kurum"},
            "date": {"type": "string", "description": "Rapor tarihi YYYY-AA-GG (yoksa boş)"},
            "tickers": {"type": "array", "items": {"type": "string"}, "description": "Raporun konu ettiği hisse kodları (BIST kodu ya da ABD sembolü)"},
            "sector": {"type": "string"},
            "rating": {"type": "string", "description": "Ana hisse için tavsiye: AL / TUT / SAT (kurumun ifadesi Endeks Üstü vb. ise karşılığı)"},
            "target_price": {"type": "number"}, "prev_target": {"type": "number"},
            "currency": {"type": "string", "enum": ["TRY", "USD", "EUR", ""]},
            "estimate_changes": {"type": "array", "maxItems": 8, "items": {"type": "object", "properties": {
                "metric": {"type": "string"}, "period": {"type": "string"}, "new": {"type": "string"},
                "old": {"type": "string"}, "change": {"type": "string"}}, "required": ["metric", "new"]}},
            "top_picks": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"}, "rating": {"type": "string"}, "target_price": {"type": "number"}},
                "required": ["ticker"]}, "description": "Sektör/strateji raporunda öne çıkarılan hisseler"},
            "model_portfolio": {"type": "object", "properties": {
                "added": {"type": "array", "items": {"type": "string"}}, "removed": {"type": "array", "items": {"type": "string"}}}},
            "sector_view": {"type": "string", "enum": ["olumlu", "nötr", "olumsuz", ""]},
            "thesis": {"type": "string", "description": "Kendi cümlelerinle 2-3 cümlelik tez; rapordan cümle kopyalama"},
            "catalysts": {"type": "array", "items": {"type": "string"}, "maxItems": 4, "description": "Kısa başlıklar, ≤10 kelime"},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 4, "description": "Kısa başlıklar, ≤10 kelime"},
            "sentiment": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "materiality": {"type": "string", "enum": ["low", "medium", "high"]},
            "detailed_summary": {"type": "array", "items": {"type": "string"}, "maxItems": 10,
                                 "description": "Ayrıntılı özet maddeleri (yalnız kullanıcıya özel bildirimde kullanılır)"},
        },
        "required": ["type", "broker", "tickers", "thesis", "sentiment", "confidence", "materiality", "detailed_summary"],
    },
}
REPORT_FMT = """
Yanıtını SADECE şu alanlara sahip tek bir JSON nesnesi olarak ver: {"type": "sirket|sektor|strateji", "broker": "...",
"date": "YYYY-AA-GG", "tickers": ["KOD"], "sector": "...", "rating": "AL|TUT|SAT", "target_price": sayı, "prev_target": sayı,
"currency": "TRY|USD|EUR", "estimate_changes": [{"metric": "...", "period": "...", "new": "...", "old": "...", "change": "..."}],
"top_picks": [{"ticker": "KOD", "rating": "AL", "target_price": sayı}], "model_portfolio": {"added": [], "removed": []},
"sector_view": "olumlu|nötr|olumsuz", "thesis": "...", "catalysts": ["..."], "risks": ["..."],
"sentiment": "bullish|bearish|neutral", "confidence": 0-100, "materiality": "low|medium|high", "detailed_summary": ["..."]}"""
REPORT_SYSTEM = """Sen deneyimli bir sell-side analistsin. Sana bir aracı kurum raporu (metin ya da sayfa görüntüleri)
verilecek. Rapordaki bilgileri yapılandırılmış biçimde çıkar: kurum, tarih, konu hisse(ler), tavsiye, hedef fiyat (ve
varsa önceki hedef), tahmin değişiklikleri, sektör/strateji raporlarında öne çıkan hisseler ve model portföy değişiklikleri.
Kurallar: Yalnız raporda yazanı kullan, rakam uydurma; okunamayan alanı boş bırak. "thesis" alanını KENDİ cümlelerinle,
kısa yaz; rapordan cümle kopyalama. Hisse kodlarını BIST kodu (ör. THYAO) ya da ABD sembolü olarak yaz.
"sentiment" ana hisse (şirket raporu) ya da sektör/piyasa (diğerleri) için kısa vadeli olası etkidir. Yanıt dili Türkçe."""


def _known(done_path: Path = DONE) -> set:
    try:
        return set(json.loads(done_path.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        return set()


def _remember(shas: set, done_path: Path = DONE) -> None:
    done_path.write_text(json.dumps(sorted(shas)), encoding="utf-8")


RATING_MAP = [(r"güçlü al|strong buy|endeks üstü|endeksin üzerinde|outperform|overweight|\bal\b|buy|ekle|biriktir", "AL"),
              (r"endeks altı|underperform|underweight|\bsat\b|sell|azalt", "SAT"),
              (r"endekse paralel|nötr|neutral|equal|hold|\btut\b|market perform", "TUT")]


def norm_rating(r: str | None) -> str | None:
    if not r:
        return None
    for rx, lab in RATING_MAP:
        if re.search(rx, r, re.I):
            return lab
    return None


def public_record(x: dict, sha: str, kind: str, hints: dict, published: str) -> dict:
    """research.json'a yazılacak, yayımlanabilir alanlar (ayrıntılı özet ve dosya adı yok)."""
    tps = []
    for t in x.get("top_picks") or []:
        if t.get("ticker"):
            tps.append({"t": str(t["ticker"]).upper().replace(".IS", "")[:8], "rating": norm_rating(t.get("rating")),
                        "tp": t.get("target_price")})
    return {
        "id": f"rapor-{sha[:16]}", "type": x.get("type") or kind, "broker": (x.get("broker") or hints.get("broker") or "?")[:60],
        "date": x.get("date") or hints.get("date") or published[:10], "ts": published,
        "tickers": [str(t).upper().replace(".IS", "")[:8] for t in (x.get("tickers") or [])][:12],
        "sector": (x.get("sector") or "")[:60], "rating": norm_rating(x.get("rating")),
        "tp": x.get("target_price"), "prev": x.get("prev_target"), "cur": x.get("currency") or None,
        "est": [{k: str(e.get(k) or "")[:40] for k in ("metric", "period", "new", "old", "change")} for e in (x.get("estimate_changes") or [])][:8],
        "top_picks": tps, "mp": x.get("model_portfolio") or {}, "view": x.get("sector_view") or None,
        "thesis": (x.get("thesis") or "")[:600], "catalysts": [c[:120] for c in (x.get("catalysts") or [])][:4],
        "risks": [r[:120] for r in (x.get("risks") or [])][:4], "sentiment": x.get("sentiment"),
    }


def notes_from_record(r: dict) -> list[dict]:
    """Rapor kaydından kurum notları (konsensüs ve not tablosu için)."""
    out = []
    if r["type"] == "sirket" and r["tickers"]:
        out.append({"broker": r["broker"], "t": r["tickers"][0], "name": None, "rating": r["rating"],
                    "dir": {"AL": 1, "SAT": -1, "TUT": 0}.get(r["rating"]), "tp": r["tp"], "prev": r["prev"],
                    "action": ("up" if r["tp"] and r["prev"] and r["tp"] > r["prev"] else
                               "down" if r["tp"] and r["prev"] and r["tp"] < r["prev"] else "keep"),
                    "cur": r["cur"] or "TRY", "m": "US" if r["cur"] == "USD" else "BIST", "id": r["id"] + "-n",
                    "ts": f"{r['date']}T12:00:00Z" if re.match(r"\d{4}-\d{2}-\d{2}$", r["date"] or "") else r["ts"],
                    "src": "Rapor", "url": "", "title": f"{r['broker']} raporu: {r['tickers'][0]}"})
    for i, p in enumerate(r["top_picks"]):
        out.append({"broker": r["broker"], "t": p["t"], "name": None, "rating": p["rating"] or "AL", "dir": 1,
                    "tp": p["tp"], "prev": None, "action": "set", "cur": r["cur"] or "TRY",
                    "m": "US" if r["cur"] == "USD" else "BIST", "id": f"{r['id']}-p{i}",
                    "ts": f"{r['date']}T12:00:00Z" if re.match(r"\d{4}-\d{2}-\d{2}$", r["date"] or "") else r["ts"],
                    "src": "Sektör raporu" if r["type"] == "sektor" else "Strateji raporu", "url": "",
                    "title": f"{r['broker']} {KINDS.get(r['type'], 'rapor').lower()}: öne çıkan {p['t']}"})
    for t in (r["mp"].get("added") or []):
        out.append({"broker": r["broker"], "t": str(t).upper()[:8], "name": None, "rating": "AL", "dir": 1, "tp": None,
                    "prev": None, "action": "add", "cur": "TRY", "m": "BIST", "id": f"{r['id']}-a{t}", "ts": r["ts"],
                    "src": "Strateji raporu", "url": "", "title": f"{r['broker']} model portföye ekledi: {t}"})
    for t in (r["mp"].get("removed") or []):
        out.append({"broker": r["broker"], "t": str(t).upper()[:8], "name": None, "rating": None, "dir": None, "tp": None,
                    "prev": None, "action": "remove", "cur": "TRY", "m": "BIST", "id": f"{r['id']}-r{t}", "ts": r["ts"],
                    "src": "Strateji raporu", "url": "", "title": f"{r['broker']} model portföyden çıkardı: {t}"})
    return out


def feed_item(r: dict, x: dict, watch: set) -> Item | None:
    """İzleme listesine dokunan raporlar için akış kaydı (analiz rapordan; ikinci AI çağrısı yok)."""
    tks = [t for t in [*r["tickers"], *(p["t"] for p in r["top_picks"]), *(r["mp"].get("added") or []),
                       *(r["mp"].get("removed") or [])] if t in watch]
    tks = list(dict.fromkeys(tks))
    if not tks:
        return None
    kind = KINDS.get(r["type"], "Rapor")
    tp = f", hedef {r['tp']:g} {r['cur'] or ''}".rstrip() if r["tp"] else ""
    head = (f"{r['broker']}: {r['tickers'][0] if r['tickers'] else ''} {r['rating'] or ''}{tp}".strip() if r["type"] == "sirket"
            else f"{r['broker']} {kind.lower()}{': ' + r['sector'] if r['sector'] else ''}")
    analysis = {
        "sentiment": r["sentiment"] or "neutral", "confidence": int(x.get("confidence") or 50),
        "materiality": x.get("materiality") or "medium", "horizon": "weeks", "category": kind,
        "headline_tr": head, "summary": r["thesis"], "event_label": "Rapor" if r["type"] == "sirket" else kind.split(" ")[0],
        "what": head[:90], "why": (r["catalysts"][0] if r["catalysts"] else r["thesis"][:90])[:90],
        "risk": (r["risks"][0] if r["risks"] else "")[:90], "key_points": r["catalysts"], "risks": r["risks"],
        "affected_tickers": tks, "figures": {e["metric"] + (f" ({e['period']})" if e.get("period") else ""):
                                             " → ".join(v for v in (e.get("old"), e.get("new")) if v) + (f" ({e['change']})" if e.get("change") else "")
                                             for e in r["est"] if e.get("metric")},
        "provider": x.get("_provider", "AI"), "model": x.get("_model", ""),
    }
    it = Item(id=r["id"], source=f"{r['broker']} · Rapor kutusu", source_type="report",
              market="US" if r["cur"] == "USD" else "BIST", title=head, url="", published=r["ts"],
              tickers=tks if r["type"] == "sirket" else [], lang="tr",
              extra={"private_report": {"type": r["type"]}, "no_ai": True, "analyst": r["type"] == "sirket"})
    if r["type"] != "sirket":
        analysis["affected_tickers"] = tks
    it.analysis = analysis
    return it


def telegram(r: dict, x: dict) -> bool:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    e = html.escape
    tp = f" · hedef <b>{r['tp']:g} {e(r['cur'] or '')}</b>" + (f" (önce {r['prev']:g})" if r["prev"] else "") if r["tp"] else ""
    lines = [f"📄 <b>{e(r['broker'])}</b> · {e(KINDS.get(r['type'], 'Rapor'))} · {e(r['date'] or '')}",
             f"{e(', '.join(r['tickers']) or r['sector'] or '')} {e(r['rating'] or '')}{tp}".strip()]
    if r["thesis"]:
        lines += ["", e(r["thesis"])]
    det = x.get("detailed_summary") or []
    if det:
        lines += [""] + [f"• {e(str(d))}" for d in det[:10]]
    if r["top_picks"]:
        lines += ["", "Öne çıkanlar: " + e(", ".join(p["t"] + (f" ({p['tp']:g})" if p.get("tp") else "") for p in r["top_picks"]))]
    rr = http.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat, "text": "\n".join(lines)[:4000], "parse_mode": "HTML",
                         "disable_web_page_preview": True}, retries=1)
    return rr is not None


def process(analyzer, watch: set, cfg: dict, root: Path = ROOT, done_path: Path = DONE) -> dict:
    """Yeni raporları okur. Döner: {records, notes, items, status}."""
    res = {"records": [], "notes": [], "items": [], "status": {"count": 0}}
    if not root.is_dir():
        res["status"] = {"disabled": True}
        return res
    done = _known(done_path)
    todo = [u for u in units(root) if u["sha"] not in done]
    res["status"]["waiting"] = len(todo)
    limit = int(cfg.get("max_per_run", 2))
    for u in todo[:limit]:
        if analyzer is None or not analyzer.enabled:
            break
        text, media = content(u)
        if not text and not media:
            done.add(u["sha"])
            continue
        hints = name_hints(u["path"])
        prompt = (f"Klasör: {KINDS[u['kind']]}\nDosya adı ipuçları: tarih={hints['date'] or '?'}, konu={hints['subject'] or '?'}, "
                  f"kurum={hints['broker'] or '?'}\nİzleme listesi: {', '.join(sorted(watch))}\n\n"
                  + (f"RAPOR METNİ:\n{text}" if text else "RAPOR: ekteki sayfa görüntülerinde."))
        x = analyzer.ask_json(REPORT_SYSTEM, prompt, REPORT_TOOL, REPORT_FMT, max_tokens=3000, media=media or None)
        if not isinstance(x, dict) or not x.get("broker"):
            log.warning("Rapor okunamadı (%s): AI yanıtı yok", u["kind"])
            continue                                  # AI yok/kota: sonraki turda yeniden denenir
        r = public_record(x, u["sha"], u["kind"], hints, iso(now_utc()))
        res["records"].append(r)
        res["notes"] += notes_from_record(r)
        it = feed_item(r, x, watch)
        if it:
            res["items"].append(it)
        if cfg.get("telegram", True):
            telegram(r, x)
        done.add(u["sha"])
        res["status"]["count"] += 1
    _remember(done, done_path)
    res["status"]["waiting"] = len([u for u in todo if u["sha"] not in done])
    log.info("Gizli rapor kutusu: %d okundu, %d sırada", res["status"]["count"], res["status"]["waiting"])
    return res
