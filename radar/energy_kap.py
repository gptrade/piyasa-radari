"""KAP'tan enerji yatırım olayları: devreye alma, kapasite artışı, üretim lisansı / önlisans, ÇED, YEKA, sözleşme.

GEM santral verisi yılda iki kez güncellendiği için arada olanları borsa şirketlerinin KAP bildirimlerinden yakalarız.
- Kapsam: KAP sektörü "Elektrik Gaz ve Buhar" olan şirketler + energy_groups.yml'deki borsa kodları (ilk dolum ve
  sonrası şirket bazında), ayrıca tüm KAP'ta özetinde güçlü enerji ifadesi geçen bildirimler (otoprodüktörler için).
- Bildirim özeti süzülür, metni okunur; olaylar AI ile (ücretsiz kotalı hafif model) yapılandırılır, AI yoksa kurallarla.
Çıktı: site/data/enerji/kap_events.json (enerji dalında kalıcı).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time

from . import http
from .config import DATA
from .documents import kap_body

log = logging.getLogger("radar.energy_kap")

LIST_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
DETAIL_URL = "https://www.kap.org.tr/tr/Bildirim/{idx}"
HEADERS = {"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"}
STATE = DATA / "enerji" / "kap_events.json"
START = dt.date(2026, 1, 1)                 # ilk dolum: GEM izleyicilerinin (Şubat–Eylül 2026) öncesinden başla
GAP = 1.2

SKIP_SUBJECT = re.compile(r"devre kesici|geri alın|pay alım satım|finansal rapor|faaliyet raporu|genel kurul|sermaye piyasası aracı|"
                          r"kar payı|kâr payı|genel bilgi formu|kayıtlı sermaye|ihraç belgesi|sorumluluk beyan|bağımsız denetim|"
                          r"kurumsal yönetim|sürdürülebilirlik|esas sözleşme|izahname|fiyat tespit|borsa dışı|yatırımcı tazmin", re.I)
ENERGY = re.compile(r"\b(GES|RES|HES|JES|BES|DGKÇS|MWe?|MWp|MWm|MWh)\b|santral|depolama|ÇED|çevresel etki|önlisans|ön lisans|"
                    r"üretim lisans|lisans tadil|YEKA|kurulu güç|kapasite artı|geçici kabul|kabul işlem|üretime geç|devreye al|"
                    r"güneş enerji|rüzgar enerji|rüzgâr enerji|hidroelektrik|jeotermal|biyokütle|hibrit|EPDK", re.I)
STRONG = re.compile(r"\b(GES|RES|HES|JES)\b|güneş enerji(si)? santral|rüzgar enerji(si)? santral|rüzgâr enerji(si)? santral|"
                    r"hidroelektrik santral|jeotermal enerji santral|depolamalı|üretim lisans|önlisans|ön lisans|YEKA", re.I)

TYPES = ["devreye_alma", "kapasite_artisi", "lisans", "onlisans", "ced", "yeka", "yatirim_karari", "sozlesme", "satin_alma", "satis", "diger"]
TYPE_NAMES = {"devreye_alma": "Devreye alma", "kapasite_artisi": "Kapasite artışı", "lisans": "Üretim lisansı", "onlisans": "Önlisans",
              "ced": "ÇED", "yeka": "YEKA", "yatirim_karari": "Yatırım kararı", "sozlesme": "Sözleşme (EPC/tedarik)",
              "satin_alma": "Satın alma", "satis": "Satış", "diger": "Diğer"}
SRCS = ["gunes", "ruzgar", "hidro", "jeotermal", "dogalgaz", "komur", "biyokutle", "depolama", "hibrit", "diger"]

SYSTEM = ("Sen Türkiye elektrik piyasasını izleyen bir analistsin. Sana bir KAP bildirimi verilecek. Bildirimdeki enerji santrali "
          "yatırım olaylarını çıkar. Yalnızca metinde açıkça yazanı kullan; MW değerini uydurma, yoksa null bırak.")
TOOL = {"name": "record_energy_events", "description": "KAP bildirimindeki santral olayları",
        "input_schema": {"type": "object", "properties": {"events": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": TYPES}, "plant": {"type": "string"}, "source": {"type": "string", "enum": SRCS},
            "mw": {"type": ["number", "null"]}, "mwp": {"type": ["number", "null"]}, "storage_mw": {"type": ["number", "null"]},
            "province": {"type": ["string", "null"]}, "country": {"type": "string"}, "note": {"type": "string"}},
            "required": ["type", "plant", "source"]}}}, "required": ["events"]}}
FMT = """
Yanıtın SADECE şu JSON olsun: {"events": [{"type": "devreye_alma|kapasite_artisi|lisans|onlisans|ced|yeka|yatirim_karari|sozlesme|satin_alma|satis|diger",
"plant": "santral adı", "source": "gunes|ruzgar|hidro|jeotermal|dogalgaz|komur|biyokutle|depolama|hibrit|diger",
"mw": elektriksel/mekanik kurulu güç MW (MWe/MWm) ya da null, "mwp": güneşte DC MWp ya da null, "storage_mw": depolama MW ya da null,
"province": "il" ya da null, "country": "TR" ya da ülke, "note": "tek cümle Türkçe özet"}]}
Kurallar: devreye_alma = geçici kabul / işletmeye alma / üretime başlama; kapasite_artisi = mevcut santrale ek kapasite (lisans tadili onayı
dahil); lisans = EPDK üretim lisansı; onlisans = önlisans; ced = ÇED başvurusu/olumlu kararı/gerekli değildir kararı; yeka = YEKA yarışması.
Enerji santraliyle ilgisi yoksa {"events": []} döndür."""


def _post(body: dict):
    r = http.post(LIST_URL, json=body, headers=HEADERS, timeout=60)
    if r is None:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def candidate(row: dict, energy_codes: set[str]) -> bool:
    subj = row.get("subject") or ""
    if SKIP_SUBJECT.search(subj):
        return False
    text = f"{row.get('summary') or ''} {subj}"
    codes = {c.strip().upper() for c in str(row.get("stockCodes") or row.get("relatedStocks") or "").replace(";", ",").split(",") if c.strip()}
    return bool(ENERGY.search(text)) if codes & energy_codes else bool(STRONG.search(text))


_NUM = r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"


def _num(s: str) -> float | None:
    s = s.strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def rule_events(text: str, summary: str) -> list[dict]:
    """AI yoksa: türü anahtar kelimeden, MW'ı metindeki ilk MWe/MWm/MW değerinden çıkar."""
    t = f"{summary}\n{text[:4000]}"
    low = t.lower()
    typ = ("devreye_alma" if re.search(r"geçici kabul|kabul işlem|üretime geç|işletmeye alın|devreye alın", low) else
           "kapasite_artisi" if re.search(r"kapasite artı|lisans tadil", low) else
           "onlisans" if re.search(r"önlisans|ön lisans", low) else
           "lisans" if "lisans" in low else "ced" if re.search(r"çed|çevresel etki", low) else
           "yeka" if "yeka" in low else "sozlesme" if "sözleşme" in low else "diger")
    src = ("gunes" if re.search(r"\bges\b|güneş", low) else "ruzgar" if re.search(r"\bres\b|rüzg", low) else
           "hidro" if re.search(r"\bhes\b|hidroelektrik|baraj", low) else "jeotermal" if re.search(r"\bjes\b|jeotermal", low) else
           "depolama" if "depolama" in low else "dogalgaz" if re.search(r"doğal ?gaz|kombine çevrim", low) else "diger")
    mw = mwp = None
    for m in re.finditer(_NUM + r"\s*(MWe|MWm|MWp|MW)\b", t):
        v = _num(m.group(1))
        if v is None or v <= 0 or v > 5000:
            continue
        if m.group(2) == "MWp":
            mwp = mwp or v
        else:
            mw = mw or v
    plant = re.search(r"([A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü\-]+(?:\s+[A-ZÇĞİÖŞÜ][\wÇĞİÖŞÜçğıöşü\-]+){0,4}\s+(?:Depolamalı\s+)?(?:GES|RES|HES|JES|Güneş Enerji(?:si)? Santrali|Rüzgar Enerji(?:si)? Santrali))", t)
    return [{"type": typ, "plant": plant.group(1) if plant else summary[:80], "source": src, "mw": mw, "mwp": mwp,
             "storage_mw": None, "province": None, "country": "TR", "note": summary[:160], "_rule": True}]


def clean_events(evs) -> list[dict]:
    out = []
    for e in evs if isinstance(evs, list) else []:
        if not isinstance(e, dict) or e.get("type") not in TYPES:
            continue
        for k in ("mw", "mwp", "storage_mw"):
            v = e.get(k)
            e[k] = float(v) if isinstance(v, (int, float)) and 0 < v < 20000 else None
        e["source"] = e.get("source") if e.get("source") in SRCS else "diger"
        e["country"] = (e.get("country") or "TR").strip()[:20]
        e["plant"] = str(e.get("plant") or "").strip()[:120]
        e["note"] = str(e.get("note") or "").strip()[:240]
        out.append(e)
    return out


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"members_done": {}, "scanned_to": None, "items": []}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    st["items"].sort(key=lambda x: x.get("date") or "", reverse=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def energy_members(universe: dict, extra_codes: set[str]) -> list[dict]:
    return [m for m in universe.get("members") or [] if m.get("sector") == "ELEKTRİK GAZ VE BUHAR" or m.get("code") in extra_codes]


def _row_date(row) -> str:
    try:
        return dt.datetime.strptime(row["publishDate"].strip()[:10], "%d.%m.%Y").date().isoformat()
    except (KeyError, ValueError):
        return ""


def update(universe: dict, extra_codes: set[str], analyzer=None, today: dt.date | None = None,
           max_bodies: int = 60, budget_s: float = 900) -> dict:
    """Yeni aday bildirimleri bulur, okur ve olayları çıkarır. Döner: durum (kap_events.json içeriği)."""
    t0 = time.monotonic()
    today = today or dt.date.today()
    st = load_state()
    seen = {it["idx"] for it in st["items"]} | set(st.get("skipped") or [])
    members = energy_members(universe, extra_codes)
    codes = {m["code"] for m in members}
    rows = []
    # 1) şirket bazında ilk dolum (yıllık pencere)
    for m in members:
        if st["members_done"].get(m["code"]) or time.monotonic() - t0 > budget_s / 2:
            continue
        got = _post({"fromDate": START.isoformat(), "toDate": today.isoformat(), "mkkMemberOidList": [m["oid"]], "subjectList": []})
        time.sleep(GAP)
        if got is None:
            continue
        rows += got
        st["members_done"][m["code"]] = today.isoformat()
    # 2) son günler: tüm KAP (yeni bildirimler + otoprodüktörler)
    frm = dt.date.fromisoformat(st["scanned_to"]) if st.get("scanned_to") else today - dt.timedelta(days=3)
    d = max(frm - dt.timedelta(days=1), today - dt.timedelta(days=30))
    while d <= today:
        got = _post({"fromDate": d.isoformat(), "toDate": d.isoformat(), "mkkMemberOidList": [], "subjectList": []})
        time.sleep(GAP)
        if got is not None:
            rows += got
            st["scanned_to"] = d.isoformat()
        d += dt.timedelta(days=1)
    cands, ids = [], set()
    for row in rows:
        idx = row.get("disclosureIndex")
        if not idx or idx in seen or idx in ids or not candidate(row, codes):
            continue
        ids.add(idx)
        cands.append(row)
    cands.sort(key=_row_date, reverse=True)
    log.info("KAP enerji: %d satır, %d yeni aday", len(rows), len(cands))
    done = 0
    for row in cands:
        if done >= max_bodies or time.monotonic() - t0 > budget_s:
            break
        idx = row["disclosureIndex"]
        r = http.get(DETAIL_URL.format(idx=idx), timeout=60, retries=1)
        time.sleep(GAP)
        if r is None:
            continue
        done += 1
        summary = (row.get("summary") or row.get("subject") or "").strip()
        text = kap_body(r.text, row.get("kapTitle"))[:7000]
        events, by = None, "kural"
        if analyzer is not None and getattr(analyzer, "providers", None):
            x = analyzer.ask_json(SYSTEM, f"Şirket: {row.get('kapTitle')}\nKonu: {row.get('subject')}\nÖzet: {summary}\n\nMETİN:\n{text}",
                                  TOOL, FMT, max_tokens=900, light=True)
            if isinstance(x, dict) and isinstance(x.get("events"), list):
                events, by = clean_events(x["events"]), f"{x.get('_provider')}:{x.get('_model')}"
            elif getattr(analyzer, "last_blocked", False):
                continue                                         # kota: sonraki çalıştırmada yeniden dene
        if events is None:
            events = clean_events(rule_events(text, summary))
        codes_row = [c.strip().upper() for c in str(row.get("stockCodes") or row.get("relatedStocks") or "").replace(";", ",").split(",") if c.strip()]
        if not events:
            st.setdefault("skipped", []).append(idx)
            continue
        st["items"].append({"idx": idx, "date": _row_date(row), "tickers": codes_row, "company": row.get("kapTitle"),
                            "subject": row.get("subject"), "summary": summary, "url": DETAIL_URL.format(idx=idx),
                            "events": events, "by": by})
    st["skipped"] = (st.get("skipped") or [])[-3000:]
    st["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    save_state(st)
    log.info("KAP enerji: %d bildirim okundu, toplam %d kayıt", done, len(st["items"]))
    return st
