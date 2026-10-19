"""Global Energy Monitor (GEM) izleyicilerinden Türkiye santral envanterini çıkarır → config/enerji/gem_tr.json.

Elle çalıştırılır (GEM yılda ~2 kez günceller; dosyalar form ile indirilir, repoya konmaz):
  python tools/gem_import.py --solar S.xlsx --wind W.xlsx --hydro H.xlsx [--nuclear N.xlsx] [--geothermal G.xlsx] \
                             --ownership Global-Energy-Ownership-Tracker.xlsx

- Güneş, rüzgâr, hidro, nükleer (ve varsa jeotermal): izleyicinin kendi satırları; sahip = "Owner" alanı ("A [60%]; B [40%]").
- Kömür, doğalgaz, biyoenerji: Ownership Tracker'ın santral sahiplik sayfaları; her ünite için tüm sahiplik
  zincirleri ("A -> B [80%] -> Santral [100%]") saklanır, gruplama radar/energy.py'de yapılır.
Lisans: GEM verisi CC BY 4.0 — panelde kaynak gösterilir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import openpyxl

TR = {"Türkiye", "Turkey", "Turkiye"}
KEEP = {"operating", "construction", "pre-construction", "announced", "mothballed", "pre-permit", "permitted"}
OUT = Path(__file__).resolve().parent.parent / "config" / "enerji" / "gem_tr.json"


_WB = {}


def sheets_of(path):
    if path not in _WB:
        _WB[path] = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return _WB[path].sheetnames


def rows(path, sheet):
    sheets_of(path)
    it = _WB[path][sheet].iter_rows(values_only=True)
    hdr = [str(h).strip() if h else None for h in next(it)]
    for r in it:
        yield {k: v for k, v in zip(hdr, r) if k and v not in (None, "")}


def status(s) -> str | None:
    s = str(s or "").strip().lower()
    base = s.split(" - ")[0].strip()
    return base if base in KEEP else None


def num(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def year(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def tracker_units(path, kind, sheets, ccol="Country/Area"):
    out = []
    for sh in [s for s in sheets if s in sheets_of(path)]:
        for r in rows(path, sh):
            if r.get(ccol) not in TR and r.get("Country/Area 2") not in TR:
                continue
            st = status(r.get("Status"))
            mw = num(r.get("Country/Area 1 Capacity (MW)") if r.get("Binational") == "yes" and r.get(ccol) in TR else r.get("Capacity (MW)"))
            if not st or not mw:
                continue
            name = str(r.get("Project Name") or "").strip()
            ph = r.get("Phase Name") or r.get("Unit Name")
            out.append({"k": kind, "n": name, "ph": str(ph) if ph not in (None, "", "--") else None, "mw": mw, "st": st,
                        "y": year(r.get("Start year") or r.get("Start Year")), "tech": r.get("Technology Type") or r.get("Installation Type") or r.get("Reactor Type"),
                        "own": str(r.get("Owner") or "").strip() or None, "op": str(r.get("Operator") or "").strip() or None,
                        "prov": r.get("State/Province") or r.get("State/Province 1") or r.get("Major area (prefecture, district)"),
                        "id": r.get("GEM phase ID") or r.get("GEM unit ID"), "loc": r.get("GEM location ID"),
                        "lic": r.get("Other IDs (location)"), "url": r.get("Wiki URL"), "below": sh == "Below Threshold" or None})
    return out


def ownership_units(path):
    ents = {r["Entity ID"]: r for r in rows(path, "All Entities") if r.get("Entity ID")}
    tr = lambda eid: any((ents.get(eid) or {}).get(k) in TR for k in ("Registration Country", "Headquarters Country"))
    out = {}
    for sheet, kind in (("Coal Plant Ownership", "coal"), ("Gas Plant Ownership", "gas"), ("Bioenergy Power Ownership", "bio")):
        for r in rows(path, sheet):
            if not tr(r.get("Immediate Project Owner GEM Entity ID")):
                continue
            st = status(r.get("Status"))
            mw = num(r.get("Capacity (MW)"))
            if not st or not mw:
                continue
            uid = r.get("GEM unit ID")
            u = out.setdefault(uid, {"k": kind, "n": str(r.get("Project") or "").strip(), "ph": None, "mw": mw, "st": st, "y": None,
                                     "imm": r.get("Immediate Project Owner"), "paths": [], "id": uid, "loc": r.get("GEM location ID")})
            p = str(r.get("Ownership Path") or "").strip()
            if p and p not in u["paths"]:
                u["paths"].append(p)
    return list(out.values())


def main():
    ap = argparse.ArgumentParser()
    for k in ("solar", "wind", "hydro", "nuclear", "geothermal", "ownership"):
        ap.add_argument("--" + k)
    a = ap.parse_args()
    units, src = [], {}
    if a.solar:
        units += tracker_units(a.solar, "solar", ["Utility-Scale (1 MW+)", "Data"]); src["solar"] = Path(a.solar).name
    if a.wind:
        units += tracker_units(a.wind, "wind", ["Data", "Below Threshold"]); src["wind"] = Path(a.wind).name
    if a.hydro:
        units += tracker_units(a.hydro, "hydro", ["Data", "Below Threshold"], "Country/Area 1"); src["hydro"] = Path(a.hydro).name
    if a.nuclear:
        units += tracker_units(a.nuclear, "nuclear", ["Data"]); src["nuclear"] = Path(a.nuclear).name
    if a.geothermal:
        units += tracker_units(a.geothermal, "geothermal", ["Data", "Below Threshold"]); src["geothermal"] = Path(a.geothermal).name
    if a.ownership:
        units += ownership_units(a.ownership); src["ownership"] = Path(a.ownership).name
    for u in units:
        for k in [k for k, v in u.items() if v in (None, [], "")]:
            del u[k]
    doc = {"imported": dt.date.today().isoformat(), "sources": src, "license": "Global Energy Monitor, CC BY 4.0", "units": units}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    by = {}
    for u in units:
        if u["st"] == "operating":
            by[u["k"]] = by.get(u["k"], 0) + u["mw"]
    print(len(units), "ünite;", {k: round(v) for k, v in by.items()}, "MW işletmede ->", OUT)


if __name__ == "__main__":
    main()
