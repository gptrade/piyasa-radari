"""Türkiye resmi kaynakları: TÜİK, BDDK, Resmi Gazete, Borsa İstanbul duyuruları, SPK basın duyuruları,
Hazine (haber araması).

Hepsi herkese açık liste sayfalarından okunur; ayrıntı sayfası indirilmez (başlık + bağlantı + tarih).
Market geneli duyurular "macro" türünde akışa düşer ve AI değerlendirir; bir hisse adı geçiyorsa
"regulator" türünde o hisseye bağlanır. Her kaynağın en sık çekim aralığı ayarlanabilir
(data/source_state.json); boru hattı 15 dakikada bir çalıştığı için bundan sık çekim olmaz.
"""
from __future__ import annotations

import html as htmlmod
import json
import logging
import re
import ssl
import tempfile
from datetime import datetime, timedelta
from urllib.parse import quote_plus, urljoin
from zoneinfo import ZoneInfo

from .. import http
from ..config import DATA
from ..models import Item, iso, make_id, now_utc, parse_iso
from . import Context
from .feeds import entries_to_items, fetch_feed, parse_tr_date

log = logging.getLogger("radar.tr")

IST = ZoneInfo("Europe/Istanbul")
STATE_FILE = DATA / "source_state.json"

TUIK_URL = "https://www.turkiye.gov.tr/tuik-haber-bulteni"
BDDK_LISTS = {"Basın duyurusu": "https://www.bddk.org.tr/Duyuru/Liste/39",
              "Mevzuat duyurusu": "https://www.bddk.org.tr/Duyuru/Liste/40"}
BDDK_INTERMEDIATE = "http://secure.globalsign.com/cacert/gsrsaovsslca2018.crt"
RG_URL = "https://www.resmigazete.gov.tr/eskiler/{d:%Y}/{d:%m}/{d:%Y%m%d}.htm"
BIST_ANN_URL = "https://www.borsaistanbul.com/en/announcement"
SPK_PRESS_URL = "https://spk.gov.tr/duyurular/basin-duyurulari/{year}"

# TÜİK: piyasayı ilgilendiren bültenler (diğerleri — hayvancılık, kültür vb. — akışa girmez)
TUIK_KEYS = ["tüketici fiyat", "enflasyon", "üretici fiyat", "işsizlik", "işgücü", "gayrisafi yurt içi hasıla", "gsyh",
             "büyüme", "sanayi üretim", "dış ticaret", "ihracat", "ithalat", "güven endeksi", "konut satış",
             "kapasite kullanım", "perakende satış", "ciro", "bütçe", "devlet açığı", "cari", "ödemeler dengesi"]
# Resmi Gazete: piyasaya dokunabilecek düzenlemeler
RG_KEYS = ["vergi", "ötv", "kdv", "harç", "gümrük", "merkez bankası", "sermaye piyasası", "bankacılık", "bddk", "kambiyo",
           "türk parasının kıymetini", "ihracat", "ithalat", "elektrik piyasası", "doğal gaz piyasası", "enerji piyasası",
           "akaryakıt", "asgari ücret", "tarife", "faiz", "kredi", "borçlanma", "hazine", "özelleştirme", "rekabet kurulu",
           "yatırım teşvik", "yatırımlarda devlet yardım", "devlet yardımları", "kamu ihale", "borsa", "halka arz",
           "sigortacılık", "bireysel emeklilik", "finansal kiralama", "faktoring", "kripto", "varlık barışı",
           "tasarruf tedbir", "döviz", "menkul kıymet", "kaynak kullanımını destekleme"]
RG_SKIP = ["kamulaştır", "üniversite", "atama", "taşınmaz"]       # arazi kamulaştırma, akademik, atama kararları
BIST_SKIP = ["opening bell", "gong"]
HAZINE_QUERIES = ['"iç borçlanma" Hazine', 'Hazine "ihalesinde" "milyar lira"', '"Hazine ve Maliye Bakanlığı" ihale tahvil']
HAZINE_MUST = ["iç borç", "ihale", "borçlanma", "tahvil ihracı", "kira sertifikası", "itfa"]
HAZINE_SKIP = ["abd", "amerikan", "fed ", "treasury", "dolar endeksi", "döviz fiyat"]


# ------------------------------------------------------------------ ortak
def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def due(name: str, minutes: float) -> bool:
    """Kaynak en son `minutes` dakika önce çekildiyse False. Çekim zamanı burada işaretlenir."""
    st = _state()
    last = st.get(name)
    now = now_utc()
    if last and now - parse_iso(last) < timedelta(minutes=minutes):
        return False
    st[name] = iso(now)
    _save_state(st)
    return True


def _clean(s: str) -> str:
    s = htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip(" –-")


def tr_cap(s: str) -> str:
    """'CUMHURBAŞKANI KARARLARI' → 'Cumhurbaşkanı kararları' (Türkçe İ/ı doğru)."""
    low = s.replace("I", "ı").replace("İ", "i").lower()
    return (low[:1].replace("i", "İ").replace("ı", "I").upper() + low[1:]) if low else s


def _has(text: str, keys: list[str]) -> bool:
    t = text.replace("İ", "i").replace("I", "ı").lower()
    return any(k in t for k in keys)


def _item(*, source: str, title: str, url: str, published: datetime, ctx: Context, issuer: str,
          lang: str = "tr", summary: str = "", market: str = "BIST", extra: dict | None = None) -> Item:
    tickers = ctx.matcher.match(title, market=market) if ctx.matcher else []
    return Item(id=make_id("tr", issuer, url, title), source=source, source_type="regulator" if tickers else "macro",
                market=market, title=title, summary=summary or title, url=url, published=iso(published),
                tickers=list(tickers), lang=lang, extra={"issuer": issuer, **(extra or {})})


def _window(published: datetime, days: int) -> bool:
    return published >= now_utc() - timedelta(days=days)


# ------------------------------------------------------------------ TÜİK
_TUIK_ROW = re.compile(r"<tr>\s*<td>(\d{2}/\d{2}/\d{4})</td>\s*<td>(.*?)</td>\s*<td>.*?href=\"([^\"]+)\"", re.S)


def parse_tuik(text: str) -> list[dict]:
    """turkiye.gov.tr TÜİK haber bülteni tablosu: [{date, title, url}]"""
    out = []
    for d, title, url in _TUIK_ROW.findall(text):
        dd, mm, yy = map(int, d.split("/"))
        out.append({"date": datetime(yy, mm, dd, 10, 0, tzinfo=IST), "title": _clean(title), "url": htmlmod.unescape(url)})
    return out


def collect_tuik(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("tuik")
    if not cfg.get("enabled", True) or not due("tuik", cfg.get("interval_min", 15)):
        return []
    r = http.get(TUIK_URL)
    if r is None:
        return []
    keys = cfg.get("keywords") or TUIK_KEYS
    out = []
    for row in parse_tuik(r.text):
        if not _window(row["date"], 3) or not _has(row["title"] + " " + row["url"], keys):
            continue
        hi = _has(row["title"] + row["url"], ["tüketici fiyat", "enflasyon", "hasıla", "işsizlik"])
        out.append(_item(source="TÜİK", title=row["title"], url=row["url"], published=row["date"], ctx=ctx,
                         issuer="TÜİK", extra={"high_impact": hi}))
    log.info("TÜİK: %d bülten", len(out))
    return out


# ------------------------------------------------------------------ BDDK
_bddk_bundle: str | None = None


def _bddk_verify() -> str | bool:
    """BDDK sunucusu ara sertifikayı göndermiyor: GlobalSign'ın herkese açık ara sertifikası güvenilen
    kök listesine eklenir (doğrulama kapatılmaz)."""
    global _bddk_bundle
    if _bddk_bundle:
        return _bddk_bundle
    try:
        import certifi
        r = http.get(BDDK_INTERMEDIATE, timeout=20)
        if r is None:
            return True
        pem = ssl.DER_cert_to_PEM_cert(r.content)
        f = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
        f.write(open(certifi.where(), encoding="utf-8").read() + "\n" + pem)
        f.close()
        _bddk_bundle = f.name
        return _bddk_bundle
    except Exception as e:                                            # noqa: BLE001
        log.warning("BDDK ara sertifikası alınamadı: %s", e)
        return True


_BDDK_ROW = re.compile(r'<a href="(/Duyuru/Detay/\d+)">.*?class="gorunenTarih">(\d{2}\.\d{2}\.\d{4})</span>(.*?)</span>', re.S)


def parse_bddk(text: str) -> list[dict]:
    out = []
    for href, d, title in _BDDK_ROW.findall(text):
        dd, mm, yy = map(int, d.split("."))
        out.append({"date": datetime(yy, mm, dd, 12, 0, tzinfo=IST), "title": _clean(title),
                    "url": urljoin("https://www.bddk.org.tr", href)})
    return out


def collect_bddk(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("bddk")
    if not cfg.get("enabled", True) or not due("bddk", cfg.get("interval_min", 30)):
        return []
    verify = _bddk_verify()
    out = []
    for kind, url in BDDK_LISTS.items():
        try:
            r = http._session.get(url, headers={"User-Agent": http.DEFAULT_UA}, timeout=40, verify=verify)
        except Exception as e:                                        # noqa: BLE001
            http.note_failure(url, type(e).__name__)
            continue
        if r.status_code != 200:
            http.note_failure(url, f"HTTP {r.status_code}")
            continue
        for row in parse_bddk(r.text)[:20]:
            if _window(row["date"], 7):
                out.append(_item(source=f"BDDK · {kind}", title=row["title"], url=row["url"], published=row["date"],
                                 ctx=ctx, issuer="BDDK"))
    log.info("BDDK: %d duyuru", len(out))
    return out


# ------------------------------------------------------------------ Resmi Gazete
_RG_LINK = re.compile(r'<a href="([^"]+\.(?:pdf|htm))"[^>]*>(.*?)</a>', re.S | re.I)
_RG_HEAD = re.compile(r"<u>\s*<font[^>]*>(.*?)</font>\s*</u>", re.S | re.I)


def parse_resmi_gazete(text: str, base: str) -> list[dict]:
    """Günün sayısı: [{section, title, url}] (ilan bölümü hariç)."""
    out, section = [], ""
    pos = 0
    tokens = sorted([(m.start(), "h", m) for m in _RG_HEAD.finditer(text)] + [(m.start(), "a", m) for m in _RG_LINK.finditer(text)],
                    key=lambda x: x[0])
    for _, kind, m in tokens:
        if kind == "h":
            section = _clean(m.group(1))
            continue
        if "İLAN" in section.upper():
            break
        title = _clean(m.group(2))
        if len(title) < 15:
            continue
        out.append({"section": section, "title": title, "url": urljoin(base, m.group(1))})
    return out


def collect_resmi_gazete(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("resmi_gazete")
    if not cfg.get("enabled", True):
        return []
    today = now_utc().astimezone(IST)
    st = _state()
    if st.get("rg_done") == today.date().isoformat() or not due("rg_try", cfg.get("interval_min", 60)):
        return []
    url = RG_URL.format(d=today)
    r = http.get(url)
    if r is None:
        return []
    text = r.content.decode("cp1254", "replace") if b"charset=utf-8" not in r.content[:2000].lower() else r.text
    rows = parse_resmi_gazete(text, url)
    if not rows:
        return []
    st = _state()
    st["rg_done"] = today.date().isoformat()
    _save_state(st)
    keys = cfg.get("keywords") or RG_KEYS
    pub = today.replace(hour=0, minute=5, second=0, microsecond=0)
    out = [_item(source=f"Resmi Gazete · {tr_cap(row['section'])}" if row["section"] else "Resmi Gazete",
                 title=row["title"], url=row["url"], published=pub, ctx=ctx, issuer="Resmi Gazete")
           for row in rows if _has(row["title"], keys) and not _has(row["title"], RG_SKIP)]
    log.info("Resmi Gazete: %d / %d düzenleme ilgili", len(out), len(rows))
    return out


# ------------------------------------------------------------------ Borsa İstanbul duyuruları
_BIST_CARD = re.compile(r'<a href="(/en/announcement/\d+/[^"]+)"[^>]*>.*?<div class="date">\s*([^<]+)</div>\s*<div class="title">(.*?)</div>', re.S)
_EN_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                           "september", "october", "november", "december"], 1)}


def parse_bist_announcements(text: str) -> list[dict]:
    out = []
    for href, d, title in _BIST_CARD.findall(text):
        p = d.strip().split()
        try:
            dt = datetime(int(p[2]), _EN_MONTHS[p[1].lower()], int(p[0]), 18, 0, tzinfo=IST)
        except (IndexError, KeyError, ValueError):
            continue
        out.append({"date": dt, "title": _clean(title), "url": urljoin("https://www.borsaistanbul.com", href)})
    return out


def collect_bist_announcements(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("bist_announcements")
    if not cfg.get("enabled", True) or not due("bist_ann", cfg.get("interval_min", 15)):
        return []
    r = http.get(BIST_ANN_URL)
    if r is None:
        return []
    out = []
    for row in parse_bist_announcements(r.text):
        if not _window(row["date"], 5) or _has(row["title"], BIST_SKIP):
            continue
        out.append(_item(source="Borsa İstanbul · Duyuru", title=row["title"], url=row["url"], published=row["date"],
                         ctx=ctx, issuer="Borsa İstanbul", lang="en"))
    log.info("Borsa İstanbul duyuruları: %d", len(out))
    return out


# ------------------------------------------------------------------ SPK basın duyuruları
_SPK_ROW = re.compile(r'<a href="(/duyurular/basin-duyurulari/\d{4}/[^"]+)" class="link">.*?<div class="liste-tarih">([^<]+)</div>'
                      r'.*?<div class="liste-baslik">(.*?)</div>', re.S)


def parse_spk_press(text: str) -> list[dict]:
    out = []
    for href, d, title in _SPK_ROW.findall(text):
        dt = parse_tr_date(d)
        if dt:
            out.append({"date": dt.replace(hour=12), "title": _clean(title), "url": urljoin("https://spk.gov.tr", href)})
    return out


def collect_spk_press(ctx: Context) -> list[Item]:
    cfg = ctx.cfg("spk_press")
    if not cfg.get("enabled", True) or not due("spk_press", cfg.get("interval_min", 30)):
        return []
    r = http.get(SPK_PRESS_URL.format(year=now_utc().astimezone(IST).year))
    if r is None:
        return []
    out = [_item(source="SPK · Basın duyurusu", title=row["title"], url=row["url"], published=row["date"], ctx=ctx, issuer="SPK")
           for row in parse_spk_press(r.text)[:15] if _window(row["date"], 7)]
    log.info("SPK duyuruları: %d", len(out))
    return out


# ------------------------------------------------------------------ Hazine (haber araması)
def collect_hazine(ctx: Context) -> list[Item]:
    """Hazine ve Maliye Bakanlığı sitesi yalnız JavaScript ile çalışıyor; ihale sonuçları/takvimi haber
    aramasıyla izlenir (AA, Bloomberg HT vb.)."""
    cfg = ctx.cfg("hazine")
    if not cfg.get("enabled", True) or not due("hazine", cfg.get("interval_min", 30)):
        return []
    out = []
    for q in cfg.get("queries") or HAZINE_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:3d&hl=tr&gl=TR&ceid=TR:tr"
        for it in entries_to_items(fetch_feed(url, warn_empty=False), source="Google News", source_type="macro",
                                   market="BIST", since=ctx.since, lang="tr", allow_empty=True, limit=4,
                                   extra={"issuer": "Hazine"}):
            if not _has(it.title, HAZINE_MUST) or _has(it.title, HAZINE_SKIP) or "instagram" in it.source.lower():
                continue
            it.source = it.source.replace(" · Google News", "") + " · Hazine"
            out.append(it)
    log.info("Hazine haberleri: %d", len(out))
    return out
