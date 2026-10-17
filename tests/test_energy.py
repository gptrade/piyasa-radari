import datetime as dt
import json

from radar import energy


def test_norm_turkish_upper_and_punctuation():
    assert energy.norm("Zorlu Enerji Elektrik Üretim A.Ş.") == "ZORLU ENERJİ ELEKTRİK ÜRETİM A Ş"
    assert energy.norm("ışık  i̇") .startswith("IŞIK")


def test_classify_curated_and_auto():
    groups = energy.load_groups()
    assert energy.classify("ZORLU JEOTERMAL ENERJİ ELEKTRİK ÜRETİMİ A.Ş.", groups)[0] == "ZOREN"
    assert energy.classify("Elektrik Üretim A.Ş. Genel Müdürlüğü", groups)[1]["kind"] == "kamu"
    # önek tam kelime olmalı: "AKSAKAL ..." Aksa değildir
    assert energy.classify("AKSAKAL ENERJİ A.Ş.", groups)[0] == "auto:AKSAKAL"
    # genel ilk kelime: ilk iki kelime
    assert energy.classify("Anadolu Yeşil Elektrik A.Ş.", groups)[0] == "auto:ANADOLU YEŞİL"
    # unvan başka grupla başlamıyorsa "X ELEKTRİK ÜRETİM A.Ş." EÜAŞ sayılmaz
    assert energy.classify("Bolu Elektrik Üretim A.Ş.", groups)[0] == "auto:BOLU"


def test_capacity_takes_max_per_field():
    rows = [{"barajli": 100, "ruzgar": 20, "toplam": 120}, {"barajli": 80, "ruzgar": 50, "gunes": 0, "toplam": 130}]
    c = energy.capacity(rows)
    assert c == {"barajli": 100.0, "ruzgar": 50.0}
    assert energy.by_source({"barajli": 100.0, "akarsu": 10.0, "linyit": 5.0}) == {"hidro": 110.0, "komur": 5.0}


def test_fuel_source():
    assert energy.fuel_source("RÜZGAR") == "ruzgar"
    assert energy.fuel_source("Hidrolik (Barajlı)") == "hidro"
    assert energy.fuel_source("Doğal Gaz") == "dogalgaz"
    assert energy.fuel_source("Biyokütle") == "diger"


def test_build_groups_shares_and_additions(tmp_path):
    groups = energy.load_groups()
    orgs = [{"organizationId": 1, "organizationName": "ZORLU ENERJİ ELEKTRİK ÜRETİM A.Ş."},
            {"organizationId": 2, "organizationName": "ZORLU JEOTERMAL ENERJİ ELEKTRİK ÜRETİMİ A.Ş."},
            {"organizationId": 3, "organizationName": "LİMAK HİDROELEKTRİK SANTRAL YATIRIMLARI A.Ş."},
            {"organizationId": 4, "organizationName": "ABC TEDARİK A.Ş."}]          # üretimi yok → listede yok
    caps = {1: {"dogalgaz": 300.0, "ruzgar": 100.0}, 2: {"jeotermal": 200.0}, 3: {"barajli": 400.0}}
    national = {"dogalgaz": 600.0, "jeotermal": 200.0, "barajli": 800.0, "ruzgar": 400.0}
    adds = [{"geciciKabulTarihi": "2026-08-01T00:00:00+03:00", "sirketAdi": "Zorlu Jeotermal Enerji Elektrik Üretimi A.Ş.",
             "santralAdi": "Kızıldere IV JES", "yakitCinsi": "JEOTERMAL", "ilaveKuruluGuc": 25.5, "il": "Denizli"},
            {"geciciKabulTarihi": "2024-01-01T00:00:00+03:00", "sirketAdi": "LİMAK HİDROELEKTRİK SANTRAL YATIRIMLARI A.Ş.",
             "santralAdi": "X HES", "yakitCinsi": "BARAJ", "ilaveKuruluGuc": "12,5", "il": "Artvin"}]
    now = dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc)
    doc = energy.build(orgs, caps, adds, national, groups, (dt.date(2026, 10, 11), dt.date(2026, 10, 17)), now)
    g = {x["key"]: x for x in doc["groups"]}
    assert g["ZOREN"]["total"] == 600.0 and g["ZOREN"]["src"] == {"dogalgaz": 300.0, "ruzgar": 100.0, "jeotermal": 200.0}
    assert g["ZOREN"]["orgs"] == [1, 2] and g["ZOREN"]["adds12"] == 25.5
    assert g["ZOREN"]["share"] == 0.3 and doc["listed_share"] == 0.3
    assert g["LİMAK"]["ticker"] is None and g["LİMAK"]["adds12"] == 0          # 2024 ekleme 12 ayın dışında
    assert doc["national"]["total"] == 2000.0 and doc["national"]["src"]["hidro"] == 800.0
    assert [a["org"] for a in doc["additions"]] == [2, 3] and doc["additions"][1]["mw"] == 12.5
    assert len(doc["orgs"]) == 3
    h = energy.append_history(doc, tmp_path / "h.json")
    h = energy.append_history(doc, tmp_path / "h.json")                       # aynı gün tekrar → tek kayıt
    assert len(h) == 1 and h[0]["g"]["ZOREN"] == 600.0
    json.dumps(doc)


def test_main_without_credentials_is_noop(monkeypatch):
    monkeypatch.delenv("EPIAS_USERNAME", raising=False)
    monkeypatch.delenv("EPIAS_PASSWORD", raising=False)
    assert energy.main() == 0
