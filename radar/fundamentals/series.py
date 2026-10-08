"""Ham KAP raporlarından standart kalem serileri: kümülatif, çeyreklik, son 12 ay (12A), bilanço.

Birim kuralı: her dönemin değeri **o dönem sonunun TL'si** cinsindendir (TMS 29 raporları zaten
dönem sonu alım gücüyle yayımlanır). Farklı dönemlerden gelen tutarlar birleştirilirken TÜFE
oranıyla aynı birime çekilir. Reel (ör. "2026/06 TL") gösterim için ön yüz her değeri
TÜFE(baz) / TÜFE(dönem sonu) ile çarpar.

Kalem eşleme, KAP'ın TFRS şablonundaki kalem adlarına dayanır (büyük/küçük harf duyarsız).
"""
from __future__ import annotations

import re
from datetime import date

# kalem → (tablo, [olası KAP adları]); ilk bulunan alınır
BS_ITEMS = {
    "cash": ["Nakit ve Nakit Benzerleri"],
    "st_fin_inv": ["Finansal Yatırımlar"],
    "receivables": ["Ticari Alacaklar"],
    "inventories": ["Stoklar"],
    "current_assets": ["TOPLAM DÖNEN VARLIKLAR", "Dönen Varlıklar"],
    "noncurrent_assets": ["TOPLAM DURAN VARLIKLAR", "Duran Varlıklar"],
    "total_assets": ["TOPLAM VARLIKLAR"],
    "ppe": ["Maddi Duran Varlıklar"],
    "intangibles": ["Maddi Olmayan Duran Varlıklar"],
    "inv_property": ["Yatırım Amaçlı Gayrimenkuller"],
    "st_borrowings": ["Kısa Vadeli Borçlanmalar"],
    "lt_borrowings_cur": ["Uzun Vadeli Borçlanmaların Kısa Vadeli Kısımları"],
    "lt_borrowings": ["Uzun Vadeli Borçlanmalar"],
    "payables": ["Ticari Borçlar"],
    "current_liab": ["TOPLAM KISA VADELİ YÜKÜMLÜLÜKLER", "Kısa Vadeli Yükümlülükler"],
    "noncurrent_liab": ["TOPLAM UZUN VADELİ YÜKÜMLÜLÜKLER", "Uzun Vadeli Yükümlülükler"],
    "total_liab": ["TOPLAM YÜKÜMLÜLÜKLER"],
    "equity_parent": ["Ana Ortaklığa Ait Özkaynaklar"],
    "minority": ["Kontrol Gücü Olmayan Paylar"],
    "equity_total": ["TOPLAM ÖZKAYNAKLAR", "Özkaynaklar"],
    "paid_capital": ["Ödenmiş Sermaye"],
    "treasury": ["Geri Alınmış Paylar (-)"],
    "retained": ["Geçmiş Yıllar Karları veya Zararları"],
}
IS_ITEMS = {
    "revenue": ["Hasılat"],
    "cogs": ["Satışların Maliyeti"],
    "gross": ["BRÜT KAR (ZARAR)", "TİCARİ FAALİYETLERDEN BRÜT KAR (ZARAR)"],
    "gna": ["Genel Yönetim Giderleri"],
    "selling": ["Pazarlama Giderleri", "Pazarlama, Satış ve Dağıtım Giderleri"],
    "rnd": ["Araştırma ve Geliştirme Giderleri"],
    "other_op_inc": ["Esas Faaliyetlerden Diğer Gelirler"],
    "other_op_exp": ["Esas Faaliyetlerden Diğer Giderler"],
    "op_profit": ["ESAS FAALİYET KARI (ZARARI)"],
    "equity_pickup": ["Özkaynak Yöntemiyle Değerlenen Yatırımların Karlarından (Zararlarından) Paylar"],
    "inv_inc": ["Yatırım Faaliyetlerinden Gelirler"],
    "inv_exp": ["Yatırım Faaliyetlerinden Giderler"],
    "fin_inc": ["Finansman Gelirleri"],
    "fin_exp": ["Finansman Giderleri"],
    "monetary": ["Net Parasal Pozisyon Kazançları (Kayıpları)"],
    "pretax": ["SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ KARI (ZARARI)"],
    "tax": ["Sürdürülen Faaliyetler Vergi (Gideri) Geliri"],
    "net": ["DÖNEM KARI (ZARARI)"],
    "net_parent": ["Ana Ortaklık Payları"],
}
CF_ITEMS = {
    "da": ["Amortisman ve İtfa Gideri İle İlgili Düzeltmeler"],
    "cfo": ["İŞLETME FAALİYETLERİNDEN NAKİT AKIŞLARI"],
    "cfi": ["YATIRIM FAALİYETLERİNDEN KAYNAKLANAN NAKİT AKIŞLARI"],
    "cff": ["FİNANSMAN FAALİYETLERİNDEN NAKİT AKIŞLARI"],
    "dividends_paid": ["Ödenen Temettüler"],
    "interest_paid": ["Ödenen Faiz"],
    "tax_paid": ["Vergi İadeleri (Ödemeleri)"],
}
# Yatırım harcaması: birden çok satırın toplamı (satır yoksa 0)
CAPEX_ROWS = ["Maddi ve Maddi Olmayan Duran Varlıkların Alımından Kaynaklanan Nakit Çıkışları",
              "Maddi Duran Varlık Alımından Kaynaklanan Nakit Çıkışları",
              "Maddi Olmayan Duran Varlık Alımından Kaynaklanan Nakit Çıkışları",
              "Yatırım Amaçlı Gayrimenkul Alımından Kaynaklanan Nakit Çıkışları"]
FLOW_KEYS = list(IS_ITEMS) + ["ebitda"] + list(CF_ITEMS) + ["capex", "fcf"]

# ---- Banka (BDDK tek düzen; TFRS 9) ----
BANK_BS = {
    "cash": ["Nakit ve Nakit Benzerleri"],
    "loans": ["Krediler"],
    "total_assets": ["VARLIKLAR TOPLAMI"],
    "deposits": ["MEVDUAT"],
    "borrowings": ["ALINAN KREDİLER"],
    "money_market": ["PARA PİYASALARINA BORÇLAR"],
    "securities_issued": ["İHRAÇ EDİLEN MENKUL KIYMETLER (Net)"],
    "subordinated": ["SERMAYE BENZERİ BORÇLANMA ARAÇLARI"],
    "equity_total": ["ÖZKAYNAKLAR"],
    "minority": ["Azınlık Payları"],
    "paid_capital": ["Ödenmiş Sermaye"],
    "total_liab_eq": ["YÜKÜMLÜLÜKLER TOPLAMI"],
}
BANK_IS = {
    "int_inc": ["FAİZ GELİRLERİ"],
    "loan_int": ["Kredilerden Alınan Faizler"],
    "int_exp": ["FAİZ GİDERLERİ (-)", "FAİZ GİDERLERİ"],
    "deposit_int": ["Mevduata Verilen Faizler"],
    "nii": ["NET FAİZ GELİRİ VEYA GİDERİ", "NET FAİZ GELİRİ/GİDERİ"],
    "fees": ["NET ÜCRET VE KOMİSYON GELİRLERİ VEYA GİDERLERİ", "NET ÜCRET VE KOMİSYON GELİRLERİ/GİDERLERİ"],
    "div_inc": ["TEMETTÜ GELİRLERİ"],
    "trading": ["TİCARİ KAR VEYA ZARAR (Net)", "TİCARİ KÂR/ZARAR (Net)"],
    "other_inc": ["DİĞER FAALİYET GELİRLERİ"],
    "revenue": ["FAALİYET BRÜT KÂRI", "FAALİYET BRÜT KARI", "FAALİYET BRÜT KÂRI (ZARARI)", "FAALİYET BRÜT KARI (ZARARI)"],
    "ecl": ["BEKLENEN ZARAR KARŞILIKLARI GİDERLERİ ( - )", "BEKLENEN ZARAR KARŞILIKLARI GİDERLERİ (-)", "BEKLENEN ZARAR KARŞILIKLARI GİDERLERİ*"],
    "other_prov": ["DİĞER KARŞILIK GİDERLERİ ( - )", "DİĞER KARŞILIK GİDERLERİ*"],
    "personnel": ["PERSONEL GİDERLERİ (-)", "PERSONEL GİDERLERİ*"],
    "other_opex": ["DİĞER FAALİYET GİDERLERİ (-)", "DİĞER FAALİYET GİDERLERİ*"],
    "op_profit": ["NET FAALİYET KARI (ZARARI)", "NET FAALİYET KÂRI (ZARARI)", "NET FAALİYET KARI/ZARARI"],
    "monetary": ["NET PARASAL POZİSYON KARI (ZARARI)"],
    "pretax": ["SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ KARI (ZARARI)", "SÜRDÜRÜLEN FAALİYETLER VERGİ ÖNCESİ K/Z*"],
    "tax": ["SÜRDÜRÜLEN FAALİYETLER VERGİ KARŞILIĞI (+/-)", "SÜRDÜRÜLEN FAALİYETLER VERGİ KARŞILIĞI*"],
    "net": ["DÖNEM NET KARI VEYA ZARARI", "DÖNEM NET KARI (ZARARI)", "DÖNEM NET KÂRI (ZARARI)"],
    "net_parent": ["Grubun Karı (Zararı)", "Grubun Kârı (Zararı)", "Ana Ortaklık Payları"],
}
BANK_CF = {
    "cfo": ["Bankacılık Faaliyetlerinden Kaynaklanan Net Nakit Akışı"],
    "dividends_paid": ["Temettü Ödemeleri"],
}

# ---- Sigorta (SEDDK tek düzen) ----
INS_BS = {
    "cash": ["NAKİT VE NAKİT BENZERİ VARLIKLAR"],
    "fin_assets": ["FİNANSAL VARLIKLAR İLE RİSKİ SİGORTALILARA AİT FİNANSAL YATIRIMLAR"],
    "receivables": ["ESAS FAALİYETLERDEN ALACAKLAR"],
    "current_assets": ["CARİ VARLIKLAR TOPLAMI"],
    "total_assets": ["TOPLAM VARLIKLAR"],
    "current_liab": ["KISA VADELİ YÜKÜMLÜLÜKLER TOPLAMI"],
    "tech_reserves": ["ΣSİGORTACILIK TEKNİK KARŞILIKLARI"],
    "fin_debt": ["ΣFİNANSAL BORÇLAR"],
    "equity_total": ["ÖZSERMAYE TOPLAMI"],
    "minority": ["AZINLIK PAYLARI"],
    "paid_capital": ["ÖDENMİŞ SERMAYE"],
}
INS_IS = {
    "revenue": ["ΣBrüt Yazılan Primler (+)"],
    "ceded": ["ΣReasüröre Devredilen Primler (-)"],
    "net_earned": ["ΣKazanılmış Primler (Reasürör Payı Düşülmüş Olarak)"],
    "claims": ["ΣGerçekleşen Tazminatlar (Reasürör Payı Düşülmüş Olarak) (+/-)", "ΣGerçekleşen Tazminatlar (Reasürör Payı Düşülmüş Olarak)"],
    "opex": ["ΣFaaliyet Giderleri (-)"],
    "other_tech_exp": ["ΣDiğer Teknik Giderler (-)"],
    "tech_balance": ["GENEL TEKNİK BÖLÜM DENGESİ"],
    "nonlife_balance": ["TEKNİK BÖLÜM DENGESİ - HAYAT DIŞI"],
    "inv_inc": ["YATIRIM GELİRLERİ"],
    "inv_exp": ["YATIRIM GİDERLERİ (-)"],
    "pretax": ["Dönem Karı veya Zararı"],
    "net": ["DÖNEM NET KARI VEYA ZARARI"],
    "net_parent": ["Ana Ortaklık Payları"],
}
INS_CF = {
    "cfo": ["Esas Faaliyetlerden Kaynaklanan Net Nakit"],
    "dividends_paid": ["Ödenen Temettüler (-)", "Ödenen Temettüler"],
}
TEMPLATES = {
    "sanayi": (BS_ITEMS, IS_ITEMS, CF_ITEMS),
    "banka": (BANK_BS, BANK_IS, BANK_CF),
    "sigorta": (INS_BS, INS_IS, INS_CF),
}
EXTRA_BS = {"sanayi": ["fin_debt", "net_debt"], "banka": ["equity_parent"], "sigorta": ["equity_parent"]}


def flow_keys(tmpl: str) -> list[str]:
    if tmpl not in ("banka", "sigorta"):
        return FLOW_KEYS
    _, inc, cf = TEMPLATES[tmpl]
    return list(inc) + list(cf) + (["opex"] if tmpl == "banka" else [])


def tms29(rep: dict) -> bool:
    """Rapor enflasyon muhasebesiyle mi (TMS 29)? Parasal pozisyon satırı sıfırdan farklıysa evet."""
    for label, vals in (rep.get("is") or {}).get("rows", {}).items():
        if "parasal pozisyon" in _norm(label) and any(v for v in vals if v):
            return True
    return False


def _norm(s: str) -> str:
    s = s.replace("İ", "i").replace("I", "ı").lower()
    s = s.replace("â", "a").replace("î", "i").replace("û", "u")
    return re.sub(r"\s+", " ", s).strip()


class _Idx:
    """Kalem adı → değerler. İlk geçen esas alınır; 'Σad' tüm tekrarların toplamı, 'ad*' önek eşlemesi."""

    def __init__(self, rows: dict):
        self.first: dict[str, list] = {}
        self.all: dict[str, list[list]] = {}
        for label, vals in rows.items():
            n = _norm(label.split("#")[0])
            self.all.setdefault(n, []).append(vals)
            if "#" not in label:
                self.first.setdefault(n, vals)

    def get(self, name: str, col: int):
        if name.startswith("Σ"):
            vs = [v[col] for v in self.all.get(_norm(name[1:]), []) if col < len(v) and v[col] is not None]
            return sum(vs) if vs else None
        if name.endswith("*"):
            pref = _norm(name[:-1])
            for k, v in self.first.items():
                if k.startswith(pref) and col < len(v) and v[col] is not None:
                    return v[col]
            return None
        v = self.first.get(_norm(name))
        return v[col] if v is not None and col < len(v) else None


def _index(rows: dict) -> "_Idx":
    return _Idx(rows)


def _pick(idx: "_Idx", names: list[str], col: int):
    for n in names:
        v = idx.get(n, col)
        if v is not None:
            return v
    return None


def _col(cols: list[dict], *, prior: bool, quarter: bool) -> int | None:
    """Kümülatif sütun = en uzun süreli; 3 aylık sütun = kümülatiften kısa, 3 aylık olan."""
    cand = []
    for i, c in enumerate(cols):
        if bool(c.get("prior")) != prior or not c.get("start"):
            continue
        s, e = date.fromisoformat(c["start"]), date.fromisoformat(c["end"])
        cand.append((i, (e.year - s.year) * 12 + e.month - s.month + 1))
    if not cand:
        return None
    longest = max(m for _, m in cand)
    if quarter:
        return next((i for i, m in cand if m == 3 and m < longest), None)
    return next(i for i, m in cand if m == longest)


def flows(rep: dict, *, prior: bool = False, quarter: bool = False, tmpl: str = "sanayi") -> dict | None:
    """Raporun kümülatif ya da 3 aylık akış kalemleri (TL). Sütun yoksa None."""
    if tmpl in ("banka", "sigorta"):
        return _fin_flows(rep, prior=prior, quarter=quarter, tmpl=tmpl)
    inc, cf = rep.get("is") or {}, rep.get("cf") or {}
    ci = _col(inc.get("cols", []), prior=prior, quarter=quarter)
    if ci is None:
        return None
    scale = rep.get("scale", 1)
    ii = _index(inc.get("rows", {}))
    out = {k: _pick(ii, names, ci) for k, names in IS_ITEMS.items()}
    exp = [out.get(k) for k in ("gna", "selling", "rnd")]
    if out.get("gross") is not None:
        out["_opex"] = sum(v for v in exp if v is not None)
    if not quarter and cf:       # nakit akışında 3 aylık sütun yok
        cc = _col(cf.get("cols", []), prior=prior, quarter=False)
        if cc is not None:
            ci2 = _index(cf.get("rows", {}))
            for k, names in CF_ITEMS.items():
                out[k] = _pick(ci2, names, cc)
            caps = [_pick(ci2, [n], cc) for n in CAPEX_ROWS]
            out["capex"] = sum(v for v in caps if v is not None)
    out = {k: (v * scale if isinstance(v, (int, float)) else v) for k, v in out.items()}
    _derive(out)
    return out


def _derive(out: dict) -> None:
    # FAVÖK = brüt kar − genel yönetim − pazarlama − Ar-Ge + amortisman (esas faaliyetlerden diğer gelir/gider hariç)
    if out.get("gross") is not None and out.get("da") is not None:
        out["ebitda"] = out["gross"] + out.get("_opex", 0) + out["da"]
    if out.get("cfo") is not None and out.get("capex") is not None:
        out["fcf"] = out["cfo"] + out["capex"]
    out.pop("_opex", None)


def _fin_flows(rep: dict, *, prior: bool, quarter: bool, tmpl: str) -> dict | None:
    _, inc_map, cf_map = TEMPLATES[tmpl]
    inc, cf = rep.get("is") or {}, rep.get("cf") or {}
    ci = _col(inc.get("cols", []), prior=prior, quarter=quarter)
    if ci is None:
        return None
    scale = rep.get("scale", 1)
    ii = _index(inc.get("rows", {}))
    out = {k: _pick(ii, names, ci) for k, names in inc_map.items()}
    if not quarter and cf:
        cc = _col(cf.get("cols", []), prior=prior, quarter=False)
        if cc is not None:
            ci2 = _index(cf.get("rows", {}))
            for k, names in cf_map.items():
                out[k] = _pick(ci2, names, cc)
    if tmpl == "banka":
        if out.get("net_parent") is None:
            out["net_parent"] = out.get("net")
        if out.get("personnel") is not None or out.get("other_opex") is not None:
            out["opex"] = (out.get("personnel") or 0) + (out.get("other_opex") or 0)
    elif out.get("net_parent") is None:
        out["net_parent"] = out.get("net")
    return {k: (v * scale if isinstance(v, (int, float)) else v) for k, v in out.items()}


def balance(rep: dict, tmpl: str = "sanayi") -> dict:
    if tmpl in ("banka", "sigorta"):
        bs = rep.get("bs") or {}
        cols = bs.get("cols", [])
        ci = next((i for i, c in enumerate(cols) if not c.get("prior")), 0)
        idx = _index(bs.get("rows", {}))
        scale = rep.get("scale", 1)
        out = {k: _pick(idx, names, ci) for k, names in TEMPLATES[tmpl][0].items()}
        out = {k: (v * scale if v is not None else None) for k, v in out.items()}
        if out.get("equity_total") is not None:
            out["equity_parent"] = out["equity_total"] - (out.get("minority") or 0)
        return out
    bs = rep.get("bs") or {}
    cols = bs.get("cols", [])
    ci = next((i for i, c in enumerate(cols) if not c.get("prior")), 0)
    idx = _index(bs.get("rows", {}))
    scale = rep.get("scale", 1)
    out = {k: _pick(idx, names, ci) for k, names in BS_ITEMS.items()}
    out = {k: (v * scale if v is not None else None) for k, v in out.items()}
    debt = [out.get(k) for k in ("st_borrowings", "lt_borrowings_cur", "lt_borrowings")]
    out["fin_debt"] = sum(v for v in debt if v is not None) if any(v is not None for v in debt) else None
    if out["fin_debt"] is not None:
        out["net_debt"] = out["fin_debt"] - (out.get("cash") or 0) - (out.get("st_fin_inv") or 0)
    return out


def _end_month(pk: str) -> str:
    y, m = pk.split("/")
    return f"{y}-{m}"


def _ratio(cpi: dict, to_pk: str, from_pk: str, currency: str, nominal: bool = False) -> float:
    if currency != "TRY" or nominal:
        return 1.0
    a, b = cpi.get(_end_month(to_pk)), cpi.get(_end_month(from_pk))
    return a / b if a and b else 1.0


def _prev_pk(pk: str) -> str:
    y, m = map(int, pk.split("/"))
    return f"{y}/{m - 3:02d}" if m > 3 else f"{y - 1}/12"


def _sub(a: dict | None, b: dict | None, r: float, keys=None) -> dict | None:
    if not a or not b:
        return None
    return {k: (a[k] - b[k] * r) if a.get(k) is not None and b.get(k) is not None else None for k in (keys or FLOW_KEYS)}


def _add(a: dict, b: dict, c: dict, r: float, keys=None) -> dict:
    """a + b·r − c   (12A = bu yıl kümülatif + geçen yıl tamamı − geçen yıl aynı dönem)."""
    return {k: (a[k] + b[k] * r - c[k]) if None not in (a.get(k), b.get(k), c.get(k)) else None for k in (keys or FLOW_KEYS)}


def build(doc: dict, cpi: dict[str, float]) -> dict:
    """Şirket dosyasından sütun tabanlı seriler: {'periods': [...], 'cum': {kalem: [...]}, 'q':..., 'ttm':..., 'bs':...}."""
    reps = doc.get("reports", {})
    pks = sorted(pk for pk, r in reps.items() if r.get("is"))
    cur = doc.get("currency") or "TRY"
    tmpl = doc.get("template") if doc.get("template") in TEMPLATES else "sanayi"
    keys = flow_keys(tmpl)
    adj = {pk: tms29(reps[pk]) for pk in pks}           # TMS 29 yoksa dönemler nominal: TÜFE oranı uygulanmaz
    cum, cum_prev, q, ttm, bs = {}, {}, {}, {}, {}
    for pk in pks:
        rep = reps[pk]
        cum[pk] = flows(rep, tmpl=tmpl)
        cum_prev[pk] = flows(rep, prior=True, tmpl=tmpl)
        bs[pk] = balance(rep, tmpl)
        month = int(pk.split("/")[1])
        if month == 3:
            q[pk] = cum[pk]
        else:
            q3 = flows(rep, quarter=True, tmpl=tmpl)
            prev = _prev_pk(pk)
            diff = _sub(cum[pk], cum.get(prev), _ratio(cpi, pk, prev, cur, not adj[pk]), keys)
            # Gelir tablosu için raporun kendi 3 aylık sütunu, nakit akışı için fark
            q[pk] = {**(diff or {}), **{k: v for k, v in (q3 or {}).items() if v is not None}} if (q3 or diff) else None
            if q[pk] is not None and tmpl == "sanayi":
                _derive_q(q[pk], q3, diff)
    for pk in pks:
        month = int(pk.split("/")[1])
        if month == 12:
            ttm[pk] = cum[pk]
            continue
        fy = f"{int(pk[:4]) - 1}/12"
        if cum.get(pk) and cum.get(fy) and cum_prev.get(pk):
            ttm[pk] = _add(cum[pk], cum[fy], cum_prev[pk], _ratio(cpi, pk, fy, cur, not adj[pk]), keys)
        else:
            ttm[pk] = None
    flow_cols = lambda d: {k: [(_r(d[p].get(k)) if d.get(p) else None) for p in pks] for k in keys}  # noqa: E731
    return {
        "periods": pks,
        "cpi": [cpi.get(_end_month(p)) for p in pks],
        "cpi_ya": [cpi.get(_end_month(f"{int(p[:4]) - 1}/{p[5:]}")) for p in pks],   # yıllık enflasyon için
        "cum": flow_cols(cum),
        "cum_prev": flow_cols(cum_prev),
        "q": flow_cols(q),
        "ttm": flow_cols(ttm),
        "bs": {k: [_r(bs[p].get(k)) for p in pks] for k in list(TEMPLATES[tmpl][0]) + EXTRA_BS[tmpl]},
        "template": tmpl,
        "nominal": [not adj[p] for p in pks],
    }


def _derive_q(qd: dict, q3: dict | None, diff: dict | None) -> None:
    # FAVÖK'ün amortisman kısmı yalnız nakit akışından (farktan) gelir
    if q3 and diff and q3.get("gross") is not None and diff.get("da") is not None:
        opex = sum(q3.get(k) or 0 for k in ("gna", "selling", "rnd"))
        qd["ebitda"] = q3["gross"] + opex + diff["da"]


def _r(v):
    return round(v) if isinstance(v, float) else v
