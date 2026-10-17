"""Türkiye elektrik üretim şirketlerinin kurulu güç envanteri (EPİAŞ Şeffaflık Platformu).

`python -m radar.energy` — enerji.yml iş akışı (haftalık). Çıktı: site/data/enerji/kurulu_guc.json (+ _history.json).

Yöntem
- Şirketler: EPİAŞ organizasyon listesi (piyasa katılımcısı tüzel kişiler; borsada olan ya da olmayan hepsi).
- Kurulu güç: her şirket için Emre Amade Kapasite (EAK) — santralin sisteme verebileceği aktif güç, kaynak bazında,
  saatlik. Son 7 günün kaynak bazında en yüksek değeri o şirketin kapasitesi sayılır (bakım/arıza düşüşlerini eler).
  EAK lisanslı santralleri kapsar; lisanssız (çoğunlukla ≤5 MW dağıtık güneş) santraller bu veride yoktur.
- Yeni devreye alınanlar: Enerji İşleri Genel Müdürlüğü'nün geçici kabul listesi (lisanslı santral yatırımları):
  tarih, şirket, santral, yakıt, ilave kurulu güç.
- Gruplama: config/energy_groups.yml unvan önekleriyle gruba ve borsa koduna bağlar; listede olmayanlar unvanın
  ilk ayırt edici kelimesiyle otomatik gruplanır.

Kimlik: EPİAŞ Şeffaflık hesabı (ücretsiz). EPIAS_USERNAME / EPIAS_PASSWORD secret'ları; TGT bileti 2 saat geçerli.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys
import time

import requests
import yaml

from .config import CONFIG, DATA

log = logging.getLogger("radar.energy")

BASE = "https://seffaflik.epias.com.tr/electricity-service"
LOGIN = "https://giris.epias.com.tr/cas/v1/tickets"
OUT = DATA / "enerji"
UA = "piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"
TZ = dt.timezone(dt.timedelta(hours=3))

# EAK alanı → (kaynak, alt kaynak). Kaynaklar panelde 7 renkle; alt kaynaklar şirket ayrıntısında.
EAK_FIELDS = {
    "barajli": ("hidro", "Barajlı"), "akarsu": ("hidro", "Akarsu"),
    "ruzgar": ("ruzgar", "Rüzgâr"), "gunes": ("gunes", "Güneş"), "jeotermal": ("jeotermal", "Jeotermal"),
    "dogalgaz": ("dogalgaz", "Doğalgaz"),
    "linyit": ("komur", "Linyit"), "ithalKomur": ("komur", "İthal kömür"), "tasKomur": ("komur", "Taş kömürü"),
    "biokutle": ("diger", "Biyokütle"), "fuelOil": ("diger", "Fuel oil"), "nafta": ("diger", "Nafta"), "diger": ("diger", "Diğer"),
}
SOURCES = ["hidro", "ruzgar", "gunes", "jeotermal", "dogalgaz", "komur", "diger"]
RENEWABLE = {"hidro", "ruzgar", "gunes", "jeotermal"}

# Otomatik gruplamada tek başına grup adı olamayacak kadar genel ilk kelimeler (o zaman ilk iki kelime alınır)
GENERIC = set("""ANADOLU AKDENİZ EGE KARADENİZ MARMARA TRAKYA DOĞU BATI KUZEY GÜNEY ORTA TÜRKİYE TÜRK YENİ YEŞİL GÜNEŞ
RÜZGAR RÜZGÂR RES GES HES JES MAVİ BÜYÜK İSTANBUL ANKARA İZMİR ELEKTRİK ENERJİ ÜRETİM ALTERNATİF TEMİZ GLOBAL
ULUSLARARASI ENERJİSA ARMA ADA ALTIN BEYAZ KIRMIZI AK KARA""".split())


# ─────────────────────────────── ad normalleştirme ve gruplama
def norm(s: str) -> str:
    """Türkçe büyük harf, noktalama boşluk: 'Zorlu Enerji Elektrik Üretim A.Ş.' → 'ZORLU ENERJİ ELEKTRİK ÜRETİM A Ş'."""
    s = (s or "").replace("i", "İ").replace("ı", "I").upper()
    s = re.sub(r"[^\wÇĞİÖŞÜÂÎÛ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_groups(path=None) -> list[dict]:
    raw = yaml.safe_load(((path or CONFIG / "energy_groups.yml")).read_text(encoding="utf-8")) or {}
    out = []
    for g in raw.get("groups") or []:
        g = dict(g)
        g["key"] = g.get("ticker") or norm(g["name"]).replace(" ", "-")
        g["_rx"] = re.compile(r"^(?:" + "|".join(re.escape(norm(m)) for m in g["match"]) + r")\b")
        out.append(g)
    return out


def auto_key(name: str) -> str:
    w = [x for x in norm(name).split() if len(x) > 1]
    if not w:
        return norm(name)
    return " ".join(w[:2]) if w[0] in GENERIC and len(w) > 1 else w[0]


def classify(name: str, groups: list[dict]) -> tuple[str, dict | None]:
    n = norm(name)
    for g in groups:
        if g["_rx"].search(n):
            return g["key"], g
    return "auto:" + auto_key(name), None


# ─────────────────────────────── EPİAŞ istemcisi
class Epias:
    def __init__(self, user: str, password: str, gap: float = 0.25):
        self.user, self.password, self.gap = user, password, gap
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        self.tgt, self.tgt_at, self.last = None, 0.0, 0.0
        self.calls = 0

    def login(self) -> None:
        r = self.s.post(LOGIN, data={"username": self.user, "password": self.password},
                        headers={"Accept": "text/plain", "Content-Type": "application/x-www-form-urlencoded"}, timeout=40)
        if r.status_code not in (200, 201) or not r.text.strip().startswith("TGT-"):
            raise RuntimeError(f"EPİAŞ girişi başarısız: HTTP {r.status_code}")
        self.tgt, self.tgt_at = r.text.strip(), time.monotonic()

    def post(self, path: str, body: dict, retries: int = 3) -> dict | None:
        for attempt in range(retries + 1):
            if not self.tgt or time.monotonic() - self.tgt_at > 100 * 60:      # bilet 2 saat geçerli
                self.login()
            wait = self.gap - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.calls += 1
            try:
                r = self.s.post(BASE + path, json=body, headers={"TGT": self.tgt}, timeout=90)
            except requests.RequestException as e:
                log.warning("%s %s", path, e)
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and attempt < retries:
                self.tgt = None
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(5 * (attempt + 1))
                continue
            log.warning("%s HTTP %s %s", path, r.status_code, r.text[:200])
            return None
        return None

    def paged(self, path: str, body: dict, size: int = 1000, limit: int = 50) -> list[dict]:
        out = []
        for n in range(1, limit + 1):
            d = self.post(path, {**body, "page": {"number": n, "size": size}}) or {}
            items = d.get("items") or []
            out += items
            total = (d.get("page") or {}).get("total")
            if len(items) < size or (total is not None and len(out) >= total):
                break
        return out


def iso(d: dt.date) -> str:
    return f"{d.isoformat()}T00:00:00+03:00"


# ─────────────────────────────── hesap
def capacity(rows: list[dict]) -> dict[str, float]:
    """Saatlik EAK satırları → alan bazında en yüksek değer (MW). Sıfırlar atlanır."""
    out: dict[str, float] = {}
    for r in rows:
        for f in EAK_FIELDS:
            v = r.get(f)
            if isinstance(v, (int, float)) and v > out.get(f, 0):
                out[f] = float(v)
    return {k: round(v, 1) for k, v in out.items() if v > 0}


def by_source(fields: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for f, v in fields.items():
        src = EAK_FIELDS[f][0]
        out[src] = round(out.get(src, 0) + v, 1)
    return out


FUEL_RX = [("ruzgar", r"RÜZGAR|RÜZGÂR|WIND"), ("gunes", r"GÜNEŞ|SOLAR"), ("jeotermal", r"JEOTERM"),
           ("hidro", r"BARAJ|HİDRO|AKARSU|KANAL|REGÜLATÖR|NEHİR"), ("dogalgaz", r"DOĞAL ?GAZ|LNG"),
           ("komur", r"LİNYİT|KÖMÜR|ASFALTİT"), ("diger", r".")]


def fuel_source(s: str) -> str:
    n = norm(s)
    return next(k for k, rx in FUEL_RX if re.search(rx, n))


def _num(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def build(orgs: list[dict], caps: dict[int, dict], adds: list[dict], national: dict, groups: list[dict],
          window: tuple[dt.date, dt.date], now: dt.datetime | None = None) -> dict:
    """Ham EPİAŞ verisinden panel JSON'u."""
    now = now or dt.datetime.now(dt.timezone.utc)
    gmeta = {g["key"]: g for g in groups}
    org_rows, G = [], {}
    name_to_org = {}
    for o in orgs:
        oid = o.get("organizationId")
        f = caps.get(oid) or {}
        if not f:
            continue
        name = (o.get("organizationName") or o.get("organizationShortName") or "").strip()
        key, g = classify(name, groups)
        src = by_source(f)
        row = {"id": oid, "name": name, "short": o.get("organizationShortName"), "eic": o.get("organizationEtsoCode"),
               "group": key, "fields": f, "src": src, "total": round(sum(f.values()), 1)}
        org_rows.append(row)
        name_to_org[norm(name)] = row
        G.setdefault(key, []).append(row)

    one_year = (now.date() - dt.timedelta(days=365)).isoformat()
    add_rows = []
    for a in adds:
        mw = _num(a.get("ilaveKuruluGuc"))
        if not mw:
            continue
        comp = (a.get("sirketAdi") or "").strip()
        key, _ = classify(comp, groups)
        org = name_to_org.get(norm(comp))
        if org:
            key = org["group"]
        add_rows.append({"date": (a.get("geciciKabulTarihi") or "")[:10], "company": comp, "plant": (a.get("santralAdi") or "").strip(),
                         "fuel": (a.get("yakitCinsi") or "").strip(), "src": fuel_source(a.get("yakitCinsi") or ""),
                         "mw": round(mw, 2), "city": (a.get("il") or "").strip(), "group": key, "org": org["id"] if org else None})
    add_rows.sort(key=lambda r: r["date"], reverse=True)

    tr_total = sum(national.values()) or sum(r["total"] for r in org_rows) or 1.0
    grp_rows = []
    for key, rows in G.items():
        g = gmeta.get(key)
        src: dict[str, float] = {}
        for r in rows:
            for s, v in r["src"].items():
                src[s] = round(src.get(s, 0) + v, 1)
        total = round(sum(src.values()), 1)
        adds12 = round(sum(a["mw"] for a in add_rows if a["group"] == key and a["date"] >= one_year), 1)
        if g:
            name, auto = g["name"], False
        else:
            rows.sort(key=lambda r: -r["total"])
            name, auto = (rows[0]["name"] if len(rows) == 1 else key[5:].title()), True
        ren = sum(v for s, v in src.items() if s in RENEWABLE)
        grp_rows.append({"key": key, "name": name, "auto": auto, "ticker": (g or {}).get("ticker"), "parent": (g or {}).get("parent"),
                         "kind": (g or {}).get("kind", "ozel"), "total": total, "share": round(total / tr_total, 5),
                         "src": src, "renew": round(ren / total, 4) if total else None, "adds12": adds12,
                         "orgs": [r["id"] for r in sorted(rows, key=lambda r: -r["total"])]})
    grp_rows.sort(key=lambda g: -g["total"])
    listed = sum(g["total"] for g in grp_rows if g["ticker"] or g["parent"])
    return {
        "generated": now.isoformat(timespec="seconds"),
        "window": [window[0].isoformat(), window[1].isoformat()],
        "method": "EAK: son 7 günün kaynak bazında en yüksek emre amade kapasitesi (MW), lisanslı santraller",
        "national": {"src": by_source(national), "fields": national, "total": round(sum(national.values()), 1)},
        "listed_share": round(listed / tr_total, 4),
        "groups": grp_rows,
        "orgs": sorted(org_rows, key=lambda r: -r["total"]),
        "additions": add_rows,
        "sources": SOURCES,
        "source_names": {"hidro": "Hidro", "ruzgar": "Rüzgâr", "gunes": "Güneş", "jeotermal": "Jeotermal",
                         "dogalgaz": "Doğalgaz", "komur": "Kömür", "diger": "Diğer"},
        "field_names": {k: v[1] for k, v in EAK_FIELDS.items()},
    }


def append_history(doc: dict, path=None, keep: int = 260) -> list[dict]:
    path = path or OUT / "_history.json"
    try:
        hist = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        hist = []
    day = doc["window"][1]
    snap = {"d": day, "tr": doc["national"]["src"], "g": {g["key"]: g["total"] for g in doc["groups"][:150]}}
    hist = [h for h in hist if h.get("d") != day] + [snap]
    hist = hist[-keep:]
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return hist


# ─────────────────────────────── çalıştırma
def collect(cl: Epias, today: dt.date | None = None, since: str = "2015-01-01") -> tuple:
    today = today or dt.datetime.now(TZ).date()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=6)
    body = {"startDate": iso(start), "endDate": iso(end), "region": "TR1"}
    national = capacity(cl.paged("/v1/generation/data/aic", body, size=500))
    orgs = (cl.post("/v1/generation/data/organization-list", {"startDate": iso(start), "endDate": iso(end)}) or {}).get("items") or []
    log.info("EPİAŞ: %d organizasyon, Türkiye EAK %.0f MW", len(orgs), sum(national.values()))
    caps = {}
    for i, o in enumerate(orgs, 1):
        oid = o.get("organizationId")
        if oid is None:
            continue
        rows = cl.paged("/v1/generation/data/aic", {**body, "organizationId": oid}, size=500, limit=3)
        c = capacity(rows)
        if c:
            caps[oid] = c
        if i % 200 == 0:
            log.info("EAK %d/%d (%d üretici)", i, len(orgs), len(caps))
    adds = cl.paged("/v1/generation/data/licensed-powerplant-investment-list",
                    {"startDate": f"{since}T00:00:00+03:00", "endDate": iso(today)}, size=1000)
    return orgs, caps, adds, national, (start, end)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    user, pw = os.environ.get("EPIAS_USERNAME"), os.environ.get("EPIAS_PASSWORD")
    if not (user and pw):
        log.warning("EPIAS_USERNAME / EPIAS_PASSWORD tanımlı değil: enerji verisi güncellenmedi")
        return 0
    cl = Epias(user, pw)
    orgs, caps, adds, national, window = collect(cl)
    if not caps:
        log.error("EAK verisi gelmedi (%d çağrı); önceki veri korunuyor", cl.calls)
        return 1
    doc = build(orgs, caps, adds, national, load_groups(), window)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kurulu_guc.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    append_history(doc)
    log.info("Enerji: %d şirket, %d grup, %d devreye alma, %d çağrı", len(doc["orgs"]), len(doc["groups"]), len(doc["additions"]), cl.calls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
