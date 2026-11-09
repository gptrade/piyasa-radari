"""Haber temizliği: yeniden yayımlanmış eski haberler ve aynı olayın farklı kaynaklardaki kopyaları.

* is_stale(): başlıkta haberin yayın yılından en az iki yıl önceki bir tarih "olayın zamanı" olarak geçiyorsa
  (ör. "Cybertruck lansmanını Kasım 2023'e erteledi", "2024 ortasına kadar üretimi durduracak") haber eskidir.
  Karşılaştırma bağlamı ("2012'den beri", "since 2020", "rekor", birden çok yıl listesi) eski sayılmaz.
  Toplayıcılar (özellikle Marketaux) eski makaleleri yeni tarihle döndürebiliyor; AI ayrıca stale_news alanıyla işaretler.
* cluster(): aynı hisse(ler) için 72 saat içinde, kök kelimeleri büyük ölçüde örtüşen haberler tek kayıtta birleşir
  (kopya sayısı `dups`, kaynaklar `dup_sources`). AI'nin Türkçe başlığı varsa o karşılaştırılır: İngilizce ve Türkçe
  kaynaklar aynı olayı anlatıyorsa yakalanır.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta

from .models import parse_iso

YEAR = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")
# Karşılaştırma / tarihsel bağlam: bu kelimeler varsa eski yıl olayın zamanı değildir
CONTEXT = re.compile(
    r"\b(since|beri|bu yana|ilk kez|first|record|rekor|highest|lowest|worst|best|en (yüksek|düşük|kötü|iyi|büyük)|"
    r"unseen|görülmemiş|like|gibi|benzer|compared|kıyasla|beat|aştı|geride|vs\.?|versus|anniversary|yıl dönümü|"
    r"history|tarih(i|in)|ago|önce)\b", re.I)


def _years(text: str) -> list[int]:
    return [int(y) for y in YEAR.findall(text or "")]


def is_stale(title: str, published: str, headline_tr: str = "") -> bool:
    """Başlık, yayın yılından en az iki yıl önceki bir olayı güncel gibi anlatıyor mu?"""
    try:
        py = parse_iso(published).year
    except (TypeError, ValueError):
        return False
    if CONTEXT.search(f"{title or ''} {headline_tr or ''}"):
        return False
    for text in (title, headline_tr):
        ys = _years(text)
        if not ys:
            continue
        if len(set(ys)) >= 2:                      # "2000, 2008 ve 2020" gibi listeler: karşılaştırma
            continue
        if max(ys) <= py - 2:
            return True
    return False


STOP = set("""ve ile icin için bir bu da de ki mi olarak gore göre daha cok çok en son yeni sonra once önce ise ama
the a an and of to in on for with as at by from is are was be its it this that after over into amid says said
new report reports stock stocks shares hisse hisseleri hissesi senedi""".split())


def _fold(s: str) -> str:
    s = (s or "").replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def stems(text: str) -> frozenset:
    t = re.sub(r"\s-\s[^-]+$", "", text or "")          # Google News " - Kaynak" eki
    words = re.findall(r"[a-z0-9]+", _fold(t))
    return frozenset(w[:5] for w in words if len(w) > 2 and w not in STOP)


def similar(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= 0.5 or (inter >= 4 and inter / min(len(a), len(b)) >= 0.75)


def _sig(d: dict) -> frozenset:
    h = (d.get("analysis") or {}).get("headline_tr")
    return stems(h) if h else stems(d.get("title"))


def _rank(d: dict) -> tuple:
    """Kümenin temsilcisi: AI değerlendirmesi olan, daha güvenilir kaynak, daha erken yayımlanan."""
    return (0 if d.get("analysis") else 1, d.get("tier") or 3, d.get("published") or "")


def cluster(items: list[dict], window_h: int = 72, kinds=("news", "social")) -> list[dict]:
    """Aynı olayı anlatan haber/sosyal kayıtlarını birleştirir; sırayı korur, temsilci dışındakileri çıkarır."""
    cand = [d for d in items if d.get("source_type") in kinds]
    cand.sort(key=_rank)
    keep: list[dict] = []                               # temsilciler
    drop: set[int] = set()
    for d in cand:
        sig, tk = _sig(d), set(d.get("tickers") or [])
        try:
            t = parse_iso(d["published"])
        except (KeyError, TypeError, ValueError):
            keep.append(d)
            continue
        for k in keep:
            ktk = set(k.get("tickers") or [])
            if (tk or ktk) and not (tk & ktk):
                continue
            if not tk and not ktk and len(sig) < 5:      # piyasa geneli kısa başlıklar: fazla birleştirme olmasın
                continue
            try:
                if abs(parse_iso(k["published"]) - t) > timedelta(hours=window_h):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if similar(sig, k["_sig"]) or similar(stems(d.get("title")), stems(k.get("title"))):
                k["dups"] = (k.get("dups") or 0) + 1 + (d.get("dups") or 0)
                srcs = k.get("dup_sources") or []
                for s in [(d.get("source") or "").split(" · ")[0], *(d.get("dup_sources") or [])]:
                    if s and s not in srcs and s != (k.get("source") or "").split(" · ")[0]:
                        srcs.append(s)
                k["dup_sources"] = srcs[:6]
                drop.add(id(d))
                break
        else:
            d["_sig"] = sig
            keep.append(d)
    for d in keep:
        d.pop("_sig", None)
    return [d for d in items if id(d) not in drop]
