"""Olay veritabanı (Faz 1): bütün modüllerin olaylarını tek, zaman damgalı tabloda toplar; BIST Tüm günlük fiyatı tutar;
her olay için 1/5/20 seanslık piyasaya göre anormal getiri hesaplar.

Çıktı (site/data/olay → ayrı `olay` dalı, tek commit):
  events/YYYY-MM.parquet   olaylar; anahtar (id, sym). Ekleyerek yazılır, aynı anahtar güncellenir (tekrarsız).
  px_daily.parquet         sym, date, close, adj_close, volume (BIST Tüm + izleme listesi + endeksler)
  event_returns.parquet    id, sym, d0, r1/r5/r20, m1/m5/m20, ar1/ar5/ar20, pre5
  summary.json             sayımlar ve kabul ölçütleri (tekrar oranı, fiyat eksik gün oranı, kaynak gecikmesi)

Kaynaklar (hepsi zaten panelin kullandığı, izinli kaynaklar):
  KAP bildirim listesi (byCriteria, evrenin tamamı) · feed.json (AI sınıflı haber/bildirim) · signals.json (sinyal arşivi) ·
  research.json (aracı kurum notlarının kamuya açık özetleri) · kap-buybacks.json (geri alım takipçisi) ·
  fin/_dividends.json (kâr payı kararları) · calendar.json (gerçekleşmiş makro veri ve bilanço tarihleri)
Fiyat: Yahoo (yfinance), kişisel kullanım; ham fiyat panelde yeniden dağıtılmaz.
"""
from __future__ import annotations

import hashlib
import re
import json
import logging
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .config import DATA

log = logging.getLogger("radar.eventdb")

OUT = DATA / "olay"
EV_DIR = OUT / "events"
PX = OUT / "px_daily.parquet"
RET = OUT / "event_returns.parquet"
SUMMARY = OUT / "summary.json"
STATE = OUT / "_state.json"
BB_URL = "https://raw.githubusercontent.com/gptrade/kap-geri-alim-takibi/main/site/kap-buybacks.json"
KAP_LIST = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"

IST, NY = ZoneInfo("Europe/Istanbul"), ZoneInfo("America/New_York")
SESS = {"BIST": (IST, time(10, 0), time(18, 0)), "US": (NY, time(9, 30), time(16, 0))}
INDEX = {"BIST": "XU100", "US": "^GSPC"}
YF = {"XU100": "XU100.IS", "XBANK": "XBANK.IS", "XUSIN": "XUSIN.IS", "^GSPC": "^GSPC"}
HORIZONS = (1, 5, 20)
BACKFILL_DAYS = 90
PX_YEARS = 2
COLS = ["id", "sym", "market", "ts", "ts_eff", "type", "subtype", "dir", "conf", "mat", "mag", "src", "title", "url", "ingested", "payload", "cluster"]

# KAP konu başlığı → olay tipi (sadeleştirilmiş küçük harf; sıra önemli, özel ifade önce)
SCHEMA = 3                                                    # sınıflandırma değişince eski tablo silinip yeniden doldurulur
# İdari / rutin bildirimler: saklanır ama olay çalışmalarına girmez (type="idari")
KAP_ADMIN = ("genel bilgi formu", "kurumsal yönetim ilkelerine uyum", "katılım finansı", "sorumluluk beyanı", "takasbank", "haftalık rapor", "piyasa yapıcılığı",
             "likidite sağlayıcılık", "tertip ihraç", "pay dışında sermaye piyasası aracı", "izahname", "kurumsal yönetim bilgi formu",
             "sürdürülebilirlik raporu", "tsrs", "bağımsız denetim kuruluşu", "yönetim kurulu komiteleri", "esas sözleşme",
             "herhangi bir otoriteye mali tablo", "tipe dönüşüm", "spk işlem yasağı nedeniyle", "temerrüt", "işlem görmeye başlama",
             "borçlanma araçlarının", "kira sertifika", "ihraç belgesi", "fon ", "genel açıklama")
KAP_TYPES = [
    ("endeks", "endeks", "endeks değişikliği"),
    ("pay alım teklifi", "birlesme", "pay alım teklifi"), ("haber ve söylenti", "kap_ozel", "haber ve söylentilere açıklama"),
    ("mali hak kullanım", "temettu", "mali hak kullanımı"), ("kayıtlı sermaye", "sermaye", "kayıtlı sermaye tavanı"),
    ("finansal duran varlık", "yatirim", "finansal duran varlık"), ("geleceğe dönük", "beklenti", "geleceğe dönük değerlendirme"),
    ("geri al", "geri_alim", "geri alım"), ("kar payı", "temettu", "kâr payı"), ("kâr payı", "temettu", "kâr payı"),
    ("finansal rapor", "finansal", "finansal rapor"), ("faaliyet raporu", "finansal", "faaliyet raporu"),
    ("sermaye artırımı", "sermaye", "sermaye artırımı/azaltımı"), ("bedelsiz", "sermaye", "bedelsiz"), ("bölünme", "sermaye", "bölünme"),
    ("birleşme", "birlesme", "birleşme/satın alma"), ("pay alım satım", "iceriden", "pay alım satım bildirimi"),
    ("yeni iş ilişkisi", "is_iliskisi", "yeni iş ilişkisi"), ("sipariş", "is_iliskisi", "sipariş"), ("ihale", "is_iliskisi", "ihale"),
    ("maddi duran varlık", "yatirim", "duran varlık alım/satım"), ("yatırım", "yatirim", "yatırım"),
    ("borçlanma", "borclanma", "borçlanma aracı"), ("ihraç tavan", "borclanma", "ihraç tavanı"), ("kredi derecelendirme", "derecelendirme", "derecelendirme"),
    ("genel kurul", "genel_kurul", "genel kurul"), ("dava", "hukuki", "dava"), ("tedbir", "borsa_tedbir", "Borsa tedbiri"),
    ("özel durum", "kap_ozel", "özel durum açıklaması"),
]
FEED_TYPES = {"disclosure": "kap_ozel", "news": "haber", "social": "sosyal", "macro": "makro", "regulator": "regulasyon",
              "technical": "teknik", "report": "broker_not"}
SIG_TYPES = {"analyst": "broker_not", "deal": "is_iliskisi", "earnings": "finansal", "buyback": "geri_alim", "dividend": "temettu",
             "insider": "iceriden", "legal": "hukuki", "measure": "borsa_tedbir", "regulator": "regulasyon", "technical": "teknik",
             "social": "sosyal", "anomaly": "anomali", "news": "haber"}
SENT = {"bullish": 1, "bearish": -1, "neutral": 0, "mixed": 0}


def _fold(s: str) -> str:
    return (s or "").replace("İ", "i").replace("I", "ı").lower()


def _ts(s) -> pd.Timestamp | None:
    try:
        t = pd.Timestamp(s)
    except (ValueError, TypeError):
        return None
    if t is pd.NaT or pd.isna(t):
        return None
    return t.tz_localize(IST).tz_convert("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _kap_ts(s: str) -> pd.Timestamp | None:
    for f in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return pd.Timestamp(datetime.strptime(s.strip(), f).replace(tzinfo=IST)).tz_convert("UTC")
        except (ValueError, AttributeError):
            continue
    return None


def _row(**k) -> dict:
    r = {c: None for c in COLS}
    r.update(k)
    if isinstance(r.get("payload"), dict):
        r["payload"] = json.dumps(r["payload"], ensure_ascii=False, separators=(",", ":"))
    return r


def kap_type(subject: str, summary: str = "") -> tuple[str, str]:
    if any(k in _fold(subject) for k in KAP_ADMIN):
        return "idari", (subject or "")[:60]
    t = _fold(f"{subject} {summary}")
    for k, typ, sub in KAP_TYPES:
        if k in t:
            return typ, sub
    return "kap_diger", (subject or "")[:60]


# ─────────────────────────────── kaynak eşlemeleri (saf fonksiyonlar; test edilir)
def from_kap_rows(rows: list[dict], universe: set[str] | None = None) -> list[dict]:
    """universe verilirse yalnız evrendeki pay kodları tutulur (fon, tahvil, varant kodları ayıklanır)."""
    out = []
    for row in rows:
        ts, idx = _kap_ts(row.get("publishDate") or ""), row.get("disclosureIndex")
        if ts is None or not idx:
            continue
        codes = [c.strip().upper() for c in str(row.get("relatedStocks") or row.get("stockCodes") or "").replace(";", ",").split(",") if c.strip()]
        subject, summ = row.get("subject") or "", row.get("summary") or ""
        if universe:
            codes = [c for c in codes if c in universe]
            if not codes:
                continue
        bist = "BORSA İSTANBUL" in (row.get("kapTitle") or "").upper()
        if bist:
            typ, sub = kap_type(subject, summ)
            if typ not in ("idari", "endeks"):
                from .sources.kap import bist_measure
                typ, sub = "borsa_tedbir", bist_measure(f"{summ} {subject}")
        else:
            typ, sub = kap_type(subject, summ)
        for sym in codes or [""]:
            out.append(_row(id=f"kap:{idx}", sym=sym, market="BIST", ts=ts, type=typ, subtype=sub, src="kap",
                            title=f"{subject} · {summ}"[:300], url=f"https://www.kap.org.tr/tr/Bildirim/{idx}",
                            payload={"class": row.get("disclosureClass"), "filer": row.get("kapTitle"), "fix": bool(row.get("modifyStatus"))}))
    return out


def from_feed(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        ts = _ts(it.get("published"))
        if ts is None:
            continue
        a = it.get("analysis") or {}
        ex = it.get("extra") or {}
        src = it.get("source") or ""
        dir_ = SENT.get(a.get("sentiment"))
        conf = a.get("confidence") / 100 if isinstance(a.get("confidence"), (int, float)) else None
        if src.endswith("KAP") and ex.get("index"):                     # KAP bildirimi: KAP satırıyla birleşir, AI sınıfını ekler
            typ, sub = ("borsa_tedbir", ex.get("bist_measure") or "") if ex.get("bist_measure") else kap_type(ex.get("subject") or "", it.get("summary") or "")
            eid, s = f"kap:{ex['index']}", "kap"
        else:
            typ, sub = FEED_TYPES.get(it.get("source_type"), "haber"), (a.get("category") or "")[:60]
            eid, s = f"feed:{it.get('id')}", f"feed:{src}"[:80]
        for sym in it.get("tickers") or [""]:
            out.append(_row(id=eid, sym=sym, market=it.get("market"), ts=ts, type=typ, subtype=sub, dir=dir_, conf=conf,
                            mat=a.get("materiality"), src=s, title=(a.get("headline_tr") or it.get("title") or "")[:300], url=it.get("url"),
                            payload={"ai": bool(a), "label": a.get("event_label"), "horizon": a.get("horizon")}))
    return out


def from_signals(items: list[dict]) -> list[dict]:
    out = []
    for s in items:
        ts = _ts(s.get("ts"))
        if ts is None or not s.get("t"):
            continue
        out.append(_row(id=f"feed:{s['id']}", sym=s["t"], market=s.get("m"), ts=ts, type=SIG_TYPES.get(s.get("ev"), "haber"),
                        subtype=s.get("kind"), dir=s.get("d"), conf=s["c"] / 100 if isinstance(s.get("c"), (int, float)) else None,
                        mat=s.get("mat"), src=f"feed:{s.get('src') or ''}"[:80], title=(s.get("title") or "")[:300],
                        payload={"signal": True, "ev": s.get("ev"), "pv": s.get("pv")}))
    return out


def from_research(notes: list[dict]) -> list[dict]:
    out = []
    for n in notes:
        ts = _ts(n.get("ts"))
        if ts is None or not n.get("t"):
            continue
        mag = round(n["tp"] / n["prev"] - 1, 4) if n.get("tp") and n.get("prev") else None
        act = n.get("action")
        dir_ = 1 if act == "up" or (act == "init" and n.get("dir") == 1) else -1 if act == "down" else n.get("dir")
        out.append(_row(id=f"res:{n['id']}", sym=n["t"], market=n.get("m") or "BIST", ts=ts,
                        type="hedef_degisim" if act in ("up", "down") else "broker_not", subtype=act, dir=dir_, mag=mag,
                        src=f"broker:{n.get('broker') or ''}"[:80], title=(n.get("title") or "")[:300], url=n.get("url"),
                        payload={"broker": n.get("broker"), "rating": n.get("rating"), "tp": n.get("tp"), "prev": n.get("prev"), "cur": n.get("cur")}))
    return out


def from_buybacks(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        ts, idx = _kap_ts(r.get("publish_date") or ""), r.get("disclosure_index")
        if ts is None or not idx:
            continue
        for sym in [c.strip() for c in str(r.get("tickers") or "").split(",") if c.strip()]:
            out.append(_row(id=f"kap:{idx}", sym=sym, market="BIST", ts=ts, type="geri_alim", subtype="gerçekleşen geri alım", dir=1,
                            mag=r.get("pct_this_transaction"), src="kap", title=(r.get("notice_type") or "")[:300], url=r.get("source_url"),
                            payload={"price": r.get("price"), "qty": r.get("quantity"), "own_after": r.get("ownership_pct_after"), "tx_date": r.get("transaction_date")}))
    return out


def from_dividends(by_code: dict[str, list[dict]]) -> list[dict]:
    out = []
    for sym, evs in by_code.items():
        for e in evs:
            d = e.get("decision")
            if not d or not e.get("idx"):
                continue
            ts = pd.Timestamp(datetime.combine(date.fromisoformat(d), time(18, 30), IST)).tz_convert("UTC")   # saat yok: kapanış sonrası say
            net = e.get("net") or 0
            out.append(_row(id=f"kap:{e['idx']}", sym=sym, market="BIST", ts=ts, type="temettu",
                            subtype="ödenmeyecek" if e.get("status") == "yok" or not net else "nakit kâr payı", dir=1 if net else -1 if e.get("status") == "yok" else 0,
                            mag=net or None, src="kap", title=(e.get("summary") or "")[:300], url=f"https://www.kap.org.tr/tr/Bildirim/{e['idx']}",
                            payload={"payout": e.get("payout"), "gross": e.get("gross"), "gm": e.get("gm"), "method": e.get("method"), "ts_guess": True}))
    return out


def from_calendar(events: list[dict], now: pd.Timestamp) -> list[dict]:
    out = []
    for e in events:
        ts = _ts(e.get("when") or e.get("date"))
        if ts is None or ts > now or e.get("kind") not in ("earnings", "data", "macro", "cb"):
            continue
        earn = e["kind"] == "earnings"
        if earn and not e.get("ticker"):
            continue
        eid = "cal:" + (e.get("id") or hashlib.sha1(f"{e.get('title')}|{e.get('when')}".encode()).hexdigest()[:16])
        out.append(_row(id=eid, sym=e.get("ticker") if earn else "", market=e.get("market"), ts=ts, type="finansal" if earn else "makro",
                        subtype="bilanço tarihi" if earn else e["kind"], src=f"takvim:{e.get('src') or ''}"[:80], title=(e.get("title") or "")[:300],
                        url=e.get("url"), payload={"importance": e.get("importance"), "eps_est": e.get("eps_est"), "region": e.get("region"), "session": e.get("session")}))
    return out


# ─────────────────────────────── birleştirme
PRIO = {"kap": 3, "res": 3, "cal": 2, "feed": 1}


def merge(old: pd.DataFrame | None, new: list[dict], now: pd.Timestamp) -> tuple[pd.DataFrame, int]:
    """(id, sym) anahtarıyla birleştirir. Var olan satırın boş alanlarını yeni kaynak doldurur (ör. KAP satırına AI yönü);
    `ingested` ilk görülme anı olarak korunur. Dönen ikinci değer: aynı turda tekrar eden satır sayısı."""
    df = pd.DataFrame(new, columns=COLS)
    if df.empty and (old is None or old.empty):
        return pd.DataFrame(columns=COLS), 0
    df["ingested"] = now
    dup = int(df.duplicated(["id", "sym"]).sum())
    frames = [x for x in (old, df) if x is not None and not x.empty]
    allr = pd.concat(frames, ignore_index=True)
    allr["_o"] = range(len(allr))
    # öncelik: eski kayıt önce (ingested, ts korunur); sonraki kayıtlar yalnız boş alanları doldurur
    g = allr.sort_values("_o").groupby(["id", "sym"], sort=False)
    merged = g.first()            # first(): her sütunda ilk boş olmayan değer
    merged["ingested"] = g["ingested"].min()
    merged["payload"] = g["payload"].agg(lambda s: _merge_payload(list(s)))
    out = merged.reset_index().drop(columns="_o", errors="ignore")[COLS]
    return out, dup


def _merge_payload(ps: list) -> str | None:
    d: dict = {}
    for p in ps:
        if isinstance(p, str):
            try:
                for k, v in json.loads(p).items():
                    if v is not None and d.get(k) is None:
                        d[k] = v
            except ValueError:
                pass
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")) if d else None


# ─────────────────────────────── seans takvimi
def sessions_from_px(px: pd.DataFrame | None, market: str) -> list[date]:
    if px is None or px.empty:
        return []
    s = px[px.sym == INDEX[market]].date
    return sorted(pd.to_datetime(s).dt.date.unique())


def ts_effective(ts: pd.Timestamp, market: str, sess: list[date]) -> tuple[pd.Timestamp, date]:
    """Getirinin başladığı an ve o seansın tarihi. Seans içi olay: kendisi; seans dışı: sonraki seans açılışı.
    Seans listesi yoksa ya da tarih listenin ötesindeyse hafta içi günler kullanılır (tatiller sonradan düzelir)."""
    tz, op, cl = SESS.get(market or "BIST", SESS["BIST"])
    loc = ts.tz_convert(tz)
    d = loc.date()

    def is_sess(x: date) -> bool:
        return x in sess_set if sess and x <= sess[-1] else x.weekday() < 5
    sess_set = set(sess)
    if is_sess(d) and loc.time() < cl:
        start = max(loc, pd.Timestamp(datetime.combine(d, op), tz=tz))
        return start.tz_convert("UTC"), d
    d += timedelta(days=1)
    while not is_sess(d):
        d += timedelta(days=1)
    return pd.Timestamp(datetime.combine(d, op), tz=tz).tz_convert("UTC"), d


# ─────────────────────────────── getiriler
JUMP = 0.25            # BIST günlük fiyat sınırı ±%10: bundan büyük tek gün hareketi çoğunlukla düzeltilmemiş bölünme/bedelsiz


def ew_index(wide: pd.DataFrame, syms: list[str]) -> pd.Series:
    """Eşit ağırlıklı evren endeksi: günlük getirilerin ortalaması (sıçramalar dışarıda), 100'den zincirlenir.
    Küçük ve orta ölçekli hisselerin olayları için XU100'den daha adil kıyas: evrenin geneline göre fark."""
    cols = [c for c in syms if c in wide.columns]
    r = wide[cols].pct_change(fill_method=None)
    r = r.where(r.abs() <= JUMP)
    return (1 + r.mean(axis=1).fillna(0)).cumprod() * 100


def event_returns(ev: pd.DataFrame, px: pd.DataFrame, universe: list[str] | None = None) -> pd.DataFrame:
    """d0 = olay seansından önceki son kapanış; h seans getirisi = olay seansından itibaren h. kapanış / d0 kapanışı − 1.
    m/ar: piyasa endeksi (XU100, S&P 500) ve ona göre fark; e/ae (yalnız BIST): eşit ağırlıklı evren ve ona göre fark.
    pre5 = olaydan önceki 5 seansın evrene göre farkı (sızıntı kontrolü). Penceresinde ±%25'ten büyük tek gün hareketi
    olan getiri yazılmaz (jump=True): Yahoo'da düzeltilmemiş bedelsiz/bölünme izi."""
    rows = []
    if ev.empty or px.empty:
        return pd.DataFrame(columns=["id", "sym", "d0", "pre5", "jump"] + [f"{k}{h}" for h in HORIZONS for k in ("r", "m", "ar", "e", "ae")])
    px = px.assign(date=pd.to_datetime(px["date"]).dt.date)
    wide = px.pivot_table(index="date", columns="sym", values="adj_close", aggfunc="last").sort_index()
    dret = wide.pct_change(fill_method=None).abs()
    ew = ew_index(wide, universe) if universe else None
    for mkt, g in ev[ev.sym.isin(wide.columns) & ev.sym.ne("")].groupby("market"):
        idx = INDEX.get(mkt)
        if idx not in wide.columns:
            continue
        cal = wide[idx].dropna()
        bench = ew.reindex(cal.index) if mkt == "BIST" and ew is not None else None
        dates = list(cal.index)
        pos = {d: i for i, d in enumerate(dates)}
        for r in g.itertuples(index=False):
            if r.ts_eff is None or pd.isna(r.ts_eff):
                continue
            de = pd.Timestamp(r.ts_eff).tz_convert(SESS[mkt][0]).date()
            i = pos.get(de)
            if i is None:                                   # seans listede yok (tatil/eksik): sonraki ilk seans
                nxt = [k for k, d in enumerate(dates) if d >= de]
                if not nxt:
                    continue
                i = nxt[0]
            if i == 0:
                continue
            s = wide[r.sym]
            p0, m0 = s.get(dates[i - 1]), cal.iloc[i - 1]
            if p0 is None or pd.isna(p0) or not p0:
                continue
            o = {"id": r.id, "sym": r.sym, "d0": dates[i - 1], "jump": False}
            b = bench if bench is not None else cal
            if i >= 6 and not pd.isna(s.get(dates[i - 6])) and s.get(dates[i - 6]):
                o["pre5"] = round((p0 / s[dates[i - 6]] - 1) * 100 - (b.iloc[i - 1] / b.iloc[i - 6] - 1) * 100, 3)
            dj = dret[r.sym]
            for h in HORIZONS:
                j = i + h - 1
                if j >= len(dates) or pd.isna(s.get(dates[j])):
                    continue
                if (dj.loc[dates[i]:dates[j]] > JUMP).any():
                    o["jump"] = True
                    break
                rr, mm = (s[dates[j]] / p0 - 1) * 100, (cal.iloc[j] / m0 - 1) * 100
                o[f"r{h}"], o[f"m{h}"], o[f"ar{h}"] = round(rr, 3), round(mm, 3), round(rr - mm, 3)
                if bench is not None:
                    ee = (bench.iloc[j] / bench.iloc[i - 1] - 1) * 100
                    o[f"e{h}"], o[f"ae{h}"] = round(ee, 3), round(rr - ee, 3)
            rows.append(o)
    return pd.DataFrame(rows)


# ─────────────────────────────── G/Ç
def load_events() -> pd.DataFrame | None:
    files = sorted(EV_DIR.glob("*.parquet"))
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def save_events(df: pd.DataFrame) -> None:
    EV_DIR.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    for c in ("ts", "ts_eff", "ingested"):
        df[c] = pd.to_datetime(df[c], utc=True)
    df["dir"] = pd.to_numeric(df["dir"], errors="coerce").astype("Int8")
    for c in ("conf", "mag"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    months = df["ts"].dt.strftime("%Y-%m")
    keep = set()
    for m, g in df.groupby(months):
        p = EV_DIR / f"{m}.parquet"
        g.sort_values(["ts", "id", "sym"]).to_parquet(p, index=False, compression="zstd")
        keep.add(p.name)
    for f in EV_DIR.glob("*.parquet"):
        if f.name not in keep:
            f.unlink()


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def fetch_kap(frm: date, to: date) -> list[dict]:
    from . import http
    rows = []
    d = frm
    while d <= to:                                         # haftalık parçalar (API yanıtı sınırlı)
        e = min(to, d + timedelta(days=6))
        r = http.post(KAP_LIST, json={"fromDate": d.isoformat(), "toDate": e.isoformat(), "mkkMemberOidList": [], "subjectList": []},
                      headers={"Referer": "https://www.kap.org.tr/tr/bildirim-sorgu", "Accept": "application/json", "Content-Type": "application/json"})
        try:
            part = r.json() if r is not None else []
        except ValueError:
            part = []
        log.info("KAP %s–%s: %d bildirim", d, e, len(part))
        rows += part if isinstance(part, list) else []
        d = e + timedelta(days=1)
    return rows


def fetch_buybacks() -> list[dict]:
    from . import http
    r = http.get(BB_URL, timeout=60)
    try:
        return r.json() if r is not None else []
    except ValueError:
        return []


def update_px(symbols: list[str], old: pd.DataFrame | None, full: bool) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        return old
    yfs = {s: YF.get(s, s if s.startswith("^") or "." in s else f"{s}.IS") for s in symbols}
    frames = _download(yf, yfs, full)
    got = {f.sym.iloc[0] for f in frames}
    for size, wait in ((25, 20), (8, 60)):               # Yahoo hız sınırı: eksikleri küçük parçalarla, bekleyerek yeniden dene
        miss = {s: y for s, y in yfs.items() if s not in got}
        if not miss:
            break
        log.info("Fiyat: %d sembol eksik, %d'lik parçalarla yeniden deneniyor", len(miss), size)
        import time as _t
        _t.sleep(wait)
        more = _download(yf, miss, full, size=size, pause=2)
        frames += more
        got |= {f.sym.iloc[0] for f in more}
    log.info("Fiyat: %d/%d sembol", len(got), len(yfs))
    if not frames:
        return old
    new = pd.concat(frames, ignore_index=True)
    allp = new if old is None or old.empty else pd.concat([old.assign(date=pd.to_datetime(old["date"]).dt.date), new], ignore_index=True)
    allp = allp.drop_duplicates(["sym", "date"], keep="last").sort_values(["sym", "date"])
    if not full and old is not None:
        # düzeltilmiş kapanış geçmişi yeni temettü/bölünmeyle değişir: son 1 ayın oranıyla eski satırları ölçekle
        allp = _rescale_adj(allp, new)
    return allp.reset_index(drop=True)


def _download(yf, yfs: dict[str, str], full: bool, size: int = 60, pause: float = 1.0) -> list[pd.DataFrame]:
    import time as _t
    frames = []
    items = list(yfs.items())
    for i in range(0, len(items), size):
        if i:
            _t.sleep(pause)
        part = dict(items[i:i + size])
        try:
            df = yf.download(" ".join(part.values()), period=f"{PX_YEARS}y" if full else "1mo", interval="1d", group_by="ticker",
                             auto_adjust=False, actions=False, threads=True, progress=False)
        except Exception as e:                              # noqa: BLE001 — bir parça düşerse diğerleri devam
            log.warning("Fiyat indirilemedi: %s", e)
            continue
        for sym, y in part.items():
            try:
                g = df[y] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            g = g.dropna(subset=["Close"])
            if g.empty:
                continue
            frames.append(pd.DataFrame({"sym": sym, "date": pd.to_datetime(g.index).date, "close": g["Close"].round(4).values,
                                        "adj_close": g["Adj Close"].round(4).values, "volume": g["Volume"].fillna(0).astype("int64").values}))
    return frames


def _rescale_adj(allp: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    first = new.sort_values("date").groupby("sym").first()
    out = []
    for sym, g in allp.groupby("sym", sort=False):
        if sym in first.index:
            d0 = first.loc[sym, "date"]
            ref = g[g.date == d0]
            if len(ref) and ref["close"].iloc[0]:
                k_new = first.loc[sym, "adj_close"] / first.loc[sym, "close"]
                old_mask = g.date < d0
                k_old = (g.loc[old_mask, "adj_close"] / g.loc[old_mask, "close"]).iloc[-1] if old_mask.any() else k_new
                if k_old and abs(k_new / k_old - 1) > 1e-4:
                    g = g.copy()
                    g.loc[old_mask, "adj_close"] = (g.loc[old_mask, "adj_close"] * k_new / k_old).round(4)
        out.append(g)
    return pd.concat(out)


def clusters(ev: pd.DataFrame) -> pd.Series:
    """Aynı hikâye kümesi: aynı hisse ve günde, başlığı neredeyse aynı olaylar (kelime Jaccard ≥ 0,6; ör. aynı haberin
    birkaç kaynaktaki kopyası). Satırlar silinmez; olay çalışması küme başına tek (ilk) olayı kullanır.
    Dönen seri: satır → kümenin ilk olayının kimliği (tek başına olan satırda kendi kimliği)."""
    out = ev["id"].copy()
    e = ev[ev.sym.fillna("").ne("") & ev.title.notna()]
    if e.empty:
        return out
    e = e.sort_values("ts")
    day = pd.to_datetime(e.ts, utc=True).dt.date
    words = e.title.map(lambda t: frozenset(w for w in re.findall(r"\w+", _fold(t)) if len(w) > 2))
    for _, idx in e.groupby([e.sym, day]).groups.items():
        if len(idx) < 2:
            continue
        heads: list[tuple[frozenset, str]] = []
        for i in idx:
            w = words[i]
            hit = next((cid for x, cid in heads if w and x and len(w & x) / len(w | x) >= 0.6), None)
            if hit:
                out[i] = hit
            else:
                heads.append((w, ev.at[i, "id"]))
    return out


MULTI_OK = {"idari", "borsa_tedbir", "iceriden", "geri_alim"}     # aynı gün birden çok gerçek bildirim olağan


def near_dups(ev: pd.DataFrame) -> tuple[int, int]:
    """Olası tekrar (kümeye bağlanan satır) ve hisseli satır sayısı; aynı gün çoklu bildirimi olağan tipler hariç."""
    e = ev[ev.sym.fillna("").ne("") & ~ev.type.isin(MULTI_OK)]
    return int((e["cluster"] != e["id"]).sum()), len(e)


def px_gap_ratio(px: pd.DataFrame, symbols: list[str], since: date) -> tuple[float, list[str]]:
    """BIST hisseleri için XU100 seanslarına göre eksik gün oranı (son ~1 yıl) ve en eksik semboller."""
    if px is None or px.empty:
        return 1.0, []
    p = px.assign(date=pd.to_datetime(px["date"]).dt.date)
    days = set(p[(p.sym == "XU100") & (p.date >= since)].date)
    if not days:
        return 1.0, []
    miss, tot, worst = 0, 0, []
    have = p[p.date >= since].groupby("sym")["date"].apply(set)
    for s in symbols:
        h = have.get(s, set())
        first = min(h) if h else None
        exp = {d for d in days if first and d >= first} if h else days
        m = len(exp - h)
        miss += m; tot += len(exp)
        if m:
            worst.append((m, s))
    return (miss / tot if tot else 1.0), [s for _, s in sorted(worst, reverse=True)[:10]]


# ─────────────────────────────── çalıştırma
def run(now: datetime | None = None, px_force: bool = False) -> dict:
    now_ts = pd.Timestamp(now or datetime.now(timezone.utc))
    now_ts = now_ts.tz_localize("UTC") if now_ts.tzinfo is None else now_ts.tz_convert("UTC")
    OUT.mkdir(parents=True, exist_ok=True)
    st = _json(STATE, {})
    old = load_events()
    if st.get("schema") != SCHEMA:
        log.info("Olay şeması %s → %s: tablo yeniden dolduruluyor", st.get("schema"), SCHEMA)
        old, st = None, {"px_day": st.get("px_day")}
        for f in EV_DIR.glob("*.parquet"):
            f.unlink()
    uni_rows = _json(DATA / "fin" / "_universe.json", {}).get("members") or []
    uni = [m if isinstance(m, str) else m.get("code") for m in uni_rows]
    useq = set(filter(None, uni))

    # 1) KAP: ilk turda 90 gün geriye, sonra son başarılı tarihten bir gün önce başlayarak
    today = now_ts.tz_convert(IST).date()
    last = date.fromisoformat(st["kap_to"]) if st.get("kap_to") else today - timedelta(days=BACKFILL_DAYS)
    kap_rows = fetch_kap(max(last - timedelta(days=1), today - timedelta(days=BACKFILL_DAYS)), today)
    new = from_kap_rows(kap_rows, useq or None)
    if kap_rows:
        st["kap_to"] = today.isoformat()

    # 2) panelin kendi verisi
    feed = _json(DATA / "feed.json", {}).get("items", [])
    new += from_feed(feed)
    new += from_signals(_json(DATA / "signals.json", {}).get("items", []))
    new += from_research(_json(DATA / "research.json", {}).get("notes", []))
    new += from_calendar(_json(DATA / "calendar.json", {}).get("events", []), now_ts)
    new += from_dividends(_json(DATA / "fin" / "_dividends.json", {}))
    new += from_buybacks(fetch_buybacks())

    ev, dup = merge(old, new, now_ts)

    # 3) fiyat: günde bir (İstanbul 18:45 sonrası) ya da ilk kurulumda tam geçmiş
    px = pd.read_parquet(PX) if PX.exists() else None
    us = sorted({s for s in ev.loc[ev.market == "US", "sym"].dropna() if s and s.isascii() and len(s) <= 6})
    wl = sorted({s for s in ev.loc[ev.market == "BIST", "sym"].dropna() if s})
    syms = list(YF) + sorted(set(useq) | set(wl) | set(us))           # endeksler önce: takvim ve getiri onlara bağlı
    loc = now_ts.tz_convert(IST)
    due = px is None or px_force or (st.get("px_day") != loc.date().isoformat() and loc.time() >= time(18, 45)) or set(syms) - set(px.sym.unique())
    if due:
        full = px is None or px_force
        missing = [] if px is None else sorted(set(syms) - set(px.sym.unique()))
        px = update_px(syms, px, full=full)
        if missing and not full:
            px = _merge_new_syms(px, missing)
        if px is not None:
            px.to_parquet(PX, index=False, compression="zstd")
            st["px_day"] = loc.date().isoformat()

    # 4) ts_eff (seans takvimi fiyattan) ve getiriler
    sess = {m: sessions_from_px(px, m) for m in SESS}
    eff = [ts_effective(pd.Timestamp(t), m if m in SESS else "BIST", sess[m if m in SESS else "BIST"])[0] for t, m in zip(ev.ts, ev.market)]
    ev["ts_eff"] = eff
    ev = ev.reset_index(drop=True)
    ev["cluster"] = clusters(ev)
    save_events(ev)
    ret = event_returns(ev, px, sorted(useq)) if px is not None else pd.DataFrame()
    if not ret.empty:
        ret.to_parquet(RET, index=False, compression="zstd")

    # 5) özet ve kabul ölçütleri
    since90 = (now_ts - pd.Timedelta(days=BACKFILL_DAYS))
    e90 = ev[pd.to_datetime(ev.ts, utc=True) >= since90]
    gap, worst = px_gap_ratio(px, [s for s in uni if s], loc.date() - timedelta(days=365))
    # gecikme: bu turda ilk kez görülen ve son 2 günde yayımlanmış olaylar (geri doldurma sayılmaz)
    ing, tsu = pd.to_datetime(ev.ingested, utc=True), pd.to_datetime(ev.ts, utc=True)
    fresh = (ing == now_ts) & (tsu >= now_ts - pd.Timedelta(days=2))
    lag = ((ing - tsu).dt.total_seconds() / 60)[fresh]
    nd, nt = near_dups(e90)
    summary = {
        "generated": now_ts.isoformat(timespec="seconds"),
        "events": int(len(ev)), "events_90d": int(len(e90)), "ids_90d": int(e90.id.nunique()),
        "by_type_90d": e90.type.value_counts().to_dict(), "by_src_90d": e90.src.str.split(":").str[0].value_counts().to_dict(),
        "syms_90d": int(e90.sym.replace("", pd.NA).dropna().nunique()),
        "overlap_in_batch": dup,                                   # aynı olay birden çok kaynakta (birleştirildi)
        "near_dup": nd, "near_dup_rate": round(nd / max(1, nt), 4),
        "px": {"symbols": int(px.sym.nunique()) if px is not None else 0, "rows": int(len(px)) if px is not None else 0,
               "last": str(px.date.max()) if px is not None else None, "gap_ratio_1y": round(gap, 4), "worst": worst},
        "returns": {"rows": int(len(ret)), "with_r20": int(ret["r20"].notna().sum()) if "r20" in ret else 0,
                    "jump_excluded": int(ret["jump"].sum()) if "jump" in ret else 0},
        "median_lag_min": round(float(lag.median()), 1) if len(lag) else None, "lag_n": int(len(lag)),
        "kap_to": st.get("kap_to"),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    st["schema"] = SCHEMA
    STATE.write_text(json.dumps(st), encoding="utf-8")
    log.info("Olay veritabanı: %d olay (%d yeni satır, %d tekrar), %d getiri satırı", len(ev), len(new), dup, len(ret))
    return summary


def _merge_new_syms(px: pd.DataFrame | None, syms: list[str]) -> pd.DataFrame | None:
    """Evrene yeni giren semboller için tam geçmiş (artımlı turda yalnız 1 ay gelirdi)."""
    add = update_px(syms, None, full=True)
    if add is None:
        return px
    return pd.concat([px, add], ignore_index=True).drop_duplicates(["sym", "date"], keep="last").sort_values(["sym", "date"]).reset_index(drop=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(run(px_force="--px-full" in sys.argv), ensure_ascii=False, indent=1, default=str))
