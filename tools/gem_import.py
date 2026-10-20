"""Global Energy Monitor (GEM) verisinden enerji sekmesinin santral envanterini çıkarır → config/enerji/gem_tr.json.

Elle çalıştırılır (GEM yılda ~2 kez günceller; dosyalar form ile indirilir, repoya konmaz):
  python tools/gem_import.py --gipt Global_Integrated_Power_….xlsx --ownership Global-Energy-Ownership-Tracker-….xlsx

- Global Integrated Power Tracker (GIPT): tüm kaynaklar (güneş, rüzgâr, hidro, jeotermal, kömür, petrol/gaz, biyoenerji,
  nükleer) tek tabloda; ülke, koordinat, il, sahip(ler) ve ana ortak(lar) payıyla.
  · Türkiye'deki tüm üniteler
  · Türkiye dışındaki üniteler: sahiplerinden ya da ana ortaklarından biri Türkiye'de kayıtlı bir şirketse
    (Türk gruplarının yurt dışı yatırımları; Türkiye toplamlarına katılmaz)
- Ownership Tracker: kömür, gaz ve biyoenerji ünitelerinde tam sahiplik zinciri (santrale en yakın eşleşen grup için)
  ve şirketlerin kayıt ülkesi.
Lisans: GEM verisi CC BY 4.0 — panelde kaynak gösterilir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import openpyxl

TR = {"Türkiye", "Turkey", "Turkiye"}
KEEP = {"operating", "construction", "pre-construction", "announced", "mothballed", "pre-permit", "permitted"}
OUT = Path(__file__).resolve().parent.parent / "config" / "enerji" / "gem_tr.json"
TYPE_KIND = {"utility-scale solar": "solar", "solar": "solar", "wind": "wind", "hydropower": "hydro", "geothermal": "geothermal",
             "coal": "coal", "oil/gas": "gas", "bioenergy": "bio", "nuclear": "nuclear"}

_WB: dict = {}


def rows(path, sheet):
    if path not in _WB:
        _WB[path] = openpyxl.load_workbook(path, read_only=True, data_only=True)
    it = _WB[path][sheet].iter_rows(values_only=True)
    hdr = [str(h).strip() if h else None for h in next(it)]
    for r in it:
        yield {k: v for k, v in zip(hdr, r) if k and v not in (None, "")}


def status(s) -> str | None:
    base = str(s or "").strip().lower().split(" - ")[0].strip()
    return base if base in KEEP else None


def num(v):
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def year(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# Santral adlarını Türkçeleştir ("Ataturk hydroelectric plant" → "Atatürk HES"); GEM'in yerel adı varsa o kullanılır
TR_NAME = [(r"\bhydroelectric (power )?(plant|station|project)\b", "HES"), (r"\bpumped storage (plant|station)\b", "Pompaj Depolamalı HES"),
           (r"\bwind (farm|power plant|power station|project)\b", "RES"), (r"\bsolar (farm|project|power plant|power station|plant|park)\b", "GES"),
           (r"\bgeothermal (power )?(plant|station|project)\b", "JES"), (r"\bnuclear power (plant|station)\b", "Nükleer Santrali"),
           (r"\bcombined cycle (gas turbine )?power (plant|station)\b", "Kombine Çevrim Santrali"),
           (r"\bpower (station|plant)\b", "Santrali"), (r"\bbiomass (power )?(plant|station)\b", "Biyokütle Santrali"),
           (r"\bbiogas (power )?(plant|station)\b", "Biyogaz Santrali"), (r"\blandfill gas (power )?(plant|station)\b", "Çöp Gazı Santrali")]
FIX = {"Ataturk": "Atatürk", "Ilisu": "Ilısu", "Hasan Ugurlu": "Hasan Uğurlu", "Ozluce": "Özlüce", "Yusufeli": "Yusufeli", "Bogazkale": "Boğazkale"}


def tr_name(name: str) -> str:
    n = name.strip()
    for rx, rep in TR_NAME:
        n = re.sub(rx, rep, n, flags=re.I)
    for a, b in FIX.items():
        n = re.sub(rf"\b{a}\b", b, n)
    return re.sub(r"\s+", " ", n).replace(" --", "").strip()


def ent_ids(s) -> list[str]:
    return re.findall(r"(E\d{9,})", str(s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gipt", required=True)
    ap.add_argument("--ownership", required=True)
    a = ap.parse_args()

    ents = {r["Entity ID"]: r for r in rows(a.ownership, "All Entities") if r.get("Entity ID")}
    tr_ent = lambda e: any((ents.get(e) or {}).get(k) in TR for k in ("Registration Country", "Headquarters Country"))
    # kömür/gaz/biyoenerji sahiplik zincirleri (ünite kimliğine göre)
    paths: dict[str, list[str]] = {}
    for sheet in ("Coal Plant Ownership", "Gas Plant Ownership", "Bioenergy Power Ownership"):
        for r in rows(a.ownership, sheet):
            uid, p = r.get("GEM unit ID"), str(r.get("Ownership Path") or "").strip()
            if uid and p and p not in paths.setdefault(uid, []):
                paths[uid].append(p)
    iso = {r.get("GEM Standard Country Name/Area"): r.get("ISO-alpha2 Code") for r in rows(a.gipt, "Regions, area, and countries")}

    units = []
    for r in rows(a.gipt, "Power facilities"):
        cc = r.get("Country/area")
        home = cc in TR
        if not home and not any(tr_ent(e) for e in ent_ids(r.get("Owner(s) GEM Entity ID")) + ent_ids(r.get("Parent(s) GEM Entity ID"))):
            continue
        st = status(r.get("Status"))
        mw = num(r.get("Capacity (MW)"))
        if not st or not mw:
            continue
        kind = TYPE_KIND.get(str(r.get("Type") or "").lower(), "bio")
        fuel = str(r.get("Fuel (combustion only)") or "").lower()
        if kind == "gas" and fuel.startswith("fossil liquids") and "gas" not in fuel:
            kind = "oil"
        en = str(r.get("Plant / Project name") or "").strip()
        local = str(r.get("Plant / Project name (local)") or "").strip()
        ph = str(r.get("Unit / Phase name") or "").strip()
        uid = r.get("GEM unit/phase ID")
        u = {"k": kind, "n": local if home and local else tr_name(en), "en": en, "ph": ph if ph and ph != "--" else None, "mw": mw, "st": st,
             "y": year(r.get("Start year")), "prov": r.get("Subnational unit (state, province)"), "city": r.get("City") or r.get("Local area (taluk, county)"),
             "cc": None if home else cc, "iso": None if home else iso.get(cc), "lat": num(r.get("Latitude")), "lon": num(r.get("Longitude")),
             "acc": r.get("Location accuracy"), "own": r.get("Owner(s)"), "par": r.get("Parent(s)"), "op": r.get("Operator(s)"),
             "tech": r.get("Technology"), "fuel": r.get("Fuel (combustion only)"), "paths": paths.get(uid), "id": uid, "loc": r.get("GEM location ID"),
             "lic": r.get("Other IDs (location)"), "url": r.get("GEM.Wiki URL")}
        units.append({k: v for k, v in u.items() if v not in (None, "", [])})
    src = {"gipt": Path(a.gipt).name, "ownership": Path(a.ownership).name}
    doc = {"imported": dt.date.today().isoformat(), "sources": src, "license": "Global Energy Monitor, CC BY 4.0", "units": units}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    by: dict[str, float] = {}
    for u in units:
        if u["st"] == "operating" and not u.get("cc"):
            by[u["k"]] = by.get(u["k"], 0) + u["mw"]
    print(len(units), "ünite (", sum(1 for u in units if u.get("cc")), "yurt dışı);", {k: round(v) for k, v in by.items()}, "MW Türkiye'de işletmede ->", OUT)


if __name__ == "__main__":
    main()
