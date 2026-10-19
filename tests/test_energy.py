import datetime as dt
import json

from radar import energy


def test_fold_turkish_and_punctuation():
    assert energy.fold("Aksa Enerji Üretim A.Ş.") == "AKSA ENERJI URETIM A S"
    assert energy.fold("İÇDAŞ Çelik") == energy.fold("Icdas Celik")


def test_match_group_prefix_word_boundary():
    groups = energy.load_groups()
    assert energy.match_group("Aksa Enerji Uretim AŞ", groups)["ticker"] == "AKSEN"
    assert energy.match_group("ZORLU JEOTERMAL ENERJİ ELEKTRİK ÜRETİMİ A.Ş.", groups)["ticker"] == "ZOREN"
    assert energy.match_group("Elektrik Uretim AS (EÜAŞ)", groups)["kind"] == "kamu"
    assert energy.match_group("Aksakal Enerji AŞ", groups) is None              # önek tam kelime olmalı
    assert energy.match_group("Bolu Elektrik Üretim AŞ", groups) is None        # "X Elektrik Üretim" EÜAŞ değil
    assert energy.match_group("Enerjisa Enerji Uretim AS", groups)["parent"] == "SAHOL"


def test_parse_owners_and_path():
    assert energy.parse_owners("A [60%]; B [40%]") == [("A", 0.6), ("B", 0.4)]
    assert energy.parse_owners("A; B") == [("A", 0.5), ("B", 0.5)]
    assert energy.parse_owners("A [50%]; B") == [("A", 0.5), ("B", 0.5)]
    nodes, pcts = energy.parse_path("Kişiler -> Kazancı Holding  [100.0%] -> Aksa Enerji Uretim AŞ [80.13%] -> Santral 1 [100.0%]")
    assert nodes == ["Kişiler", "Kazancı Holding", "Aksa Enerji Uretim AŞ", "Santral 1"]
    assert pcts[0] is None and [round(p, 4) for p in pcts[1:]] == [1.0, 0.8013, 1.0]


def test_assign_closest_group_in_chain_and_no_double_count():
    groups = energy.load_groups()
    unit = {"k": "gas", "n": "Santral 1", "mw": 430, "st": "operating", "paths": [
        "Aksa Enerji Uretim AŞ -> Santral 1 [100.0%]",
        "Kazancı Holding  -> Aksa Enerji Uretim AŞ [80.13%] -> Santral 1 [100.0%]",
        "natural person(s)  -> Kazancı Holding  [100.0%] -> Aksa Enerji Uretim AŞ [80.13%] -> Santral 1 [100.0%]",
        "small shareholder(s)  -> Aksa Enerji Uretim AŞ [19.87%] -> Santral 1 [100.0%]"]}
    out = energy.assign(unit, groups)
    assert [(o["key"], round(o["share"], 4)) for o in out] == [("AKSEN", 1.0)]
    # eşleşmeyen zincir: ortak en üst kurumsal düğüm, kişiler değil
    unit2 = {"k": "coal", "n": "X", "mw": 100, "st": "operating", "paths": [
        "natural person(s)  -> Foo Holding [100%] -> Foo Enerji AŞ [100%] -> X [100%]", "Foo Holding -> Foo Enerji AŞ [100%] -> X [100%]"]}
    out2 = energy.assign(unit2, groups)
    assert [(o["name"], o["share"]) for o in out2] == [("Foo Holding", 1.0)]
    # yenilenebilir: sahip alanı, ortak girişim
    out3 = energy.assign({"k": "hydro", "n": "Y HES", "mw": 200, "st": "operating", "own": "Özaltın Construction [50%]; Cengiz Construction [50%]"}, groups)
    assert sorted((o["name"], o["share"]) for o in out3) == [("Cengiz Holding", 0.5), ("Özaltın", 0.5)]


def test_build_equity_consolidated_pipeline_and_exclusion(tmp_path):
    groups = energy.load_groups()
    gem = {"imported": "2026-10-19", "units": [
        {"k": "hydro", "n": "Y HES", "mw": 200, "st": "operating", "y": 2025, "own": "Özaltın [50%]; Cengiz [50%]"},
        {"k": "wind", "n": "Z RES", "mw": 100, "st": "operating", "own": "Galata Wind Enerji AS [100%]"},
        {"k": "wind", "n": "Z RES 2", "mw": 50, "st": "construction", "own": "Galata Wind Enerji AS [100%]"},
        {"k": "solar", "n": "Sahipsiz GES", "mw": 30, "st": "operating"},
        {"k": "gas", "n": "Aksa Ghana HFO power plant 1", "mw": 370, "st": "operating", "paths": ["Aksa Enerji Uretim AŞ -> Aksa Ghana HFO power plant 1 [100%]"]},
    ]}
    now = dt.datetime(2026, 10, 19, tzinfo=dt.timezone.utc)
    doc = energy.build(gem, groups, None, now, exclude=energy.load_exclude())
    g = {x["key"]: x for x in doc["groups"]}
    assert doc["national"]["total"] == 330 and doc["national"]["unowned"] == 30 and doc["national"]["pipe_total"] == 50
    assert g["CENGIZ-HOLDING"]["total"] == 100 and g["CENGIZ-HOLDING"]["cons"] == 200     # %50: pay oranıyla 100, konsolide 200
    assert g["GWIND"]["total"] == 100 and g["GWIND"]["pipe_total"] == 50 and g["GWIND"]["ticker"] == "GWIND"
    assert "AKSEN" not in g                                                               # yurt dışı santral dışarıda
    assert doc["listed_share"] == round(100 / 330, 4)
    assert [r["n"] for r in doc["recent"]] == ["Y HES"]
    h = energy.append_history(doc, tmp_path / "h.json")
    h = energy.append_history(doc, tmp_path / "h.json")
    assert len(h) == 1
    json.dumps(doc)


def test_real_gem_file_builds():
    gem = json.loads(energy.GEM.read_text(encoding="utf-8"))
    doc = energy.build(gem, energy.load_groups(), exclude=energy.load_exclude())
    assert doc["national"]["total"] > 80000
    keys = {g["key"] for g in doc["groups"][:30]}
    assert {"EUAS", "ENKAI", "AKSEN"} <= keys
