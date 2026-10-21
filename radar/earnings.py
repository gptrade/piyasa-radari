"""Bilanço sürprizi (PEAD için): KAP mali tablolarından (fin/*.json) çeyreklik net kâr sürprizi.

Beklenti modeli: mevsimsel rastgele yürüyüş — bu çeyreğin reel net kârı geçen yılın aynı çeyreği kadar olur.
  Δ_t   = reel NK_t − reel NK_{t−4}             (reel = dönem sonu TÜFE'ye bölünmüş; TMS 29 ve enflasyon farkını giderir)
  SU_t  = Δ_t / ortalama |reel NK| (t−4 … t−1)  (ölçekli sürpriz: tipik bir çeyreğin kârına göre; ana ölçü, 5 çeyrek yeter)
  SUE_t = Δ_t / std(Δ_{t−1} … Δ_{t−8})         (standartlaştırılmış; en az 4 geçmiş Δ gerekir, geçmiş uzadıkça dolar)
Analist beklentisi kullanılmaz (ücretsiz ve lisanslı BIST konsensüsü yok). Yön: SU > +0,2 olumlu, < −0,2 olumsuz, arası nötr.
Her rapor KAP bildirim endeksini (idx) taşır; olay veritabanındaki kap:<idx> satırına bağlanır.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MIN_HIST = 4
WIN = 8
TH = 0.2
CAP = 5.0              # zarar/kâr geçişinde oran patlamasın


def _real(q: list, cpi: list) -> list[float | None]:
    return [None if v is None or not c else v / c for v, c in zip(q, cpi)]


def sue_series(q: list, cpi: list) -> list[dict | None]:
    """Her dönem için {'sue', 'd', 'yoy'} ya da None (yetersiz geçmiş)."""
    r = _real(q, cpi)
    n = len(r)
    d = [None] * n
    for t in range(4, n):
        if r[t] is not None and r[t - 4] is not None:
            d[t] = r[t] - r[t - 4]
    out: list[dict | None] = [None] * n
    for t in range(n):
        if d[t] is None:
            continue
        hist = [x for x in d[max(0, t - WIN):t] if x is not None]
        yoy = (r[t] / r[t - 4] - 1) if r[t - 4] and r[t - 4] > 0 else None
        base = [abs(x) for x in r[t - 4:t] if x is not None]
        scale = sum(base) / len(base) if len(base) == 4 else None
        su = max(-CAP, min(CAP, d[t] / scale)) if scale else None
        sue = None
        if len(hist) >= MIN_HIST:
            m = sum(hist) / len(hist)
            sd = math.sqrt(sum((x - m) ** 2 for x in hist) / (len(hist) - 1))
            sue = d[t] / sd if sd > 0 else None
        out[t] = {"su": su, "sue": sue, "d": d[t], "yoy": yoy}
    return out


def direction(su: float | None) -> int | None:
    if su is None:
        return None
    return 1 if su > TH else -1 if su < -TH else 0


def surprises(fin: Path) -> dict[int, dict]:
    """KAP bildirim endeksi → {'sym', 'period', 'su', 'sue', 'yoy', 'dir', 'rev_su'}."""
    out: dict[int, dict] = {}
    for p in sorted(fin.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        s = doc.get("series") or {}
        P, cpi, q = s.get("periods") or [], s.get("cpi") or [], s.get("q") or {}
        ni = q.get("net_parent") or q.get("net")
        if not P or not ni or len(cpi) != len(P):
            continue
        ns = sue_series(ni, cpi)
        rs = sue_series(q["revenue"], cpi) if q.get("revenue") and len(q["revenue"]) == len(P) else [None] * len(P)
        reps = doc.get("reports") or {}
        for t, per in enumerate(P):
            idx = (reps.get(per) or {}).get("idx")
            if not idx or ns[t] is None:
                continue
            x = ns[t]
            rnd = lambda v, k=3: None if v is None else round(v, k)
            out[int(idx)] = {"sym": doc.get("code"), "period": per, "su": rnd(x["su"]), "sue": rnd(x["sue"]), "yoy": rnd(x["yoy"], 4),
                             "dir": direction(x["su"]), "rev_su": rnd(rs[t]["su"]) if rs[t] else None}
    return out
