"""Analist beklentileri ve ek istatistikler — stockanalysis.com (kişisel kullanım, robots.txt'e uyan nazik okuma).

Kullanım koşulları bot/kazıyıcı yasağını "robots.txt'e uyan tarayıcılar" için uygulamıyor; robots.txt yalnız /e/ ve /p/
yollarını kapatıyor. Koşullar içeriğin tamamen yeniden yayımlanmasını ve rakip veritabanı kurulmasını yasaklıyor; bu yüzden:
- Veri herkese açık dallara YAZILMAZ: çıktı gizli rapor reposuna (gptrade/piyasa-radari-raporlar, analist/) gider ve yalnız
  giriş korumalı Cloudflare sitesine kopyalanır (GitHub Pages kopyasında yok).
- Sayfanın tamamı saklanmaz; yalnız özet alanlar (hedef fiyat, tavsiye dağılımı, yıl ve çeyrek tahminleri, ABD'de açığa
  satış ve ileriye dönük çarpanlar).
- Okuma yavaş: istekler arası GAP saniye, günlük bütçe; 403/429 gelirse o gün durulur, engel aşılmaz.
- "[PRO]" (ücretli) alanlar alınmaz.

Kaynak sayfalar (SvelteKit veri uç noktası, aynı sayfanın JSON'u):
  BIST  /quote/ist/{KOD}/forecast/__data.json
  ABD   /stocks/{kod}/forecast/__data.json  ve  /stocks/{kod}/statistics/__data.json
Tahminlerin kaynağı S&P Global Market Intelligence (sitede belirtildiği gibi).

Bilanço sürprizi için çeyrek tahminleri haftalık anlık görüntü olarak saklanır (analist_hist.json): bir çeyrek raporlanınca
raporlamadan önceki son tahmin ile gerçekleşen karşılaştırılır.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path

from .config import DATA, ROOT

log = logging.getLogger("radar.sa")

BASE = "https://stockanalysis.com"
GAP = 4.0                     # saniye, istekler arası
REFRESH_D = 7                 # gün: kapsanan hisse
EMPTY_D = 30                  # gün: analist takibi olmayan hisse
UA = "Mozilla/5.0 (compatible; piyasa-radari/1.0; +https://github.com/gptrade/piyasa-radari; kisisel kullanim)"
FIN = DATA / "fin" / "_screen.json"
FIN_US = DATA / "fin_us" / "_screen.json"
STAT_IDS = {"shortInterest", "shortPriorMonth", "shortShares", "shortFloat", "shortRatio", "peForward", "peg", "pe",
            "earningsdate", "exdivdate", "beta", "priceTargetChange", "floatShares", "insiderOwnership", "institutionalOwnership"}


# ───────────────────────────── ayrıştırma

def unflatten(arr: list):
    """SvelteKit 'devalue' biçimi: düz dizi, değerler indeks referansı."""
    memo: dict = {}

    def h(i):
        if not isinstance(i, int) or i < 0:
            return None
        if i in memo:
            return memo[i]
        v = arr[i]
        if isinstance(v, list):
            out = v[1] if (v and isinstance(v[0], str) and v[0] in ("Date", "BigInt", "RegExp")) else [h(x) for x in v]
        elif isinstance(v, dict):
            out = {k: h(x) for k, x in v.items()}
        else:
            out = v
        memo[i] = out
        return out
    return h(0)


def nodes(j: dict) -> tuple[dict, dict]:
    """(info, sayfa verisi)"""
    ns = [unflatten(n["data"]) if n and n.get("type") == "data" else None for n in (j.get("nodes") or [])]
    info = next((n.get("info") for n in ns if isinstance(n, dict) and "info" in n), None) or {}
    page = ns[-1] if ns and isinstance(ns[-1], dict) and "info" not in ns[-1] and "session" not in ns[-1] else {}
    return info, page


def _free(v):
    return None if v == "[PRO]" or (isinstance(v, str) and "PRO" in v) else v


def _num(v):
    v = _free(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("$", "").replace("%", "").strip()
        m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([KMBT]?)", s)
        if m:
            return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2)]
    return None


def _r(v, n=4):
    return round(v, n) if isinstance(v, (int, float)) else None


def parse_forecast(info: dict, d: dict) -> dict | None:
    if not d or not (d.get("priceTargets") or d.get("currentRatings") or d.get("estimates")):
        return None
    pt, rt = d.get("priceTargets") or {}, d.get("currentRatings") or {}
    out = {"cur": (info.get("curr") or {}).get("price"), "fcur": (info.get("curr") or {}).get("financial")}
    if pt.get("numPriceTargets"):
        out["pt"] = {k2: _r(_num(pt.get(k1)), 4) for k1, k2 in (("avg", "avg"), ("median", "med"), ("low", "low"), ("high", "high"))}
        out["pt"]["n"] = int(pt["numPriceTargets"])
    if rt.get("count"):
        out["rt"] = {"c": rt.get("consensus"), "s": _r(_num(rt.get("score")), 2), "n": int(rt["count"]),
                     **{k: int(rt.get(k) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}}
    rec = [x for x in (d.get("recommendations") or []) if isinstance(x, dict)][-6:]
    if rec:
        out["rtr"] = [[x.get("date"), _r(_num(x.get("score")), 2), x.get("total")] for x in rec]
    ec = d.get("estimatesCharts") or {}
    for key, nm in (("eps", "eps"), ("revenue", "rev")):
        for fy, v in sorted((ec.get(key) or {}).items()):
            v = _free(v)
            if isinstance(v, dict) and v.get("avg") is not None:
                out.setdefault("fy", {})["end"] = fy
                out["fy"][nm] = {"n": v.get("no"), "avg": _r(_num(v.get("avg")), 6), "low": _r(_num(v.get("low")), 6), "high": _r(_num(v.get("high")), 6)}
                break
    st = ((d.get("estimates") or {}).get("stats") or {})
    for per, nm in (("annual", "an"), ("quarterly", "qt")):
        s = st.get(per) or {}
        blk = {k: {kk: _r(_num(vv), 6) for kk, vv in (s.get(k) or {}).items()} for k in ("epsThis", "epsNext", "revenueThis", "revenueNext") if s.get(k)}
        blk = {k: v for k, v in blk.items() if any(x is not None for x in v.values())}
        if blk:
            out[nm] = blk
    tq = ((d.get("estimates") or {}).get("table") or {}).get("quarterly") or {}
    if tq.get("dates"):
        out["tq"] = {"dates": tq["dates"], "eps": [_r(_num(x), 6) for x in (tq.get("eps") or [])],
                     "rev": [_r(_num(x), 0) for x in (tq.get("revenue") or [])], "last": tq.get("lastDate"),
                     "fq": tq.get("fiscalQuarter"), "fyr": tq.get("fiscalYear")}
    return out if len(out) > 2 else None


def parse_stats(d: dict) -> dict | None:
    out = {}
    for sec in d.values() if isinstance(d, dict) else []:
        for it in (sec.get("data") or []) if isinstance(sec, dict) else []:
            if isinstance(it, dict) and it.get("id") in STAT_IDS and not it.get("proOnly"):
                v = it.get("hover") if it.get("hover") is not None else it.get("value")
                if it["id"] in ("earningsdate", "exdivdate"):
                    out[it["id"]] = v
                else:
                    n = _num(v)
                    if n is not None:
                        out[it["id"]] = round(n / 100, 6) if isinstance(v, str) and v.strip().endswith("%") else n
    return out or None


# ───────────────────────────── kuyruk

def universe() -> list[tuple[str, str, float]]:
    """(pazar, kod, piyasa değeri USD yaklaşığı) — önce izleme listesi, sonra büyükten küçüğe."""
    out = []
    for path, m in ((FIN, "BIST"), (FIN_US, "US")):
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("rows") or []
        except (OSError, ValueError):
            continue
        for r in rows:
            mc = r.get("mcap") or 0
            out.append((m, r["code"], mc / 50 if m == "BIST" else mc))
    return out


def watch_codes() -> set[str]:
    try:
        import yaml
        wl = yaml.safe_load((ROOT / "config" / "watchlist.yml").read_text(encoding="utf-8")) or {}
        return {str(x.get("symbol")).upper() for k in ("bist", "us") for x in (wl.get(k) or []) if isinstance(x, dict)}
    except Exception:  # noqa: BLE001
        return set()


def urls(m: str, code: str) -> list[tuple[str, str]]:
    if m == "BIST":
        return [("forecast", f"/quote/ist/{code}/forecast/__data.json")]
    c = code.lower().replace("-", ".")
    return [("forecast", f"/stocks/{c}/forecast/__data.json"), ("stats", f"/stocks/{c}/statistics/__data.json")]


def due(st: dict, key: str, today: date) -> bool:
    s = st.get(key)
    if not s:
        return True
    age = (today - date.fromisoformat(s["t"])).days
    return age >= (EMPTY_D if s.get("empty") else REFRESH_D)


def order(univ, st: dict, today: date, watch: set[str]) -> list[tuple[str, str]]:
    todo = [(m, c, mc) for m, c, mc in univ if due(st, f"{m}:{c}", today)]
    # izleme listesi önce; sonra hiç okunmamışlar büyükten küçüğe; sonra en eski okunanlar
    def k(x):
        m, c, mc = x
        s = st.get(f"{m}:{c}")
        return (0 if c in watch else 1, 0 if not s else 1, s["t"] if s else "", -mc)
    return [(m, c) for m, c, _ in sorted(todo, key=k)]


# ───────────────────────────── bilanço sürprizi (çeyrek tahmini anlık görüntüleri)

def snapshot(hist: dict, key: str, fc: dict, today: str) -> None:
    """Gelecek çeyreklerin tahminini kaydeder; raporlanan çeyreğin gerçekleşenini bir kez yazar."""
    tq = (fc or {}).get("tq")
    if not tq:
        return
    h = hist.setdefault(key, {})
    last = tq.get("last")
    if isinstance(last, (int, float)) and not isinstance(last, bool):      # sayfa bazen son gerçekleşen çeyreğin sırasını verir
        last = tq["dates"][int(last)] if 0 <= int(last) < len(tq["dates"]) else (
            datetime.fromtimestamp(last / 1000, timezone.utc).date().isoformat() if last > 1e11 else "")
    last = str(last or "")
    for i, d in enumerate(tq["dates"]):
        eps = tq["eps"][i] if i < len(tq["eps"]) else None
        rev = tq["rev"][i] if i < len(tq["rev"]) else None
        q = h.setdefault(d, {})
        if last and d <= last:
            if "act" not in q and (eps is not None or rev is not None):
                q["act"] = [eps, rev, today]
        elif eps is not None or rev is not None:
            q["est"] = [eps, rev, today]          # son tahmin (raporlamadan önceki en son okuma kalır)
    for d in sorted(h)[:-12]:                     # en fazla 12 çeyrek
        h.pop(d, None)


def surprises(h: dict) -> list[dict]:
    out = []
    for d, q in sorted(h.items()):
        if "act" in q and "est" in q and q["est"][2] < q["act"][2]:
            e, a = q["est"][0], q["act"][0]
            re_, ra = q["est"][1], q["act"][1]
            out.append({"d": d, "eps_e": e, "eps_a": a, "eps_s": _r((a - e) / abs(e), 4) if e not in (None, 0) and a is not None else None,
                        "rev_e": re_, "rev_a": ra, "rev_s": _r((ra - re_) / abs(re_), 4) if re_ not in (None, 0) and ra is not None else None})
    return out[-4:]


# ───────────────────────────── çalıştırma

def fetch(session, path: str):
    r = session.get(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30)
    if r.status_code in (403, 429):
        raise PermissionError(f"HTTP {r.status_code}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def robots_ok(session) -> bool:
    try:
        t = session.get(BASE + "/robots.txt", headers={"User-Agent": UA}, timeout=20).text
    except Exception:  # noqa: BLE001
        return False
    block, dis = False, []
    for line in t.splitlines():
        l = line.split("#")[0].strip()
        if l.lower().startswith("user-agent:"):
            block = l.split(":", 1)[1].strip() == "*"
        elif block and l.lower().startswith("disallow:"):
            dis.append(l.split(":", 1)[1].strip())
    bad = [d for d in dis if d in ("/", "/stocks/", "/quote/") or d.startswith("/stocks") or d.startswith("/quote")]
    if bad:
        log.warning("robots.txt hisse sayfalarını kapatıyor (%s); okunmuyor", bad)
    return not bad


def run(out: Path, budget_s: int = 1500, max_pages: int = 400, session=None, today: date | None = None, sleep=time.sleep) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    today = today or date.today()
    sp, ap, hp = out / "sa_state.json", out / "analist.json", out / "analist_hist.json"
    st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    rows = (json.loads(ap.read_text(encoding="utf-8")).get("rows") if ap.exists() else None) or {}
    hist = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else {}
    if session is None:
        import requests
        session = requests.Session()
    if not robots_ok(session):
        return {"rows": rows}
    t0, n, errs, stop = time.monotonic(), 0, 0, None
    for m, c in order(universe(), st, today, watch_codes()):
        if time.monotonic() - t0 > budget_s or n >= max_pages or stop:
            break
        key, row, empty = f"{m}:{c}", {"m": m}, True
        for kind, path in urls(m, c):
            n += 1
            try:
                j = fetch(session, path)
                errs = 0
            except PermissionError as e:
                stop = str(e)
                log.warning("stockanalysis %s — bugünlük durduruldu", e)
                break
            except Exception as e:  # noqa: BLE001
                errs += 1
                log.info("stockanalysis %s %s: %s", c, kind, e)
                j = None
                if errs >= 5:
                    stop = "ardışık hata"
            if j:
                info, d = nodes(j)
                if kind == "forecast":
                    fc = parse_forecast(info, d)
                    if fc:
                        row.update(fc)
                        empty = False
                        snapshot(hist, key, fc, today.isoformat())
                else:
                    s = parse_stats(d)
                    if s:
                        row["st"] = s
                        empty = False
            sleep(GAP)
        if stop:                                   # yarım kalan hisse kaydedilmez; ertesi gün yeniden denenir
            break
        if not empty:
            row["t"] = today.isoformat()
            if hist.get(key):
                sv = surprises(hist[key])
                if sv:
                    row["sur"] = sv
            row.pop("tq", None)
            rows[key] = row
        st[key] = {"t": today.isoformat(), **({"empty": True} if empty else {})}
    doc = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "stockanalysis.com (tahminler: S&P Global Market Intelligence)", "rows": rows,
           "n": len(rows), "stopped": stop}
    ap.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    sp.write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")
    hp.write_text(json.dumps(hist, separators=(",", ":")), encoding="utf-8")
    log.info("stockanalysis: %d sayfa okundu, %d hisse kayıtlı, kuyrukta %d · %s", n, len(rows),
             sum(1 for m, c, _ in universe() if due(st, f"{m}:{c}", today)), stop or "tamam")
    return doc


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA / "sa"))
    ap.add_argument("--budget", type=int, default=1500)
    ap.add_argument("--max", type=int, default=400)
    a = ap.parse_args()
    run(Path(a.out), a.budget, a.max)
