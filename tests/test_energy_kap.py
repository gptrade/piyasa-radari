import datetime as dt

from radar import energy, energy_kap


def row(subject, summary, codes="AKSEN"):
    return {"subject": subject, "summary": summary, "stockCodes": codes, "disclosureIndex": 1, "publishDate": "21.09.2026 09:38:17"}


def test_candidate_filter():
    en = {"AKSEN", "AKENR"}
    assert energy_kap.candidate(row("Özel Durum Açıklaması (Genel)", "Van ili Zümrüt Depolamalı Güneş Enerjisi Santrali Üretim Lisansının EPDK Onayı"), en)
    assert not energy_kap.candidate(row("Pay Bazında Devre Kesici Bildirimi", "AKSEN.E işlem sırasında devreye girmiştir"), en)
    assert not energy_kap.candidate(row("Özel Durum Açıklaması (Genel)", "Yatırımcı Tazmin Merkezine Başvuru"), en)
    # enerji dışı şirket: yalnız güçlü ifade
    assert energy_kap.candidate(row("Özel Durum Açıklaması (Genel)", "Fabrika çatısına 5 MWp GES kurulumu", "KRDMD"), en)
    assert not energy_kap.candidate(row("Özel Durum Açıklaması (Genel)", "Yeni kapasite artışı yatırımı", "KRDMD"), en)


def test_rule_events():
    ev = energy_kap.rule_events("Erzin GES 45,5 MWe / 58,2 MWp kapasiteli santralimizin geçici kabulü tamamlanmıştır.",
                                "Erzin Güneş Enerjisi Santrali'nin kabul işlemlerinin tamamlanarak üretime geçtiğinin kamuya açıklanmasıdır.")[0]
    assert ev["type"] == "devreye_alma" and ev["source"] == "gunes" and ev["mw"] == 45.5 and ev["mwp"] == 58.2
    ev = energy_kap.rule_events("Toplam 1.250 MWm kurulu güç için önlisans alınmıştır.", "Divriği RES önlisans")[0]
    assert ev["type"] == "onlisans" and ev["source"] == "ruzgar" and ev["mw"] == 1250


def test_clean_events_drops_bad():
    out = energy_kap.clean_events([{"type": "lisans", "plant": "X GES", "source": "gunes", "mw": "12"}, {"type": "uydurma"}, "x"])
    assert len(out) == 1 and out[0]["mw"] is None and out[0]["country"] == "TR"


def test_tracker_asof_and_overlay():
    asof = energy.tracker_asof({"solar": "b0-Global-Solar-Power-Tracker-February-2026.xlsx", "ownership": "Global-Energy-Ownership-Tracker-September-2026-V2.xlsx"})
    assert asof["gunes"] == "2026-02-28" and asof["dogalgaz"] == "2026-09-30"
    groups = energy.load_groups()
    out = [{"key": "AKSEN", "name": "Aksa"}, {"key": "ENERJISA-URETIM", "name": "Enerjisa"}]
    kap = {"items": [
        {"date": "2026-05-15", "tickers": ["AKSEN"], "events": [{"type": "devreye_alma", "plant": "X GES", "source": "gunes", "mw": 50, "country": "TR"}]},
        {"date": "2026-01-15", "tickers": ["AKSEN"], "events": [{"type": "devreye_alma", "plant": "Y GES", "source": "gunes", "mw": 20, "country": "TR"}]},
        {"date": "2026-06-01", "tickers": ["AKSEN"], "events": [{"type": "lisans", "plant": "Z RES", "source": "ruzgar", "mw": 100, "country": "TR"}]},
        {"date": "2026-07-01", "tickers": ["AKSEN"], "events": [{"type": "lisans", "plant": "Z RES", "source": "ruzgar", "mw": 120, "country": "TR"}]},
        {"date": "2026-08-01", "tickers": ["AKSEN"], "events": [{"type": "devreye_alma", "plant": "Gana", "source": "dogalgaz", "mw": 300, "country": "Gana"}]},
        {"date": "2026-09-01", "tickers": ["SAHOL"], "events": [{"type": "lisans", "plant": "Q RES", "source": "ruzgar", "mw": 40, "country": "TR"}]},
    ]}
    rows = energy.kap_overlay(kap, out, groups, asof)
    assert out[0]["kap_added"] == 50                 # şubat sonrası; ocak eklemesi GEM'de, Gana yurt dışı
    assert out[0]["kap_pipe"] == 120                 # aynı santral: son bildirim
    assert out[1]["kap_pipe"] == 40                  # SAHOL → Enerjisa Üretim
    assert rows[0]["date"] == "2026-09-01" and len(rows) == 6
