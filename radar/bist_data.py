"""Borsa İstanbul resmi veri dosyaları (borsaistanbul.com, ücretsiz gün sonu dosyaları).

- Günlük bülten  /data/thb/YYYY/AA/thbYYYYAAGG1.zip : hisse bazında açığa satış hacmi, brüt takas (tedbir) ve
  açığa satış izni bayrakları. İzleme listesindeki BIST hisseleri için günlük özet data/bist_flows.json'da birikir.
- Genel kurullar /data/gk/gkYYYY.zip : toplantı tarihi, saati, türü, gündemdeki hak kullanımları, KAP bağlantısı.
Yalnız izleme listesi hisselerinin türetilmiş göstergeleri saklanır; ham dosyalar yeniden yayımlanmaz.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import http
from .config import DATA
from .models import Item, iso, make_id, now_utc, parse_iso

log = logging.getLogger("radar.bist")

BASE = "https://www.borsaistanbul.com"
FLOWS = DATA / "bist_flows.json"
GK_CACHE = DATA / "bist_gk.json"
IST = ZoneInfo("Europe/Istanbul")
KEEP_DAYS = 70          # takvim günü; ~45 seans
AVG_N = 20


def _get(url: str, timeout: int = 40) -> bytes | None:
    """Yayımlanmamış gün dosyası 404 döner; bu normaldir, kaynak hatası sayılmaz."""
    try:
        r = http._session.get(url, headers={"User-Agent": http.DEFAULT_UA}, timeout=timeout)
    except Exception as e:                                  # noqa: BLE001
        http.note_failure(url, type(e).__name__)
        return None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        http.note_failure(url, f"HTTP {r.status_code}")
        return None
    return r.content


def _unzip_first(blob: bytes) -> tuple[str, bytes] | None:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return None
    names = [n for n in z.namelist() if not n.startswith("__MACOSX") and not n.endswith("/")]
    return (names[0], z.read(names[0])) if names else None


def _f(v) -> float:
    try:
        return float(str(v).replace(",", ".")) if str(v).strip() not in ("", "None") else 0.0
    except ValueError:
        return 0.0


def parse_bulletin(text: str) -> dict[str, dict]:
    """thb CSV (';' ayraçlı, 1. satır Türkçe 2. satır İngilizce başlık) → {SEMBOL: göstergeler}."""
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    if len(rows) < 3:
        return {}
    hdr = [h.strip().upper() for h in rows[0]]
    ix = {h: i for i, h in enumerate(hdr)}

    def col(r, name):
        i = ix.get(name)
        return r[i] if i is not None and i < len(r) else ""
    out = {}
    for r in rows[2:]:
        code = col(r, "ISLEM  KODU") or col(r, "ISLEM KODU")
        if not code.endswith(".E"):
            continue
        sym = code[:-2]
        value = _f(col(r, "TOPLAM ISLEM HACMI"))
        short_v = _f(col(r, "ACIGA SATIS ISLEM HACMI"))
        out[sym] = {
            "date": col(r, "TARIH"), "close": _f(col(r, "KAPANIS FIYATI")), "chg": _f(col(r, "DEGISIM (%)")),
            "value": value, "short_value": short_v, "short_vol": _f(col(r, "ACIGA SATIS ISLEM ADEDI")),
            "short_pct": round(short_v / value * 100, 2) if value else 0.0,
            "close_sess_pct": round(_f(col(r, "KAPANIS SEANSI ISLEM HACMI")) / value * 100, 2) if value else 0.0,
            "gross": col(r, "BRUT TAKAS").strip() == "1", "short_ok": col(r, "ACIGA SATIS").strip() == "1",
            "bist100": col(r, "BIST 100 ENDEKS").strip() == "1",
        }
    return out


def _decode(b: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def bulletin_url(d: date) -> str:
    return f"{BASE}/data/thb/{d:%Y}/{d:%m}/thb{d:%Y%m%d}1.zip"


def update_flows(stocks: list, max_fetch: int = 25) -> dict:
    """Eksik seans bültenlerini indir, izleme listesi BIST hisselerinin günlük özetini biriktir."""
    syms = {s.symbol for s in stocks if s.market == "BIST"}
    try:
        store = json.loads(FLOWS.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        store = {}
    days: dict = store.get("days", {})
    tried: dict = store.get("tried", {})
    now = now_utc()
    today = now.astimezone(IST).date()
    fetched = 0
    for back in range(0, 45):
        d = today - timedelta(days=back)
        k = d.isoformat()
        if d.weekday() >= 5 or k in days:
            continue
        if (today - d).days > KEEP_DAYS or fetched >= max_fetch:
            break
        last = tried.get(k)
        # bugünün dosyası akşam yayımlanır: aynı gün en sık saatte bir dene; geçmiş günler bir kez denenir
        if last and (k != today.isoformat() or now - parse_iso(last) < timedelta(hours=1)):
            continue
        tried[k] = iso(now)
        blob = _get(bulletin_url(d))
        if not blob:
            continue
        f = _unzip_first(blob)
        if not f:
            continue
        rows = parse_bulletin(_decode(f[1]))
        if rows:
            days[k] = {s: v for s, v in rows.items() if s in syms}
            fetched += 1
    lo = (today - timedelta(days=KEEP_DAYS)).isoformat()
    days = {k: v for k, v in days.items() if k >= lo}
    tried = {k: v for k, v in tried.items() if k >= lo}
    out = {"updated": iso(now), "source": "Borsa İstanbul günlük bülten", "days": dict(sorted(days.items())),
           "tried": tried, "summary": summarize(days, syms)}
    FLOWS.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("BIST bülten: %d yeni gün, %d gün kayıtlı", fetched, len(days))
    return out


def summarize(days: dict, syms: set[str]) -> dict:
    """Hisse başına: son gün açığa satış payı, 20 seans ortalaması, son 30 seans serisi."""
    order = sorted(days)
    out = {}
    for s in sorted(syms):
        ser = [(d, days[d][s]) for d in order if s in days[d]]
        if not ser:
            continue
        d_last, last = ser[-1]
        prev = [v["short_pct"] for _, v in ser[:-1]][-AVG_N:]
        avg = sum(prev) / len(prev) if prev else None
        out[s] = {"date": d_last, "short_pct": last["short_pct"], "short_value": last["short_value"],
                  "value": last["value"], "avg20": round(avg, 2) if avg is not None else None, "n": len(prev),
                  "gross": last["gross"], "short_ok": last["short_ok"], "close_sess_pct": last.get("close_sess_pct"),
                  "series": [[d, v["short_pct"]] for d, v in ser[-30:]]}
    return out


def flow_items(stocks: list, flows: dict, cfg: dict | None = None) -> list[Item]:
    """Açığa satış payı 20 seans ortalamasının belirgin üstüne çıktıysa akışa kural tabanlı kayıt."""
    cfg = cfg or {}
    mult, floor, min_n = float(cfg.get("short_mult", 2.0)), float(cfg.get("short_min_pct", 5.0)), int(cfg.get("min_days", 10))
    out = []
    names = {s.symbol: s for s in stocks}
    for sym, m in (flows.get("summary") or {}).items():
        st = names.get(sym)
        if not st or m.get("avg20") is None or m["n"] < min_n:
            continue
        pct, avg = m["short_pct"], m["avg20"]
        if pct < floor or pct < mult * max(avg, 0.5):
            continue
        d = m["date"]
        gun = f"{d[8:10]}.{d[5:7]}"
        x = pct / max(avg, 0.1)
        tr = lambda v: str(round(v, 1)).replace(".", ",")              # noqa: E731
        title = f"{sym}: açığa satış yoğunlaştı · işlemlerin %{tr(pct)}'i ({gun})"
        what = (f"{gun} seansında açığa satış hacmi toplam işlem hacminin %{tr(pct)}'i; "
                f"son {m['n']} seans ortalaması %{tr(avg)} ({tr(x)} katı)")
        out.append(Item(
            id=make_id("short", sym, d), source="Borsa İstanbul bülteni", source_type="technical", market="BIST",
            title=title, summary=what, lang="tr", tickers=[sym], published=iso(now_utc()),
            url="https://www.borsaistanbul.com/tr/sayfa/332/kredili-islem-ve-aciga-satis",
            extra={"no_ai": True, "short_flow": True, "short_pct": pct, "avg20": avg, "bar": d},
            analysis={"sentiment": "bearish", "confidence": 55, "materiality": "medium" if x >= 3 else "low",
                      "horizon": "days", "category": "Açığa satış", "event_label": "Açığa satış artışı",
                      "headline_tr": title, "what": what,
                      "why": "Açığa satışın işlem hacmindeki payının sıçraması, düşüş beklentisiyle pozisyon alındığını gösterebilir.",
                      "risk": "Açığa satışlar arbitraj ya da piyasa yapıcılık amaçlı olabilir; kısa pozisyonların kapanması "
                              "ileride alım baskısı (short squeeze) da yaratabilir.",
                      "summary": "", "affected_tickers": [sym], "provider": "kural (açığa satış)"},
        ))
    return out


# ------------------------------------------------------------------ genel kurullar
def _cell_date(v) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_gk(blob: bytes) -> list[dict]:
    import openpyxl
    f = _unzip_first(blob)
    if not f:
        return []
    wb = openpyxl.load_workbook(io.BytesIO(f[1]), read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    if not rows:
        return []
    norm = lambda x: str(x or "").replace("İ", "I").lower().replace("ı", "i").replace("\u0307", "")   # noqa: E731
    hdr = [norm(str(h or "").split("/")[0].strip()) for h in rows[0]]

    def ci(*keys):
        return next((i for i, h in enumerate(hdr) if any(norm(k) in h for k in keys)), None)
    i_code, i_type, i_date, i_time = ci("pay kodu"), ci("toplanti türü"), ci("toplanti tarihi"), ci("toplanti saati")
    i_agenda, i_cancel, i_url, i_name = ci("gündemde"), ci("iptal"), ci("web sayfasi"), ci("şirket adi")
    out = []
    for r in rows[1:]:
        g = lambda i: r[i] if i is not None and i < len(r) else None   # noqa: E731
        d = _cell_date(g(i_date))
        if not g(i_code) or not d:
            continue
        out.append({"code": str(g(i_code)).strip(), "name": str(g(i_name) or ""), "type": str(g(i_type) or "Genel Kurul"),
                    "date": d, "time": str(g(i_time) or "")[:5], "agenda": str(g(i_agenda) or ""),
                    "cancelled": str(g(i_cancel) or "").lower().startswith("evet"), "url": str(g(i_url) or "")})
    return out


def agm_list(max_age_h: int = 24) -> list[dict]:
    """Bu ve gelecek yılın genel kurul listesi (günde bir indirilir, data/bist_gk.json önbelleği)."""
    try:
        cache = json.loads(GK_CACHE.read_text(encoding="utf-8"))
        if now_utc() - parse_iso(cache["updated"]) < timedelta(hours=max_age_h):
            return cache["items"]
    except (FileNotFoundError, ValueError, KeyError):
        cache = None
    items, ok = [], False
    y = now_utc().astimezone(IST).year
    for year in (y, y + 1):
        blob = _get(f"{BASE}/data/gk/gk{year}.zip", timeout=60)
        if blob:
            ok = True
            items += parse_gk(blob)
    if not ok:
        return (cache or {}).get("items", [])
    GK_CACHE.write_text(json.dumps({"updated": iso(now_utc()), "items": items}, ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")
    return items


def agm_events(stocks: list, items: list[dict]) -> list[dict]:
    """İzleme listesi BIST hisselerinin genel kurulları → takvim olayları."""
    syms = {s.symbol for s in stocks if s.market == "BIST"}
    out = []
    for it in items:
        if it["code"] not in syms or it["cancelled"]:
            continue
        agenda = it["agenda"].replace("Kar Payı", "Kâr payı")
        important = any(k in it["agenda"] for k in ("Kar Payı", "Sermaye Artırımı", "Birleşme", "Bölünme"))
        out.append({"kind": "agm", "date": it["date"], "time": it["time"] or None, "market": "BIST", "ticker": it["code"],
                    "title": f"{it['code']} {it['type'].lower()}", "detail": f"Gündem: {agenda}" if agenda else "",
                    "importance": 2 if important or "Olağanüstü" in it["type"] else 1, "url": it["url"]})
    return out
