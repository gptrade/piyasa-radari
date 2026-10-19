"""Türkiye elektrik üretim şirketlerinin kurulu güç envanteri.

`python -m radar.energy` — enerji.yml iş akışı. Çıktı: site/data/enerji/kurulu_guc.json (+ _history.json).

Kaynaklar
- Santral envanteri ve sahiplik: Global Energy Monitor (GEM) izleyicileri, config/enerji/gem_tr.json
  (tools/gem_import.py ile üretilir; CC BY 4.0). Güneş ≥1 MW, rüzgâr ≥10 MW, hidro (eşik altı dahil), kömür,
  doğalgaz, biyoenerji, nükleer; işletmede ve yapım/planlama aşamasındaki üniteler; kömür/gaz/biyoenerjide tam
  sahiplik zinciri ve paylar.
- Türkiye bağlamı (isteğe bağlı): EPİAŞ Şeffaflık Platformu — YEKDEM lisanslı/lisanssız kurulu güç. EPIAS_USERNAME /
  EPIAS_PASSWORD yoksa atlanır.

Gruplama: config/energy_groups.yml. Sahiplik zincirinde santrale en yakın eşleşen şirket esas alınır; eşleşmeyen
sahipler kendi adlarıyla görünür. Grup MW'ı PAY ORANINA GÖREdir (ortaklık payı × ünite gücü); ayrıca kontrol edilen
(pay ≥ %50) ünitelerin tam gücü "konsolide" olarak verilir.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys
import time
import unicodedata

import requests
import yaml

from .config import CONFIG, DATA

log = logging.getLogger("radar.energy")

GEM = CONFIG / "enerji" / "gem_tr.json"
OUT = DATA / "enerji"
BASE = "https://seffaflik.epias.com.tr/electricity-service"
LOGIN = "https://giris.epias.com.tr/cas/v1/tickets"
UA = "piyasa-radari/1.0 (+https://github.com/gptrade/piyasa-radari)"
TZ = dt.timezone(dt.timedelta(hours=3))

KIND_SRC = {"hydro": "hidro", "wind": "ruzgar", "solar": "gunes", "geothermal": "jeotermal", "gas": "dogalgaz",
            "coal": "komur", "nuclear": "nukleer", "bio": "diger"}
SOURCES = ["hidro", "ruzgar", "gunes", "jeotermal", "dogalgaz", "komur", "nukleer", "diger"]
SOURCE_NAMES = {"hidro": "Hidro", "ruzgar": "Rüzgâr", "gunes": "Güneş", "jeotermal": "Jeotermal", "dogalgaz": "Doğalgaz",
                "komur": "Kömür", "nukleer": "Nükleer", "diger": "Biyokütle/diğer"}
RENEWABLE = {"hidro", "ruzgar", "gunes", "jeotermal", "diger"}
PIPE = {"construction", "pre-construction", "announced", "pre-permit", "permitted"}
STATUS_NAMES = {"operating": "işletmede", "construction": "yapım", "pre-construction": "izin/finansman", "pre-permit": "izin öncesi",
                "permitted": "izinli", "announced": "duyuruldu", "mothballed": "atıl"}
NOT_CORP = re.compile(r"^(NATURAL PERSON|SMALL SHAREHOLDER|UNKNOWN|GOVERNMENT OF|MINISTRY OF)", re.I)


# ─────────────────────────────── ad sadeleştirme ve gruplama
def fold(s: str) -> str:
    """'Aksa Enerji Üretim A.Ş.' → 'AKSA ENERJI URETIM A S' (Türkçe harfler sadeleşir, noktalama boşluk)."""
    s = (s or "").replace("ı", "i").replace("İ", "I").replace("ş", "s").replace("Ş", "S").replace("ğ", "g").replace("Ğ", "G")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_groups(path=None) -> list[dict]:
    raw = yaml.safe_load((path or CONFIG / "energy_groups.yml").read_text(encoding="utf-8")) or {}
    out = []
    for g in raw.get("groups") or []:
        g = dict(g)
        g["key"] = g.get("ticker") or fold(g["name"]).replace(" ", "-")
        g["_rx"] = re.compile(r"^(?:" + "|".join(re.escape(fold(m)) for m in g["match"]) + r")(?:\s|$)")
        out.append(g)
    return out


def load_exclude(path=None) -> re.Pattern | None:
    raw = yaml.safe_load((path or CONFIG / "energy_groups.yml").read_text(encoding="utf-8")) or {}
    ex = raw.get("exclude") or []
    return re.compile(r"\b(?:" + "|".join(re.escape(fold(x)) for x in ex) + r")\b") if ex else None


def match_group(name: str, groups: list[dict]) -> dict | None:
    n = fold(name)
    return next((g for g in groups if g["_rx"].search(n)), None)


def parse_owners(s: str | None) -> list[tuple[str, float | None]]:
    """'A [60%]; B [40%]' → [('A', .6), ('B', .4)]; payı yazmayanlara kalan pay eşit bölünür."""
    out = []
    for part in (s or "").split(";"):
        part = part.strip()
        if not part:
            continue
        m = re.search(r"\[\s*([\d.,]+)\s*%\s*\]\s*$", part)
        name = re.sub(r"\s*\[[^\]]*\]\s*$", "", part).strip()
        out.append((name, float(m.group(1).replace(",", ".")) / 100 if m else None))
    known = sum(p for _, p in out if p is not None)
    unk = [i for i, (_, p) in enumerate(out) if p is None]
    if unk:
        rest = max(0.0, 1 - known) / len(unk)
        out = [(n, p if p is not None else rest) for n, p in out]
    return out


def parse_path(path: str) -> tuple[list[str], list[float | None]]:
    """'A -> B [80%] -> Santral [100%]' → (['A','B','Santral'], [None, .8, 1.0]); pct[i] = nodes[i-1]'in nodes[i]'deki payı."""
    nodes, pcts = [], []
    for i, tok in enumerate(path.split("->")):
        tok = tok.strip()
        m = re.search(r"\[\s*([\d.,]+|unknown)\s*%?\s*\]\s*$", tok)
        name = re.sub(r"\s*\[[^\]]*\]\s*$", "", tok).strip()
        nodes.append(name)
        pcts.append(None if i == 0 else (float(m.group(1).replace(",", ".")) / 100 if m and m.group(1) != "unknown" else 1.0))
    return nodes, pcts


def _share_from(pcts: list, k: int) -> float:
    s = 1.0
    for p in pcts[k + 1:]:
        s *= p if p is not None else 1.0
    return s


def assign(unit: dict, groups: list[dict]) -> list[dict]:
    """Ünite → [{key, name, g, share, node}]: payı olan sahipler/gruplar."""
    out: dict[tuple, dict] = {}

    def add(node, share, g):
        key = g["key"] if g else "own:" + fold(node)
        k = (key, fold(node))
        if k not in out:
            out[k] = {"key": key, "name": g["name"] if g else node.strip(), "g": g, "share": 0.0, "node": node.strip()}
        out[k]["share"] = max(out[k]["share"], share)        # aynı düğümden geçen farklı zincirler aynı payı taşır

    if unit.get("paths"):
        chains = [parse_path(p) for p in unit["paths"]]
        by_imm: dict[str, list] = {}
        for nodes, pcts in chains:
            if len(nodes) >= 2:
                by_imm.setdefault(fold(nodes[-2]), []).append((nodes, pcts))
        for imm, cs in by_imm.items():
            imm_share = _share_from(cs[0][1], len(cs[0][0]) - 2)
            covered, rest = 0.0, []
            hits = {}
            for nodes, pcts in cs:
                hit = None
                for k in range(len(nodes) - 2, -1, -1):                      # santrale en yakından yukarı
                    g = match_group(nodes[k], groups)
                    if g:
                        hit = (nodes[k], _share_from(pcts, k), g)
                        break
                if hit:
                    hits[fold(hit[0])] = hit
                else:
                    rest.append((nodes, pcts))
            for node, share, g in hits.values():
                add(node, share, g)
                covered += share
            left = imm_share - covered
            if rest and left > 0.001:
                # eşleşmeyen zincirler: hepsinde ortak olan en üst kurumsal düğüm
                common = None
                for nodes, _ in rest:
                    s = [fold(n) for n in nodes[:-1]]
                    common = s if common is None else [n for n in common if n in s]
                nodes, pcts = rest[0]
                top = next((k for k in range(len(nodes) - 1) if fold(nodes[k]) in (common or []) and not NOT_CORP.search(nodes[k].strip())), len(nodes) - 2)
                add(nodes[top], min(left, _share_from(pcts, top)), None)
    else:
        for name, share in parse_owners(unit.get("own")):
            add(name, share, match_group(name, groups))
    return list(out.values())


# ─────────────────────────────── EPİAŞ (isteğe bağlı bağlam)
class Epias:
    def __init__(self, user: str, password: str):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        r = self.s.post(LOGIN, data={"username": user, "password": password},
                        headers={"Accept": "text/plain", "Content-Type": "application/x-www-form-urlencoded"}, timeout=40)
        if r.status_code not in (200, 201) or not r.text.strip().startswith("TGT-"):
            raise RuntimeError(f"EPİAŞ girişi başarısız (HTTP {r.status_code})")
        self.tgt = r.text.strip()

    def post(self, path: str, body: dict) -> dict | None:
        for attempt in range(3):
            try:
                r = self.s.post(BASE + path, json=body, headers={"TGT": self.tgt}, timeout=90)
                if r.status_code == 200:
                    return r.json()
                log.warning("%s HTTP %s", path, r.status_code)
            except requests.RequestException as e:
                log.warning("%s %s", path, e)
            time.sleep(3 * (attempt + 1))
        return None


YEKDEM_SRC = {"Güneş": "gunes", "Rüzgar": "ruzgar", "Rezarvuarlı": "hidro", "Kanal Tipi": "hidro", "Nehir Tipi": "hidro",
              "Jeotermal": "jeotermal", "Biyokütle": "diger", "LFG-Çöp Gazı": "diger", "Biyogaz": "diger"}


def epias_context(today: dt.date | None = None) -> dict | None:
    user, pw = os.environ.get("EPIAS_USERNAME"), os.environ.get("EPIAS_PASSWORD")
    if not (user and pw):
        return None
    today = today or dt.datetime.now(TZ).date()
    try:
        cl = Epias(user, pw)
    except Exception as e:                                                   # noqa: BLE001
        log.warning("%s", e)
        return None
    period = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    d = cl.post("/v1/renewables/data/new-installed-capacity", {"period": f"{period.isoformat()}T00:00:00+03:00"}) or {}
    rows = d.get("installedCapacities") or []
    if not rows:
        return None
    lic, unlic = {}, {}
    for r in rows:
        s = YEKDEM_SRC.get(r.get("renewableEnergyType"), "diger")
        lic[s] = round(lic.get(s, 0) + (r.get("licencedCapacity") or 0), 1)
        unlic[s] = round(unlic.get(s, 0) + (r.get("unlicencedCapacity") or 0), 1)
    out = {"period": period.isoformat(), "yekdem_licensed": lic, "yekdem_unlicensed": unlic}
    try:
        out["new_plants"] = new_plants(cl, today)
    except Exception as e:                                                   # noqa: BLE001
        log.warning("EPİAŞ yeni santral kontrolü: %s", e)
    return out


RT_KEYS = {"sun": "gunes", "wind": "ruzgar", "dammedHydro": "hidro", "river": "hidro", "geothermal": "jeotermal", "naturalGas": "dogalgaz",
           "lng": "dogalgaz", "lignite": "komur", "importCoal": "komur", "blackCoal": "komur", "asphaltiteCoal": "komur",
           "biomass": "diger", "wasteheat": "diger", "fueloil": "diger", "naphta": "diger"}
PLANTS = OUT / "_epias_plants.json"


def new_plants(cl: Epias, today: dt.date) -> list[dict]:
    """EPİAŞ lisanslı santral listesine yeni eklenenler (ilk görüldüğü gün) ve son 7 günün en yüksek saatlik üretimi."""
    r = cl.s.get(BASE + "/v1/generation/data/powerplant-list", headers={"TGT": cl.tgt}, timeout=90)
    items = (r.json().get("items") if r.status_code == 200 else None) or []
    if not items:
        return []
    try:
        st = json.loads(PLANTS.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        st = {"known": {}, "new": []}
    first_run = not st["known"]
    for p in items:
        pid = str(p.get("id"))
        if pid in st["known"]:
            continue
        st["known"][pid] = today.isoformat()
        if not first_run:
            st["new"].append({"id": p.get("id"), "name": (p.get("shortName") or p.get("name") or "").strip(), "eic": p.get("eic"),
                              "first_seen": today.isoformat()})
    # yeni santrallerin son 7 günlük üretimi: kaynak ve gözlenen en yüksek saatlik güç
    for n in st["new"]:
        if n.get("checked") == today.isoformat() or n.get("first_seen", "") < (today - dt.timedelta(days=60)).isoformat():
            continue
        g = cl.post("/v1/generation/data/realtime-generation", {"startDate": f"{(today - dt.timedelta(days=8)).isoformat()}T00:00:00+03:00",
                                                                  "endDate": f"{(today - dt.timedelta(days=1)).isoformat()}T00:00:00+03:00",
                                                                  "powerPlantId": n["id"], "page": {"number": 1, "size": 500}}) or {}
        peak, src, mwh = 0.0, {}, 0.0
        for h in g.get("items") or []:
            peak = max(peak, h.get("total") or 0)
            mwh += h.get("total") or 0
            for k, s_ in RT_KEYS.items():
                if h.get(k):
                    src[s_] = src.get(s_, 0) + h[k]
        n["peak_mw"], n["mwh_7d"], n["src"] = round(peak, 1), round(mwh), max(src, key=src.get) if src else None
        n["checked"] = today.isoformat()
    st["new"] = st["new"][-300:]
    PLANTS.parent.mkdir(parents=True, exist_ok=True)
    PLANTS.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sorted(st["new"], key=lambda x: x["first_seen"], reverse=True)[:100]


# ─────────────────────────────── panel verisi
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                       "october", "november", "december"], 1)}
TRACKER_SRC = {"solar": ["gunes"], "wind": ["ruzgar"], "hydro": ["hidro"], "nuclear": ["nukleer"], "geothermal": ["jeotermal"],
               "ownership": ["komur", "dogalgaz", "diger"]}
KAP_SRC = {"gunes": "gunes", "ruzgar": "ruzgar", "hidro": "hidro", "jeotermal": "jeotermal", "dogalgaz": "dogalgaz", "komur": "komur",
           "biyokutle": "diger", "depolama": "gunes", "hibrit": "gunes", "diger": "diger"}
ADDED = {"devreye_alma", "kapasite_artisi"}
PIPE_EVENTS = {"lisans", "onlisans", "ced", "yeka", "yatirim_karari"}


def tracker_asof(sources: dict | None) -> dict[str, str]:
    """GEM dosya adlarındaki aydan kaynak bazında veri tarihi: 'Global-Solar-Power-Tracker-February-2026.xlsx' → gunes: 2026-02-28."""
    out = {}
    for k, name in (sources or {}).items():
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)-(\d{4})", name or "", re.I)
        if not m:
            continue
        y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
        last = (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        for src in TRACKER_SRC.get(k, []):
            out[src] = last
    return out


def kap_overlay(kap: dict | None, groups_out: list[dict], groups_cfg: list[dict], asof: dict[str, str]) -> list[dict]:
    """KAP olaylarını gruplara bağlar; GEM tarihinden sonraki devreye almaları ve proje hattını gruba yazar."""
    by_ticker = {g["ticker"]: g["key"] for g in groups_cfg if g.get("ticker")}
    parents = {}
    for g in groups_cfg:
        if g.get("parent") and not g.get("ticker"):
            parents.setdefault(g["parent"], []).append(g["key"])
    gidx = {g["key"]: g for g in groups_out}
    rows, latest_pipe = [], {}
    for it in (kap or {}).get("items") or []:
        key = next((by_ticker[t] for t in it.get("tickers") or [] if t in by_ticker), None)
        if key is None:
            key = next((parents[t][0] for t in it.get("tickers") or [] if len(parents.get(t, [])) == 1), None)
        for e in it.get("events") or []:
            tr = (e.get("country") or "TR").upper() in ("TR", "TÜRKİYE", "TURKIYE", "TURKEY")
            src = KAP_SRC.get(e.get("source"), "diger")
            mw = e.get("mw") or e.get("mwp")
            after = bool(it.get("date")) and it["date"] > asof.get(src, "9999")
            rows.append({"date": it.get("date"), "tickers": it.get("tickers"), "company": it.get("company"), "group": key,
                         "type": e["type"], "plant": e.get("plant"), "src": src, "raw_src": e.get("source"), "mw": e.get("mw"),
                         "mwp": e.get("mwp"), "storage": e.get("storage_mw"), "prov": e.get("province"), "tr": tr,
                         "note": e.get("note"), "url": it.get("url"), "after_gem": after, "rule": e.get("_rule") or None})
            g = gidx.get(key)
            if not g or not tr or not mw:
                continue
            if e["type"] in ADDED and after:
                g["kap_added"] = round(g.get("kap_added", 0) + mw, 1)
            elif e["type"] in PIPE_EVENTS:
                pk = (key, fold(e.get("plant") or ""))
                if pk not in latest_pipe or (it.get("date") or "") > latest_pipe[pk][0]:
                    latest_pipe[pk] = (it.get("date") or "", mw)
    for (key, _), (_, mw) in latest_pipe.items():
        gidx[key]["kap_pipe"] = round(gidx[key].get("kap_pipe", 0) + mw, 1)
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


def build(gem: dict, groups: list[dict], epias: dict | None = None, now: dt.datetime | None = None,
          exclude: re.Pattern | None = None, kap: dict | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    units = [u for u in gem["units"] if not (exclude and exclude.search(fold(u["n"] + " " + " ".join(u.get("paths") or []))))]
    gmeta = {g["key"]: g for g in groups}
    U, G = [], {}
    nat_op, nat_pipe = {}, {}
    for i, u in enumerate(units):
        src = KIND_SRC.get(u["k"], "diger")
        op = u["st"] == "operating"
        pipe = u["st"] in PIPE
        if op:
            nat_op[src] = nat_op.get(src, 0) + u["mw"]
        elif pipe:
            nat_pipe[src] = nat_pipe.get(src, 0) + u["mw"]
        owners = assign(u, groups)
        U.append({"n": u["n"] + (f" {u['ph']}" if u.get("ph") and str(u["ph"]) not in u["n"] else ""), "s": src, "mw": u["mw"], "st": u["st"],
                  "y": u.get("y"), "p": u.get("prov"), "u": u.get("url"), "o": u.get("own") or (u.get("paths") or [None])[0],
                  "lic": u.get("lic")})
        for ow in owners:
            gr = G.setdefault(ow["key"], {"key": ow["key"], "name": ow["name"], "g": ow["g"], "op": {}, "pipe": {}, "cons": 0.0,
                                          "units": [], "nodes": set()})
            gr["nodes"].add(ow["node"])
            eq = u["mw"] * ow["share"]
            if op:
                gr["op"][src] = gr["op"].get(src, 0) + eq
                if ow["share"] >= 0.5:
                    gr["cons"] += u["mw"]
            elif pipe:
                gr["pipe"][src] = gr["pipe"].get(src, 0) + eq
            gr["units"].append([i, round(ow["share"], 4)])
    nat_total = sum(nat_op.values()) or 1.0
    year = now.year
    grp = []
    for k, gr in G.items():
        g = gr["g"] or {}
        op = {s: round(v, 1) for s, v in gr["op"].items() if v >= 0.05}
        pipe = {s: round(v, 1) for s, v in gr["pipe"].items() if v >= 0.05}
        total = round(sum(op.values()), 1)
        if total < 1 and sum(pipe.values()) < 1:
            continue
        ren = sum(v for s, v in op.items() if s in RENEWABLE)
        recent = round(sum(U[i]["mw"] * sh for i, sh in gr["units"] if U[i]["st"] == "operating" and (U[i]["y"] or 0) >= year - 2), 1)
        grp.append({"key": k, "name": gr["name"], "auto": not gr["g"], "ticker": g.get("ticker"), "parent": g.get("parent"),
                    "kind": g.get("kind", "ozel"), "total": total, "cons": round(gr["cons"], 1), "share": round(total / nat_total, 5),
                    "src": op, "pipe": pipe, "pipe_total": round(sum(pipe.values()), 1), "renew": round(ren / total, 4) if total else None,
                    "recent": recent, "n": sum(1 for i, _ in gr["units"] if U[i]["st"] == "operating"),
                    "entities": sorted(gr["nodes"])[:30], "units": sorted(gr["units"], key=lambda x: -U[x[0]]["mw"] * x[1])})
    grp.sort(key=lambda g: (-g["total"], -g["pipe_total"]))
    listed = sum(g["total"] for g in grp if g["ticker"] or g["parent"])
    unowned = round(sum(U[i]["mw"] for i, u in enumerate(units) if u["st"] == "operating" and not u.get("own") and not u.get("paths")), 1)
    recent = sorted([dict(i=i, **{k: U[i][k] for k in ("n", "s", "mw", "y", "p")}) for i in range(len(U))
                     if U[i]["st"] == "operating" and (U[i]["y"] or 0) >= year - 2], key=lambda r: (-(r["y"] or 0), -r["mw"]))
    pipeline = sorted([dict(i=i, **{k: U[i][k] for k in ("n", "s", "mw", "st", "y", "p")}) for i in range(len(U)) if U[i]["st"] in PIPE],
                      key=lambda r: -r["mw"])
    asof = tracker_asof(gem.get("sources"))
    kap_rows = kap_overlay(kap, grp, groups, asof)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "gem": {"imported": gem.get("imported"), "sources": gem.get("sources"), "license": gem.get("license"), "asof": asof},
        "kap": kap_rows[:600], "kap_updated": (kap or {}).get("updated"),
        "kap_types": {"devreye_alma": "Devreye alma", "kapasite_artisi": "Kapasite artışı", "lisans": "Üretim lisansı", "onlisans": "Önlisans",
                      "ced": "ÇED", "yeka": "YEKA", "yatirim_karari": "Yatırım kararı", "sozlesme": "Sözleşme", "satin_alma": "Satın alma",
                      "satis": "Satış", "diger": "Diğer"},
        "national": {"src": {s: round(v, 1) for s, v in nat_op.items()}, "total": round(sum(nat_op.values()), 1),
                     "pipe": {s: round(v, 1) for s, v in nat_pipe.items()}, "pipe_total": round(sum(nat_pipe.values()), 1),
                     "unowned": unowned},
        "epias": epias,
        "listed_share": round(listed / nat_total, 4),
        "groups": grp,
        "units": U,
        "recent": recent[:300],
        "pipeline": pipeline[:300],
        "year": year,
        "sources": SOURCES, "source_names": SOURCE_NAMES, "status_names": STATUS_NAMES,
    }


GEM_PAGES = {"solar": "global-solar-power-tracker", "wind": "global-wind-power-tracker", "hydro": "global-hydropower-tracker",
             "nuclear": "global-nuclear-power-tracker", "geothermal": "global-geothermal-power-tracker", "ownership": "global-energy-ownership-tracker",
             "coal": "global-coal-plant-tracker", "gas": "global-oil-gas-plant-tracker"}
RELEASE = re.compile(r"(?:release|released|update|updated|version|latest data)[^.<]{0,60}?\b(January|February|March|April|May|June|July|August|"
                     r"September|October|November|December)\s+(20\d\d)|\b(January|February|March|April|May|June|July|August|September|"
                     r"October|November|December)\s+(20\d\d)\s+(?:release|update|version|data)", re.I)


def gem_watch(gem: dict, today: dt.date | None = None) -> list[dict]:
    """GEM izleyici sayfalarında bizdekinden yeni sürüm var mı (herkese açık proje sayfaları, haftada bir).
    Yeni sürüm bulunursa Telegram'a bir kez haber verir; dosyalar form ile indirildiği için içe aktarma elle yapılır."""
    today = today or dt.date.today()
    path = OUT / "_gem_watch.json"
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        st = {}
    if st.get("checked", "") > (today - dt.timedelta(days=7)).isoformat():
        return st.get("newer") or []
    have = {}
    for k, name in (gem.get("sources") or {}).items():
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)-(\d{4})", name or "", re.I)
        if m:
            have[k] = (int(m.group(2)), MONTHS[m.group(1).lower()])
    newer = []
    for k, slug in GEM_PAGES.items():
        try:
            r = requests.get(f"https://globalenergymonitor.org/projects/{slug}/", timeout=40, headers={"User-Agent": UA})
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        found = []
        for m in RELEASE.finditer(re.sub(r"<[^>]+>", " ", r.text)):
            mon, yr = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            ym = (int(yr), MONTHS[mon.lower()])
            if ym <= (today.year, today.month):
                found.append(ym)
        if found and (k not in have or max(found) > have[k]):
            y, mo = max(found)
            newer.append({"tracker": k, "release": f"{y}-{mo:02d}", "have": f"{have[k][0]}-{have[k][1]:02d}" if k in have else None,
                          "url": f"https://globalenergymonitor.org/projects/{slug}/"})
    told = set(st.get("told") or [])
    fresh = [n for n in newer if f"{n['tracker']}:{n['release']}" not in told]
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if fresh and token and chat:
        lines = "\n".join(f"• {n['tracker']}: {n['release']}" + (f" (bizdeki {n['have']})" if n["have"] else " (bizde yok)") for n in fresh)
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={"chat_id": chat, "disable_web_page_preview": True,
                          "text": "⚡ Global Energy Monitor'de yeni izleyici sürümü var:\n" + lines +
                                  "\nDosyaları indirip Claude'a gönderirsen enerji sekmesi güncellenir."})
            told |= {f"{n['tracker']}:{n['release']}" for n in fresh}
        except requests.RequestException:
            pass
    st = {"checked": today.isoformat(), "newer": newer, "told": sorted(told)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    return newer


def append_history(doc: dict, path=None, keep: int = 120) -> list[dict]:
    path = path or OUT / "_history.json"
    try:
        hist = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        hist = []
    day = (doc.get("gem") or {}).get("imported") or doc["generated"][:10]
    snap = {"d": day, "tr": doc["national"]["src"], "g": {g["key"]: g["total"] for g in doc["groups"][:150]}}
    hist = [h for h in hist if h.get("d") != day] + [snap]
    path.write_text(json.dumps(hist[-keep:], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return hist


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    gem = json.loads(GEM.read_text(encoding="utf-8"))
    groups = load_groups()
    kap = None
    try:
        from . import energy_kap
        uni_path = DATA / "fin" / "_universe.json"
        universe = json.loads(uni_path.read_text(encoding="utf-8")) if uni_path.exists() else {}
        analyzer = None
        try:
            from .analyze import Analyzer
            from .config import load_settings
            analyzer = Analyzer(load_settings())
        except Exception as e:                                               # noqa: BLE001
            log.warning("AI yok: %s", e)
        extra = {g["ticker"] for g in groups if g.get("ticker")} | {g["parent"] for g in groups if g.get("parent")}
        kap = energy_kap.update(universe, extra, analyzer) if universe else energy_kap.load_state()
    except Exception as e:                                                   # noqa: BLE001
        log.warning("KAP enerji olayları güncellenemedi: %s", e)
        from .energy_kap import load_state
        kap = load_state()
    doc = build(gem, groups, epias_context(), exclude=load_exclude(), kap=kap)
    try:
        doc["gem"]["newer"] = gem_watch(gem)
    except Exception as e:                                                   # noqa: BLE001
        log.warning("GEM sürüm kontrolü: %s", e)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kurulu_guc.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    append_history(doc)
    log.info("Enerji: %d ünite, %d sahip/grup, Türkiye %.0f MW (EPİAŞ bağlamı: %s)", len(doc["units"]), len(doc["groups"]),
             doc["national"]["total"], "var" if doc["epias"] else "yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
