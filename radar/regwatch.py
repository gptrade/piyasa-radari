"""Uluslararası Regülasyon Takip: BCBS/BIS, Azerbaycan, Türkiye, Körfez ve Orta Doğu bankacılık düzenleyicilerinin risk
yönetimi ve model validasyonu yayınları.

`python -m radar.regwatch` — regulasyon.yml iş akışı (günlük; her turda birkaç kurum, yaklaşık haftada bir tam tur).
Çıktı: site/data/regulasyon/regwatch.json

Toplama
- Kaynak gösteren Google araması (Gemini API, google_search aracı): her kurum için yalnız o kurumun alan adlarında,
  son ~120 günde yayımlanan metodoloji / rehber / istişare / sirküler aranır. Kurum sitelerinin çoğu yurt dışı
  sunuculardan doğrudan erişime kapalı olduğu için tek güvenilir yol bu. Model yalnız arama sonuçlarındaki
  dokümanları döndürür; link, aramanın gösterdiği kaynaklardan biri değilse ya da kurumun alan adında değilse atılır.
- config/regwatch.yml'de feeds tanımlıysa kurumun RSS akışı doğrudan okunur.
- Faiz kararı, enflasyon raporu ve rutin makro duyurular dışarıda kalır.
Yönetici özeti: son 90 günün bulgularından en kritik 3 eğilim (haftada bir).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
import yaml

from .config import CONFIG, DATA

log = logging.getLogger("radar.regwatch")

OUT = DATA / "regulasyon" / "regwatch.json"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.7-flash", "gemini-flash-latest"]
WINDOW_DAYS = 120
PER_RUN = 4                      # her çalıştırmada aranan kurum sayısı (17 kurum ≈ 5 günde bir tam tur)
TYPES = {"taslak": "Taslak / istişare", "nihai": "Nihai düzenleme", "rehber": "Rehber / ilke", "duyuru": "Duyuru / sirküler"}
EXCLUDE = re.compile(r"monetary policy (committee|decision)|policy rate|interest rate decision|inflation report|"
                     r"faiz karar|enflasyon rapor|para politikası kurulu|exchange rate|döviz kuru", re.I)


def load_config(path=None) -> dict:
    return yaml.safe_load((path or CONFIG / "regwatch.yml").read_text(encoding="utf-8"))


def load_state() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"items": [], "runs": {}, "summary": None}


def save_state(st: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    st["items"].sort(key=lambda x: (x.get("date") or "", x.get("first_seen") or ""), reverse=True)
    OUT.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def domain_ok(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def resolve(url: str) -> str:
    """Google'ın arama-kaynak yönlendirmesini (vertexaisearch…/grounding-api-redirect/…) gerçek adrese çevirir."""
    if "grounding-api-redirect" not in url:
        return url
    try:
        r = requests.get(url, allow_redirects=False, timeout=20, headers={"User-Agent": "piyasa-radari/1.0"})
        return r.headers.get("Location") or url
    except requests.RequestException:
        return url


def parse_items(text: str) -> list[dict]:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    for cand in (t, (re.search(r"\[.*\]", t, re.S) or re.search(r"\{.*\}", t, re.S) or [None])[0]):
        if not cand:
            continue
        try:
            x = json.loads(cand)
        except (ValueError, TypeError):
            continue
        if isinstance(x, dict):
            x = x.get("documents") or x.get("items") or []
        if isinstance(x, list):
            return [d for d in x if isinstance(d, dict)]
    return []


def norm_date(s) -> str | None:
    s = str(s or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s[:10]
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})-(\d{2})$", s)
    return f"{s}-01" if m else None


def topic_tags(text: str, topics: list[dict]) -> list[str]:
    low = text.lower()
    return [t["key"] for t in topics if any(term.lower() in low for term in t["terms"])]


class Grounded:
    """Gemini + Google araması. Yanıt metni ve aramanın gösterdiği kaynaklar (uri, başlık)."""

    def __init__(self, key: str, models: list[str] | None = None, gap: float = 6.0):
        self.key, self.models, self.gap, self.last, self.dead = key, list(models or MODELS), gap, 0.0, set()
        self.calls = 0

    def ask(self, prompt: str) -> tuple[str, list[dict]] | None:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4000}}
        for model in [m for m in self.models if m not in self.dead]:
            for attempt in range(2):
                wait = self.last + self.gap - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()
                self.calls += 1
                try:
                    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                                      headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
                except requests.RequestException as e:
                    log.warning("%s %s", model, type(e).__name__)
                    continue
                if r.status_code == 200:
                    c = (r.json().get("candidates") or [{}])[0]
                    text = "".join(p.get("text", "") for p in ((c.get("content") or {}).get("parts") or []) if not p.get("thought"))
                    chunks = [ch.get("web") or {} for ch in ((c.get("groundingMetadata") or {}).get("groundingChunks") or [])]
                    return text, [{"uri": x.get("uri"), "title": x.get("title")} for x in chunks if x.get("uri")]
                log.warning("%s HTTP %s %s", model, r.status_code, r.text[:160])
                if r.status_code in (400, 403, 404) or (r.status_code == 429 and "PerDay" in r.text):
                    self.dead.add(model)
                    break
                if r.status_code in (429, 500, 503):
                    time.sleep(15 * (attempt + 1))
        return None


PROMPT = """Sen kıdemli bir finansal regülasyon, risk yönetimi ve model validasyonu analistisin.
Google aramasıyla YALNIZCA şu resmi alan adlarında ara: {domains} ({name}, {country}).
Dönem: {start} – {end} arasında yayımlanan dokümanlar.
Konular: model validasyonu, model risk yönetimi (MRM), IRB, AI/ML model yönetişimi, backtesting, IFRS 9 / TFRS 9 beklenen kredi
zararı (ECL), stres testi, ICAAP, ILAAP, ALM, likidite riski, bankacılık hesaplarından kaynaklanan faiz oranı riski (IRRBB),
Basel III / Basel III son reformlar, RWA, kredi riski, piyasa riski (FRTB), operasyonel risk, iklim riski.
Dahil et: düzenleme, yönetmelik, sirküler (circular), rehber/ilke (guideline/principles), istişare/taslak (consultation paper,
draft), metodoloji dokümanları, denetim beklentisi duyuruları. Hariç tut: faiz kararları, enflasyon raporları, rutin makro
duyurular, basın açıklaması niteliğinde genel haberler, konferans/konuşmalar.
Arama sonuçlarında gerçekten gördüğün dokümanları listele; görmediğin bir dokümanı ya da linki ASLA uydurma.
Yanıtın SADECE bir JSON dizisi olsun (bulamazsan []):
[{{"title": "orijinal doküman başlığı", "title_tr": "Türkçe başlık", "date": "YYYY-AA-GG", "type": "taslak|nihai|rehber|duyuru",
"url": "dokümanın doğrudan linki", "summary_tr": "1-2 cümle Türkçe özet: ne değişiyor, kimleri etkiliyor"}}]"""


def search_regulator(g: Grounded, reg: dict, topics: list[dict], today: dt.date) -> list[dict] | None:
    start = today - dt.timedelta(days=WINDOW_DAYS)
    res = g.ask(PROMPT.format(domains=", ".join(reg["domains"]), name=reg["name"], country=reg["country"],
                              start=start.isoformat(), end=today.isoformat()))
    if res is None:
        return None
    text, chunks = res
    sources = []
    for c in chunks:
        u = resolve(c["uri"])
        sources.append({"url": u, "title": c.get("title") or ""})
    allowed = [s for s in sources if domain_ok(s["url"], reg["domains"])]
    out = []
    for d in parse_items(text):
        url = str(d.get("url") or "").strip()
        title = str(d.get("title") or "").strip()
        if not title:
            continue
        if url and "grounding-api-redirect" in url:
            url = resolve(url)
        # link, aramanın gösterdiği kaynaklardan biri olmalı (ya da aynı alan adında ve kaynaklarda o sayfa geçmeli)
        src_urls = {s["url"].rstrip("/") for s in allowed}
        if not (url and domain_ok(url, reg["domains"]) and (url.rstrip("/") in src_urls or any(url.startswith(s) or s.startswith(url) for s in src_urls))):
            # kaynaklardan başlığı en çok örtüşeni dene
            best = next((s for s in allowed if s["title"] and (s["title"].lower()[:40] in title.lower() or title.lower()[:40] in s["title"].lower())), None)
            if not best:
                continue
            url = best["url"]
        date = norm_date(d.get("date"))
        if date and date < start.isoformat():
            continue
        blob = f"{title} {d.get('title_tr') or ''} {d.get('summary_tr') or ''}"
        if EXCLUDE.search(blob):
            continue
        typ = str(d.get("type") or "duyuru").lower()
        out.append({"reg": reg["id"], "title": title, "title_tr": str(d.get("title_tr") or "").strip() or None, "date": date,
                    "type": typ if typ in TYPES else "duyuru", "url": url, "summary": str(d.get("summary_tr") or "").strip()[:500],
                    "topics": topic_tags(blob, topics), "via": "arama"})
    return out


SUMMARY_PROMPT = """Aşağıda bankacılık düzenleyicilerinin son 90 günde yayımladığı risk yönetimi ve model validasyonu dokümanları var.
Dönemin en kritik 3 regülatif eğilimini çıkar. Her eğilim için: kısa başlık, 2-3 cümle açıklama (Türkçe; somut doküman ve kurum
adlarıyla), ilgili kurumlar. Türkiye'deki bankalar için çıkarımı da bir cümleyle ekle.
SADECE JSON: {{"trends": [{{"title": "...", "detail": "...", "regulators": ["..."], "tr_impact": "..."}}]}}

DOKÜMANLAR:
{docs}"""


def summarize(g: Grounded | None, items: list[dict], regs: dict, today: dt.date) -> dict | None:
    if g is None:
        return None
    recent = [i for i in items if (i.get("date") or i.get("first_seen", "")[:10]) >= (today - dt.timedelta(days=90)).isoformat()][:80]
    if len(recent) < 3:
        return None
    docs = "\n".join(f"- {regs[i['reg']]['name']} | {i.get('date') or '?'} | {i['title']} | {TYPES.get(i['type'], i['type'])} | {i.get('summary') or ''}"
                     for i in recent)
    body = {"contents": [{"role": "user", "parts": [{"text": SUMMARY_PROMPT.format(docs=docs)}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000, "responseMimeType": "application/json"}}
    for model in [m for m in g.models if m not in g.dead]:
        try:
            r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                              headers={"x-goog-api-key": g.key, "Content-Type": "application/json"})
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        c = (r.json().get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in ((c.get("content") or {}).get("parts") or []))
        try:
            x = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        except ValueError:
            continue
        if isinstance(x, dict) and isinstance(x.get("trends"), list):
            return {"date": today.isoformat(), "n_docs": len(recent), "trends": x["trends"][:3], "model": model}
    return None


def run(today: dt.date | None = None, per_run: int = PER_RUN) -> dict:
    today = today or dt.date.today()
    cfg = load_config()
    regs = {r["id"]: r for r in cfg["regulators"]}
    st = load_state()
    key = os.environ.get("GEMINI_API_KEY")
    g = Grounded(key) if key else None
    if g is None:
        log.warning("GEMINI_API_KEY yok: arama yapılmadı")
    else:
        due = sorted((r for r in cfg["regulators"] if r.get("search")), key=lambda r: st["runs"].get(r["id"], {}).get("at", ""))[:per_run]
        known = {i["url"].rstrip("/") for i in st["items"]}
        for reg in due:
            found = search_regulator(g, reg, cfg["topics"], today)
            st["runs"][reg["id"]] = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                     "ok": found is not None, "found": len(found or [])}
            for it in found or []:
                if it["url"].rstrip("/") in known:
                    continue
                it["first_seen"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                st["items"].append(it)
                known.add(it["url"].rstrip("/"))
            log.info("%s: %s doküman", reg["name"], "hata" if found is None else len(found))
        if not st.get("summary") or st["summary"].get("date", "") <= (today - dt.timedelta(days=7)).isoformat():
            s = summarize(g, st["items"], regs, today)
            if s:
                st["summary"] = s
    st["regulators"] = [{k: r.get(k) for k in ("id", "name", "country", "cc", "domains")} for r in cfg["regulators"]]
    st["topics"] = [{"key": t["key"], "label": t["label"]} for t in cfg["topics"]]
    st["types"] = TYPES
    st["generated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    save_state(st)
    return st


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    per = int(sys.argv[1]) if len(sys.argv) > 1 else PER_RUN
    st = run(per_run=per)
    log.info("Regülasyon: %d doküman", len(st["items"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
