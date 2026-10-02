"""Araştırma katmanı: aracı kurum notları, küresel kurum görünümleri ve haftalık sentez.

Kaynak ilkeleri (kullanım koşulları gereği):
- İş Yatırım, Garanti BBVA Yatırım, Yapı Kredi Yatırım siteleri otomatik okunmaz (koşullar / robots.txt yasaklıyor).
- Aracı kurum notları kamuya duyurulmuş haber BAŞLIKLARINDAN çıkarılır (AA, Bloomberg HT, Dünya, Foreks, Google News,
  Yahoo not değişiklikleri): kurum, hisse, tavsiye, hedef fiyat, değişim yönü. Raporun kendisi okunmaz.
- Foreks, yapay zekâ araçları için llms-analysis.txt / llms-news.txt yayımlıyor; bunlar okunur.
- J.P. Morgan "Guide to the Markets" (çeyreklik) ve BlackRock haftalık yorumu kamuya açık PDF'lerdir; AI özeti +
  bağlantı yayımlanır, belge metni yayımlanmaz.

research.json: notes (kurum notları, 120 gün), outlooks (kurum görünümleri), synthesis (günlük AI sentezi).
"""
from __future__ import annotations

import io
import json
import logging
import re
import statistics
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from . import http
from .config import DATA
from .models import UTC, Item, iso, make_id, now_utc, parse_iso
from .sources import Context
from .sources.feeds import entries_to_items, fetch_feed
from .sources.tr_official import _save_state, _state, due

log = logging.getLogger("radar.research")

STORE = DATA / "research.json"
KEEP_DAYS = 120

# ------------------------------------------------------------------ not ayrıştırma
_TR_UP = {"ı": "I", "i": "İ"}
BROKER_TAIL = (r"Yatırım|Menkul(?: Değerler)?|Securities|Invest|Capital|Research|Portföy|Bank|Bankası|"
               r"Morgan Stanley|Goldman Sachs|JPMorgan|J\.P\. Morgan|Citi(?:group)?|HSBC|UBS|Barclays|Deutsche Bank|"
               r"BofA|Bank of America|Jefferies|Wells Fargo|Bernstein|Mizuho|Raymond James|Piper Sandler|Evercore ISI|"
               r"Wedbush|Needham|Oppenheimer|KeyBanc|Truist|Cantor Fitzgerald|BNP Paribas|Societe Generale|Nomura")
BROKER = re.compile(rf"(?P<broker>(?:[A-ZÇĞİÖŞÜ][\w&.'’\-]*\s){{0,4}}?(?:{BROKER_TAIL}))", re.U)
NUM = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
TP_TR = re.compile(rf"hedef fiyat(?:ını|ı|i|ini)?\s*(?:(?P<prev>{NUM})\s*(?:TL|lira)?['’]?\s*(?:den|dan|’den|'den)\s*)?"
                   rf"(?P<tp>{NUM})\s*(?:TL|lira)", re.I)
TP_EN = re.compile(rf"(?:price target|PT)[^$]{{0,40}}?\$(?P<tp>{NUM})(?:[^$]{{0,20}}?from \$(?P<prev>{NUM}))?", re.I)
TP_EN2 = re.compile(rf"from \$(?P<prev>{NUM}) to \$(?P<tp>{NUM})", re.I)
CODE = re.compile(r"\b([A-ZÇĞİÖŞÜ]{4,6})(?=[-\s,'’.:)]|$)")
NOT_CODE = {"HİSSE", "DEĞERLENDİRMESİ", "ANALİZ", "ABD", "BIST", "VİOP", "FAVÖK", "HTTP", "NYSE", "NASDAQ", "TCMB",
            "YATIRIM", "MENKUL", "BANKASI", "HOLDİNG", "KAPSAMA", "EKONOMİ", "PİYASA", "BORSA", "GÜÇLÜ"}

RATING = [  # (desen, etiket, yön)
    (r"güçlü al|strong buy", "AL", 1), (r"endeks (?:üzeri|üstü)|endeksin üzerinde|outperform|overweight|ağırlı[kğ]\w* artır", "AL", 1),
    (r"\bal\b|\bbuy\b|\bAL\b|accumulate|biriktir", "AL", 1),
    (r"endeks (?:altı|altında)|underperform|underweight|ağırlı[kğ]\w* azalt", "SAT", -1), (r"\bsat\b|\bsell\b|\bSAT\b|reduce", "SAT", -1),
    (r"endekse paralel|endeks paralel|nötr|neutral|equal[- ]weight|market perform|\bhold\b|\btut\b|\bTUT\b", "TUT", 0),
]
ACTION = [
    (r"yükseltti|artırdı|yukarı yönlü revize|raises|raised|lifts|boosts|ups\b|upgrade", "up"),
    (r"düşürdü|indirdi|aşağı yönlü revize|lowers|lowered|cuts|cut\b|trims|downgrade", "down"),
    (r"kapsama(?:ya)? (?:al|başla)|kapsamına aldı|initiat", "init"),
    (r"korudu|sürdürdü|teyit|yineledi|maintain|reiterat|keeps", "keep"),
    (r"belirledi|açıkladı|olarak güncelledi|sets", "set"),
]


def tr_num(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    elif "." in s and len(s.split(".")[-1]) == 3:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def rating_of(text: str) -> tuple[str | None, int | None]:
    m = re.search(r"(?:[\"'“‘]([^\"'”’]{2,30})[\"'”’]\s*tavsiye|([A-Za-zÇĞİÖŞÜçğıöşü ]{2,25}?)\s+tavsiye|tavsiye\w*\s*[\"'“‘:]?\s*"
                  r"([^\"'”’,.;]{2,30})|rating[^,.;]{0,15}?\b(?:to|at)\s+([A-Za-z\- ]{3,20}))", text, re.I)
    chunks = [g for g in (m.groups() if m else ()) if g] + [text]
    for chunk in chunks:
        for rx, lab, d in RATING:
            if re.search(rx, chunk, re.I):
                return lab, d
    return None, None


UNIT = r"(?:TL|lira|dolar|\$|USD|avro|euro|€)"
TP_ANY = re.compile(rf"(?:hedef(?: fiyat\w*)?|price target|PT)[^.;:]{{0,60}}?(?:(?P<prev>{NUM})\s*{UNIT}?['’]?\s*(?:dan|den|tan|ten)\s+)?"
                    rf"(?P<tp>{NUM})\s*(?P<unit>{UNIT})|\$\s?(?P<tp2>{NUM})|(?P<tp3>{NUM})\s*(?P<unit3>{UNIT})['’]?(?:lık|lik)?\s+hedef",
                    re.I)
HINT = re.compile(r"hedef fiyat|tavsiye|kapsama|model portf|price target|upgrade|downgrade|initiat|overweight|underweight", re.I)
LEAD = re.compile(r"^(?P<b>[A-ZÇĞİÖŞÜ0-9][^,:]{1,40}?)(?:,\s+|['’](?:dan|den|tan|ten)\s+)")
SUBJ = re.compile(r"^(?P<s>.+?)(?:['’][a-zçğıöşü]{1,4}\b|\s+(?:hisse\w*|için|model portf\w*|hedef\w*|tavsiye\w*)\b|\s+[\"'“‘])",
                  re.I)


def parse_note(title: str, summary: str = "", known: dict | None = None) -> dict | None:
    """Başlıktan aracı kurum notu: kurum, hisse (kod ya da ad), tavsiye, hedef fiyat (önceki), değişim yönü.
    Not değilse None. known: {sembol: [takma adlar]} — kod geçmiyorsa şirket adından eşleştirme için."""
    text = re.sub(r"^\s*HİSSE DEĞERLENDİRMESİ\s*-\s*", "", title or "").strip()
    text = re.sub(r"\s+-\s+[^-]{2,40}$", "", text)            # Google News " - Kaynak" eki
    if not HINT.search(text):
        return None
    m = LEAD.match(text)
    if m and len(m.group("b").split()) <= 5 and not re.search(r"hedef|tavsiye|hisse|için|portföy", m.group("b"), re.I):
        broker, rest = m.group("b").strip(), text[m.end():]
    else:
        b = BROKER.search(text)
        if not b:
            return None
        broker, rest = b.group("broker").strip(" ,-"), text[b.end():].lstrip(" ,'’")
    broker = re.sub(r"^(?:ve|ile|and)\s+", "", broker)
    lead_code = re.match(r"^([A-Z]{4,6})\s+(.+)$", broker)           # "AKSEN İş Yatırım'ın model portföyüne…"
    subj_src = rest
    if lead_code and lead_code.group(1) not in NOT_CODE:
        broker = lead_code.group(2)
        subj_src = lead_code.group(1)
    elif ":" in rest[:70]:                                            # "Model Portföyünü Güncelledi: Aselsan İçin…"
        subj_src = rest.split(":", 1)[1].strip()
    sm = SUBJ.search(subj_src)
    subj = sm.group("s") if sm else subj_src[:40]
    cap = re.search(r"[A-ZÇĞİÖŞÜ].*", subj)
    subj = (cap.group(0) if cap else subj).strip(" ,-")
    paren = re.search(r"\(([A-Z]{3,6})\)", rest)
    codes = [c for c in CODE.findall(subj) if c not in NOT_CODE]
    ticker = paren.group(1) if paren else codes[0] if codes else None
    if not ticker and known:
        low = f"{subj} {rest}".lower()
        ticker = next((sy for sy, names in known.items() if any(n.lower() in low for n in names if len(n) > 2)), None)
    name = re.sub(r"\s*\([A-Z]{3,6}\)", "", subj)[:40] if not ticker else None
    if not ticker and (not name or len(name) < 2):
        return None
    blob = f"{rest} {summary or ''}"
    mt = TP_ANY.search(blob)
    tp = prev = None
    unit = ""
    if mt:
        tp = tr_num(mt.group("tp") or mt.group("tp2") or mt.group("tp3"))
        prev = tr_num(mt.group("prev"))
        unit = (mt.group("unit") or mt.group("unit3") or ("$" if mt.group("tp2") else "")).lower()
    m2 = TP_EN2.search(blob)                                  # "from $260 to $240"
    if m2:
        tp, prev, unit = tr_num(m2.group("tp")), tr_num(m2.group("prev")), "$"
    elif tp and prev is None:
        mp = re.search(rf"from \$\s?(?P<p>{NUM})|(?P<q>{NUM})\s*{UNIT}?['’]?\s*(?:dan|den|tan|ten)\b", blob, re.I)
        if mp and tr_num(mp.group("p") or mp.group("q")) not in (None, tp):
            prev = tr_num(mp.group("p") or mp.group("q"))
    rating, d = rating_of(rest)
    action = next((a for rx, a in ACTION if re.search(rx, rest, re.I)), None)
    if re.search(r"model portf\w*\s*(?:ekle|al|gir)|model portföyüne", rest, re.I):
        action, rating, d = "add", rating or "AL", 1 if d is None else d
    elif re.search(r"model portf\w*\s*(?:çıkar|den çık)", rest, re.I):
        action = "remove"
    if action in (None, "set", "keep") and tp and prev and abs(tp / prev - 1) > 0.005:
        action = "up" if tp > prev else "down"
    if not (tp or rating or action):
        return None
    cur = "USD" if unit in ("dolar", "$", "usd") else "EUR" if unit in ("avro", "euro", "€") else "TRY" if unit in ("tl", "lira") else None
    if cur is None and ticker and known and ticker in known:
        cur = "TRY"
    return {"broker": broker[:40], "t": ticker, "name": name, "rating": rating, "dir": d, "tp": tp, "prev": prev,
            "action": action, "cur": cur, "m": "BIST" if cur == "TRY" or (ticker and known and ticker in known) else
            "US" if cur == "USD" else None}


# ------------------------------------------------------------------ toplayıcılar
DEFAULT_QUERIES = ['"hedef fiyatını"', '"hedef fiyat" Yatırım hisse', '"tavsiyesini" hisse', '"model portföy" Yatırım',
                   'site:foreks.com "HİSSE DEĞERLENDİRMESİ"']
PENDING: list[dict] = []      # izleme listesi dışı notlar (akışa girmez, update() research.json'a yazar)


def note_row(n: dict, id_: str, ts: str, src: str, url: str, title: str, px: dict | None = None) -> dict:
    p = (px or {}).get(n.get("t") or "") or {}
    return {**n, "id": id_, "ts": ts, "src": (src or "").split(" · ")[0], "url": url or "", "title": (title or "")[:200],
            "px": p.get("last")}


FOREKS = ("https://www.foreks.com/llms-analysis.txt", "https://www.foreks.com/llms-news.txt")
NOTE_HINT = re.compile(r"DEĞERLENDİRME|hedef fiyat|tavsiye|model portföy|kapsama", re.I)


def parse_llms(text: str) -> list[dict]:
    """Foreks llms*.txt: '### Başlık' + '- **Tarih:** …' + '- **Özet:** …' + '- **Detay:** [..](url)'."""
    out = []
    for block in text.split("\n### ")[1:]:
        title = block.split("\n", 1)[0].strip()
        d = re.search(r"\*\*Tarih:\*\*\s*([\d\- :]+)", block)
        s = re.search(r"\*\*Özet:\*\*\s*(.+)", block)
        u = re.search(r"\]\((https?://[^)]+)\)", block)
        if not d:
            continue
        try:
            ts = datetime.strptime(d.group(1).strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=UTC) - timedelta(hours=3)
        except ValueError:
            continue
        out.append({"title": title, "summary": s.group(1).strip() if s else "", "url": u.group(1) if u else "",
                    "published": iso(ts)})
    return out


def collect_broker_notes(ctx: Context) -> list[Item]:
    """Aracı kurum notu başlıkları: Foreks llms dosyaları + Google News konu aramaları (tüm BIST, yalnız izleme
    listesi hisseleri akışa girer; diğerleri yalnız research.json'a not olarak yazılır)."""
    cfg = ctx.cfg("broker_notes")
    if not cfg.get("enabled", True) or not due("broker_notes", cfg.get("interval_min", 30)):
        return []
    known = {s.symbol: [s.name, *s.aliases] for s in ctx.stocks if s.market == "BIST"}
    raw: list[Item] = []
    for url in FOREKS:
        r = http.get(url, timeout=30, retries=1)
        if r is None:
            continue
        for e in parse_llms(r.text):
            if not NOTE_HINT.search(e["title"]) or e["published"] < iso(ctx.since):
                continue
            raw.append(Item(id=make_id("foreks", e["url"] or e["title"]), source="Foreks", source_type="news", market="BIST",
                            title=e["title"], summary=e["summary"], url=e["url"], published=e["published"], lang="tr"))
    for q in cfg.get("queries") or DEFAULT_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:2d&hl=tr&gl=TR&ceid=TR:tr"
        for it in entries_to_items(fetch_feed(url, warn_empty=False), source="Google News", source_type="news",
                                   market="BIST", since=ctx.since, lang="tr", allow_empty=True):
            raw.append(it)
    out = []
    for it in raw:
        n = parse_note(it.title, it.summary, known)
        if not n:
            continue
        if n.get("t") in known:
            it.extra["broker_note"] = n
            it.extra["analyst"] = True
            it.tickers = [n["t"]]
            out.append(it)
        else:                                            # izleme listesi dışı: akışa girmez, yalnız nota yazılır
            PENDING.append(note_row(n, it.id, it.published, it.source, it.url, it.title))
    log.info("Aracı kurum notları: izleme listesinde %d, diğer BIST %d", len(out), len(PENDING))
    return out


OUTLOOKS = [
    {"key": "jpm_gtm", "house": "J.P. Morgan AM", "title": "Guide to the Markets – U.S.", "freq_days": 7,
     "url": "https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/market-insights/guide-to-the-markets/"
            "mi-guide-to-the-markets-us.pdf", "pages": 45},
    {"key": "blk_weekly", "house": "BlackRock Investment Institute", "title": "Haftalık piyasa yorumu", "freq_days": 1,
     "page": "https://www.blackrock.com/us/individual/insights/blackrock-investment-institute/weekly-commentary",
     "pattern": r"(/us/individual/literature/market-commentary/weekly-investment-commentary[^\"'\s]*\.pdf)",
     "base": "https://www.blackrock.com", "pages": 8},
]
JUNK = re.compile(r"Guides Go to View.*?(?=CAPITAL AT RISK|FOR PUBL)|Helpful hints.*?inches|Use only BLACK.*?differentiate\.", re.S)


def _pdf_text(data: bytes, pages: int) -> tuple[str, int]:
    from pypdf import PdfReader
    i = data.find(b"%PDF")
    reader = PdfReader(io.BytesIO(data[max(i, 0):]))
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:pages])
    return JUNK.sub(" ", text), len(reader.pages)


def collect_outlooks(ctx: Context) -> list[Item]:
    """Kurum görünümleri: yeni sayı çıktığında (PDF adresi ya da Last-Modified değişince) makro kayıt + belge metni."""
    cfg = ctx.cfg("outlooks")
    if not cfg.get("enabled", True) or not due("outlooks", cfg.get("interval_min", 360)):
        return []
    st = _state()
    out = []
    for o in OUTLOOKS:
        url = o.get("url")
        if o.get("page"):
            r = http.get(o["page"], timeout=40, retries=1)
            found = sorted(set(re.findall(o["pattern"], r.text))) if r is not None else []
            if not found:
                continue
            url = o["base"] + found[-1]
        r = http.get(url, timeout=120, retries=1)
        if r is None:
            continue
        ver = f"{url}|{r.headers.get('last-modified') or len(r.content)}"
        if st.get(f"outlook_{o['key']}") == ver:
            continue
        try:
            text, n = _pdf_text(r.content, o["pages"])
        except Exception as e:
            log.warning("%s okunamadı: %s", o["key"], e)
            continue
        st[f"outlook_{o['key']}"] = ver
        out.append(Item(
            id=make_id("outlook", ver), source=f"{o['house']} · {o['title']}", source_type="macro", market="US",
            title=f"{o['house']}: {o['title']}", summary="", url=url, published=iso(now_utc()), lang="en",
            extra={"outlook": {"key": o["key"], "house": o["house"], "title": o["title"]},
                   "full_text": text[:40000], "doc": {"kind": "Kurum görünümü", "files": [{"type": "PDF", "pages": n}],
                                                     "chars": len(text)}},
        ))
    if out:
        _save_state({**_state(), **{k: v for k, v in st.items() if k.startswith("outlook_")}})
    log.info("Kurum görünümleri: %d yeni", len(out))
    return out


# ------------------------------------------------------------------ depo + sentez
def load() -> dict:
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"notes": [], "outlooks": [], "synthesis": None}


def notes_from(items: list[dict], px: dict, known: dict | None = None) -> list[dict]:
    """Akıştaki kayıtlardan kurum notları: toplayıcının ayrıştırdıkları + diğer kaynaklardaki not başlıkları
    (AA, Bloomberg HT, hisse bazlı analist araması…)."""
    out = []
    for d in items:
        ex = d.get("extra") or {}
        n = ex.get("broker_note")
        if not n and d.get("source_type") == "news" and NOTE_HINT.search(d.get("title") or ""):
            n = parse_note(d.get("title") or "", d.get("summary") or "", known)
        if n:
            out.append(note_row(n, d["id"], d["published"], d.get("source"), d.get("url"), d.get("title"), px))
    # Yahoo not değişiklikleri (ABD ağırlıklı): aynı yapıya
    for sym, p in px.items():
        for c in ((p.get("analyst") or {}).get("changes") or [])[:8]:
            if not c.get("firm"):
                continue
            lab, d = rating_of(c.get("to") or "")
            act = {"up": "up", "down": "down", "init": "init", "main": "keep", "reit": "keep"}.get(c.get("action"))
            out.append({"broker": c["firm"][:40], "t": sym, "name": None, "m": p.get("market"), "rating": lab, "dir": d, "tp": c.get("pt"),
                        "prev": c.get("pt_prev"), "action": act, "cur": p.get("currency") or "USD",
                        "id": make_id("yahoo-note", sym, c["firm"], c["date"], str(c.get("pt"))),
                        "ts": f"{c['date']}T12:00:00Z", "src": "Yahoo", "url": f"https://finance.yahoo.com/quote/{p.get('yahoo', sym)}/analysis/",
                        "title": f"{c['firm']}: {c.get('to') or ''}", "px": p.get("last")})
    return out


def consensus(notes: list[dict], sym: str, days: int = 120) -> dict | None:
    """Hisse için son notlardan: kurum başına en son tavsiye/hedef; medyan hedef, dağılım."""
    lo = iso(now_utc() - timedelta(days=days))
    latest: dict[str, dict] = {}
    for n in sorted((n for n in notes if n.get("t") == sym and n["ts"] >= lo), key=lambda n: n["ts"]):
        latest[n["broker"]] = {**latest.get(n["broker"], {}), **{k: v for k, v in n.items() if v is not None}}
    if not latest:
        return None
    tps = [n["tp"] for n in latest.values() if n.get("tp")]
    dist = {"AL": 0, "TUT": 0, "SAT": 0}
    for n in latest.values():
        if n.get("rating") in dist:
            dist[n["rating"]] += 1
    return {"n": len(latest), "median_tp": round(statistics.median(tps), 2) if tps else None, "dist": dist}


SYNTH_TOOL = {
    "name": "record_synthesis",
    "description": "Araştırma sentezini kaydet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "Tek cümle ana mesaj"},
            "summary": {"type": "string", "description": "3-5 cümle genel değerlendirme"},
            "consensus": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                          "description": "Kurumların büyük ölçüde hemfikir olduğu noktalar"},
            "divergences": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                            "description": "Kurumların ayrıştığı / çeliştiği noktalar"},
            "watchlist": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"}, "stance": {"type": "string", "enum": ["olumlu", "olumsuz", "nötr", "karışık"]},
                "why": {"type": "string", "description": "En fazla 20 kelime, dayandığı not/görünümle"}},
                "required": ["ticker", "stance", "why"]}},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "watch_next": {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                           "description": "Önümüzdeki günlerde izlenecek veri/olay"},
        },
        "required": ["headline", "summary", "consensus", "divergences", "watchlist", "risks", "watch_next"],
    },
}
SYNTH_FMT = """
Yanıtını SADECE şu alanlara sahip tek bir JSON nesnesi olarak ver: {"headline": "...", "summary": "...",
"consensus": ["..."], "divergences": ["..."], "watchlist": [{"ticker": "KOD", "stance": "olumlu|olumsuz|nötr|karışık",
"why": "..."}], "risks": ["..."], "watch_next": ["..."]}"""
SYNTH_SYSTEM = """Sen deneyimli bir strateji analistisin. Sana son günlerin aracı kurum notları (kurum, hisse, tavsiye,
hedef fiyat değişimi), küresel kurum görünümlerinin özetleri ve önemli makro gelişmeler verilecek. Görevin bunları
SENTEZLEMEK: kurumların hemfikir olduğu ve ayrıştığı noktaları, izleme listesindeki hisseler için ne anlama geldiğini
ve riskleri çıkarmak. Yalnız verilen bilgilere dayan, rakam uydurma; hangi kurum/kaynağa dayandığını belirt.
Yatırım tavsiyesi verme. Yanıt dili Türkçe."""


def synthesize(analyzer, store: dict, items: list[dict], watch: list) -> dict | None:
    lo = iso(now_utc() - timedelta(days=7))
    notes = [n for n in store["notes"] if n["ts"] >= lo]
    outl = [o for o in store["outlooks"] if o.get("ts", "") >= iso(now_utc() - timedelta(days=100))][:4]
    macro = [d for d in items if d.get("source_type") == "macro" and d.get("analysis") and d["published"] >= lo
             and d["analysis"].get("materiality") in ("medium", "high")][:15]
    if len(notes) + len(outl) + len(macro) < 3:
        return None
    lines = ["İZLEME LİSTESİ: " + ", ".join(f"{s.symbol} ({s.name})" for s in watch), "", "ARACI KURUM NOTLARI (son 7 gün):"]
    for n in sorted(notes, key=lambda n: n["ts"], reverse=True)[:60]:
        tp = f" hedef {n['tp']:g}{' (önce ' + format(n['prev'], 'g') + ')' if n.get('prev') else ''} {n.get('cur', '')}" if n.get("tp") else ""
        lines.append(f"- {n['ts'][:10]} {n['broker']} → {n.get('t') or n.get('name')}: {n.get('rating') or '?'} {n.get('action') or ''}{tp}")
    lines += ["", "KURUM GÖRÜNÜMLERİ:"]
    for o in outl:
        lines.append(f"- {o['house']} ({o['ts'][:10]}): {o.get('summary', '')} | " + " | ".join(o.get("key_points") or []))
    lines += ["", "ÖNEMLİ MAKRO GELİŞMELER:"]
    for d in macro:
        a = d["analysis"]
        lines.append(f"- {d['published'][:10]} {d.get('source', '').split(' · ')[0]}: {a.get('headline_tr') or d['title']} "
                     f"({a.get('sentiment')}, etkilenen: {', '.join(a.get('affected_tickers') or [])})")
    out = analyzer.ask_json(SYNTH_SYSTEM, "\n".join(lines)[:30000], SYNTH_TOOL, SYNTH_FMT, max_tokens=2500)
    if not out:
        return None
    out["generated"] = iso(now_utc())
    out["inputs"] = {"notes": len(notes), "outlooks": len(outl), "macro": len(macro)}
    return out


def update(items: list[dict], px: dict, analyzer, watch: list, cfg: dict) -> dict:
    """Kurum notlarını ve görünümleri research.json'a yazar; günde bir sentez üretir."""
    store = load()
    key = lambda n: (n["broker"].lower()[:10], n.get("t") or (n.get("name") or "").lower()[:12], n.get("tp"), n.get("rating"), n["ts"][:10])
    seen = {n["id"] for n in store["notes"]}
    keys = {key(n) for n in store["notes"]}
    added = 0
    known = {s.symbol: [s.name, *s.aliases] for s in watch}
    for n in [*notes_from(items, px, known), *PENDING]:
        if n["id"] in seen or key(n) in keys:          # aynı not birden çok kaynaktan gelebilir
            continue
        store["notes"].append(n)
        seen.add(n["id"])
        keys.add(key(n))
        added += 1
    PENDING.clear()
    lo = iso(now_utc() - timedelta(days=KEEP_DAYS))
    store["notes"] = sorted((n for n in store["notes"] if n["ts"] >= lo), key=lambda n: n["ts"], reverse=True)[:3000]
    oids = {o["id"] for o in store["outlooks"]}
    for d in items:
        o = (d.get("extra") or {}).get("outlook")
        a = d.get("analysis")
        if o and a and d["id"] not in oids:
            store["outlooks"].insert(0, {"id": d["id"], "ts": d["published"], "url": d.get("url"), **o,
                                         "summary": a.get("summary"), "key_points": a.get("key_points") or [],
                                         "risks": a.get("risks") or [], "figures": a.get("figures") or {},
                                         "sentiment": a.get("sentiment")})
    store["outlooks"] = store["outlooks"][:30]
    syn = store.get("synthesis") or {}
    hours = float(cfg.get("synthesis_hours", 20))
    if analyzer is not None and analyzer.enabled and (not syn or now_utc() - parse_iso(syn["generated"]) > timedelta(hours=hours)):
        new = synthesize(analyzer, store, items, watch)
        if new:
            store["synthesis"] = new
    store["consensus"] = {s.symbol: c for s in watch if (c := consensus(store["notes"], s.symbol))}
    store["generated"] = iso(now_utc())
    STORE.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Araştırma: %d yeni not, %d not, %d görünüm", added, len(store["notes"]), len(store["outlooks"]))
    return {"added": added, "notes": len(store["notes"]), "outlooks": len(store["outlooks"])}
