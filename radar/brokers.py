"""Aracı kurum adlarını tek biçime indirme ve gönderici alan adından kurum tanıma.

Aynı kurum farklı yazımlarla gelebiliyor ("Ak Yatırım", "Ak Yatırım / Akbank", "AK YATIRIM MENKUL DEĞERLER A.Ş."):
rapor ve not listelerinde tek ad görünsün, konsensüs ve strateji özetleri kurum başına doğru sayılsın.
E-postayla iletilen raporlarda asıl gönderici alan adı (ör. @gedik.com.tr) kurum için ilk ipucudur.
"""
from __future__ import annotations

import re

# (kanonik ad, eşleşme deseni, alan adları)
BROKERS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Ak Yatırım", r"\bak\s*yat[ıi]r[ıi]m|\bak\s*invest|akbank", ("akyatirim.com.tr", "akbank.com")),
    ("Gedik Yatırım", r"\bgedik", ("gedik.com", "gedik.com.tr")),
    ("Kuveyt Türk Yatırım", r"kuveyt\s*t[üu]rk", ("kuveytturk.com.tr", "kuveytturkyatirim.com.tr")),
    ("Deniz Yatırım", r"\bdeniz\s*yat[ıi]r[ıi]m|denizbank\s*yat|denizinvest", ("denizyatirim.com", "denizbank.com", "denizinvest.com")),
    ("ÜNLÜ & Co", r"[üu]nl[üu]\s*(?:menkul|&|ve|co\b|yat)|unlu\s*&?\s*co|^[üu]nl[üu]$", ("unluco.com", "unlumenkul.com")),
    ("İş Yatırım", r"[iİı]ş\s*yat[ıi]r[ıi]m|is\s*yatirim|isyatirim", ("isyatirim.com.tr",)),
    ("Garanti BBVA Yatırım", r"garanti\s*bbva|garanti\s*yat", ("garantibbvayatirim.com.tr", "garantibbva.com.tr")),
    ("Yapı Kredi Yatırım", r"yap[ıi]\s*kredi", ("ykyatirim.com.tr", "yapikredi.com.tr")),
    ("QNB Yatırım", r"\bqnb", ("qnbyatirim.com", "qnbinvest.com.tr")),
    ("Halk Yatırım", r"\bhalk\s*yat|halkinvest", ("halkyatirim.com.tr",)),
    ("Ziraat Yatırım", r"ziraat\s*yat", ("ziraatyatirim.com.tr",)),
    ("Vakıf Yatırım", r"vak[ıi]f\s*yat", ("vakifyatirim.com.tr",)),
    ("Şeker Yatırım", r"[şs]eker\s*yat", ("sekeryatirim.com.tr",)),
    ("Tacirler Yatırım", r"tacirler", ("tacirler.com.tr",)),
    ("Info Yatırım", r"\binfo\s*yat", ("infoyatirim.com",)),
    ("A1 Capital", r"\ba1\s*capital", ("a1capital.com.tr",)),
    ("Ahlatcı Yatırım", r"ahlatc[ıi]", ("ahlatciyatirim.com.tr",)),
    ("Global Menkul", r"global\s*(?:menkul|yat)", ("global.com.tr", "globalmenkul.com.tr")),
    ("Osmanlı Yatırım", r"osmanl[ıi]\s*yat", ("osmanliyatirim.com.tr",)),
    ("İntegral Yatırım", r"[iİ]ntegral\s*yat", ("integralyatirim.com.tr",)),
    ("Oyak Yatırım", r"\boyak\s*yat", ("oyakyatirim.com.tr",)),
    ("Tera Yatırım", r"\btera\s*yat", ("terayatirim.com",)),
    ("Burgan Yatırım", r"\bburgan", ("burganyatirim.com.tr",)),
    ("Phillip Capital", r"phillip", ("phillipcapital.com.tr",)),
    ("Marbaş Menkul", r"marba[şs]", ("marbas.com",)),
    ("Bulls Yatırım", r"\bbulls\b", ("bullsyatirim.com",)),
    ("Gcm Yatırım", r"\bgcm\b", ("gcmyatirim.com.tr",)),
    ("Strateji Menkul", r"strateji\s*menkul", ("strateji.com.tr",)),
    ("Ata Yatırım", r"\bata\s*yat|ata\s*invest", ("atainvest.com",)),
    ("Hedef Yatırım", r"\bhedef\s*yat", ("hedefyatirim.com.tr",)),
    ("Destek Yatırım", r"\bdestek\s*yat", ("destekyatirim.com.tr",)),
    ("Meksa Yatırım", r"\bmeksa", ("meksa.com.tr",)),
    ("Pusula Yatırım", r"\bpusula\s*yat", ("pusulayatirim.com.tr",)),
    ("Capital Economics", r"capital\s*economics", ("capitaleconomics.com",)),
    ("Goldman Sachs", r"goldman", ("gs.com", "goldmansachs.com")),
    ("J.P. Morgan", r"j\.?\s*p\.?\s*morgan|jpmorgan", ("jpmorgan.com", "jpmchase.com")),
    ("Morgan Stanley", r"morgan\s*stanley", ("morganstanley.com",)),
    ("BlackRock", r"blackrock", ("blackrock.com",)),
    ("sentix", r"\bsentix", ("sentix.de",)),
]
_RX = [(name, re.compile(rx, re.I)) for name, rx, _ in BROKERS]
DOMAINS = {d: name for name, _, ds in BROKERS for d in ds}
UNKNOWN = "Kurum belirtilmemiş"
FOREIGN = {"Capital Economics", "Goldman Sachs", "J.P. Morgan", "Morgan Stanley", "BlackRock", "sentix"}
LOCAL = {n for n, _, _ in BROKERS} - FOREIGN          # Türk aracı kurumlar


def canon(name: str | None) -> str | None:
    """Kurum adını kanonik biçime çevir; tanınmıyorsa olduğu gibi (kırpılmış) bırak."""
    if not name:
        return name
    s = str(name).strip()
    for n, rx in _RX:
        if rx.search(s):
            return n
    return s[:60]


def from_domain(domain: str | None) -> str | None:
    """Gönderici alan adından kurum: alt alan adlarıyla da eşleşir (research.gedik.com.tr → Gedik Yatırım)."""
    d = (domain or "").lower().strip(". ")
    while d and "." in d:
        if d in DOMAINS:
            return DOMAINS[d]
        d = d.split(".", 1)[1]
    return None


def looks_like_domain(s: str | None) -> bool:
    return bool(s) and bool(re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", str(s).strip().lower()))
