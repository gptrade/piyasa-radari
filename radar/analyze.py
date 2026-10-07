"""AI değerlendirmesi (yön, güven, önem, ufuk, gerekçe).

Sıra: Claude → Gemini. Claude'un anahtarı yoksa, kredisi bittiyse, anahtar geçersizse,
hız/kota sınırına takıldıysa ya da servise ulaşılamıyorsa değerlendirme Gemini'ye düşer.
"""
from __future__ import annotations

import json
import logging
import os
import time
import re

from .models import Item

log = logging.getLogger("radar.analyze")

SYSTEM = """Sen Borsa İstanbul ve ABD hisse piyasalarını takip eden deneyimli bir sell-side/buy-side
analistsin. Sana tek bir haber, KAP/SEC bildirimi, sosyal medya gönderisi veya aracı kurum raporu
verilecek. Görevin: bu içeriğin ilgili hisse(ler) üzerindeki OLASI kısa vadeli fiyat etkisini
değerlendirmek.

Kurallar:
- Sadece verilen metne ve genel finans bilgisine dayan; metinde olmayan rakam uydurma.
- Zaten fiyatlanmış olabilecek, rutin veya belirsiz haberlerde "neutral" de ve güveni düşük tut.
- Sosyal medya gönderileri söylenti olabilir; kaynağı doğrulanmamışsa güveni düşür.
- KAP'ta rutin bildirimler (genel kurul çağrısı, bağımsız denetim, sermaye piyasası aracı ihracı
  bilgilendirmesi vb.) genelde düşük önemlidir; pay geri alımı, bedelsiz/bedelli sermaye artırımı,
  yeni iş ilişkisi/ihale, temettü, finansal sonuçlar, yönetim değişikliği, SPK cezası daha önemlidir.
- SEC'te 8-K madde numaraları, Form 4 (içeriden alım/satım), 13D/13G (önemli pay) ayrımını gözet.
- Aracı kurum raporlarında hedef fiyat, tavsiye değişikliği ve tahmin revizyonunu öne çıkar.
- Borsa İstanbul tedbirleri (brüt takas, tek fiyat, kredili işlem/açığa satış yasağı, emir paketi)
  likiditeyi düşürür ve kısa vadede genelde olumsuzdur; tedbirin kaldırılması olumludur. Önem: yüksek.
- SPK bülteninde sadece ilgili şirketin kararına odaklan: bedelsiz/bedelli onayı, halka arz,
  pay satış izni, işlem yasağı, idari para cezası. Bülten metni kesitler hâlinde verilir.
- TCMB PPK kararı ve duyurularında beklentiye göre sürprizi değerlendir; hangi izleme listesi
  hisselerinin (özellikle bankalar) nasıl etkileneceğini affected_tickers'a yaz.
- Fed ve ECB kararlarında/konuşmalarında beklentiye göre şahin/güvercin sürprizi değerlendir; küresel faiz ve
  risk iştahı üzerinden BIST'e (bankalar, dış borçlu şirketler, ihracatçılar) ve ABD hisselerine etkisini yaz.
- GDELT alarmları dünya basınındaki haber hacmi/ton sıçramasıdır; başlıklardan olayı çıkar, tek başına kanıt
  değildir — güveni ölçülü tut, etkilenen izleme listesi hisselerini affected_tickers'a yaz.
- Kurum görünümlerinde (J.P. Morgan, BlackRock vb.) kurumun ana tezlerini, değerleme ve faiz görüşünü, gelişen
  piyasalar/Türkiye ile izleme listesi için çıkarımları özetle; kurumun görüşünü kendi görüşün gibi sunma.
- 10-Q/10-K yönetim değerlendirmesinde (MD&A) gelir/marj eğilimi, rehberlik ve yeni ya da büyüyen riskleri öne çıkar.
- Basın bültenleri şirketin kendi ağzından yazılır; pazarlama dilini ayıkla, rakamlara bak.
- Yatırım tavsiyesi verme; olasılıksal değerlendirme yap.
- Yanıt dili: {language}. Metin İngilizce olsa bile özeti {language} yaz."""

TOOL = {
    "name": "record_assessment",
    "description": "Haberin hisse üzerindeki olası etkisini kaydet.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100,
                           "description": "Yön tahminine güven, 0-100"},
            "materiality": {"type": "string", "enum": ["low", "medium", "high"],
                            "description": "Fiyatı hareket ettirme potansiyeli"},
            "horizon": {"type": "string", "enum": ["intraday", "days", "weeks", "long_term"]},
            "category": {"type": "string",
                         "description": "Kısa kategori: ör. geri alım, finansal sonuç, ihale, rehberlik, "
                                        "içeriden işlem, analist notu, makro, söylenti"},
            "headline_tr": {"type": "string", "description": "Tek cümlelik net başlık"},
            "event_label": {"type": "string",
                            "description": "Olayın en fazla 3 kelimelik etiketi, ör. 'Analist AL', "
                                           "'Hedef fiyat ↑', 'Geri alım', 'Brüt takas', 'Bilanço güçlü', 'Faiz sabit'"},
            "what": {"type": "string", "description": "Ne oldu? En fazla 8 kelime"},
            "why": {"type": "string", "description": "Neden önemli? En fazla 8 kelime"},
            "risk": {"type": "string", "description": "Ana risk / tersine döndürebilecek şey. En fazla 8 kelime"},
            "summary": {"type": "string", "description": "2-3 cümlelik değerlendirme"},
            "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                      "description": "Değerlendirmeyi bozabilecek noktalar"},
            "affected_tickers": {"type": "array", "items": {"type": "string"}},
            "figures": {"type": "object", "additionalProperties": {"type": "string"},
                        "description": "Metinde geçen önemli rakamlar: ör. {'hedef fiyat': '45 TL'}"},
        },
        "required": ["sentiment", "confidence", "materiality", "horizon", "category",
                     "headline_tr", "event_label", "what", "why", "risk", "summary", "key_points",
                     "risks", "affected_tickers"],
    },
}


DOC_NOTE = """BELGE ÖZETİ: Bu kayıt bir {kind}; metin belgenin kendisidir (uzunsa kesitler hâlinde).
Değerlendirmeyi belgeye dayandır ve özellikle şunları doldur:
- summary: 3-4 cümle; dönemin ana sonucu ve beklenti/önceki döneme göre durumu.
- key_points: en önemli 4 bulgu, mümkünse rakamla ve önceki döneme göre değişimle.
- figures: gelir/hasılat, FAVÖK veya faaliyet kârı, net kâr, marjlar, büyüme, (banka ise) net faiz marjı, özkaynak
  kârlılığı, (varsa) yönetimin rehberliği. Sadece metinde geçen rakamlar; birimi ve dönemi yaz (ör. '3Ç26: 12,4 mlr TL, +%35 y/y').
- risks: belgede açıkça geçen ya da rakamlardan çıkan riskler.

"""


SENTIMENTS = {"bullish", "bearish", "neutral"}
LEVELS = {"low", "medium", "high"}
HORIZONS = {"intraday", "days", "weeks", "long_term"}


def _words(v, n: int, chars: int) -> str:
    """Kısa alanları sınırla: en fazla n kelime / chars karakter."""
    w = str(v or "").strip().rstrip(".").split()
    return " ".join(w[:n])[:chars]


def normalize(raw: dict) -> dict | None:
    """Sağlayıcıdan gelen çıktıyı ortak biçime getirir; bozuk çıktıda None."""
    if not isinstance(raw, dict):
        return None
    sent = str(raw.get("sentiment", "")).lower().strip()
    if sent not in SENTIMENTS:
        return None
    try:
        f = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        f = 0.0
    if 0 < f < 1:                                          # 0.8 gibi oran → 80
        f *= 100
    conf = int(round(f))
    lst = lambda v, n: [str(x) for x in (v if isinstance(v, list) else [v] if v else [])][:n]
    out = {
        "sentiment": sent,
        "confidence": max(0, min(100, conf)),
        "materiality": raw.get("materiality") if raw.get("materiality") in LEVELS else "low",
        "horizon": raw.get("horizon") if raw.get("horizon") in HORIZONS else "days",
        "category": str(raw.get("category") or "")[:60],
        "headline_tr": str(raw.get("headline_tr") or "")[:200],
        "summary": str(raw.get("summary") or "")[:800],
        "event_label": _words(raw.get("event_label"), 4, 40),
        "what": _words(raw.get("what"), 10, 90),
        "why": _words(raw.get("why"), 10, 90),
        "risk": _words(raw.get("risk"), 10, 90),
        "key_points": lst(raw.get("key_points"), 4),
        "risks": lst(raw.get("risks"), 3),
        "affected_tickers": [t.upper() for t in lst(raw.get("affected_tickers"), 8)],
    }
    if isinstance(raw.get("figures"), dict):
        out["figures"] = {str(k): str(v) for k, v in list(raw["figures"].items())[:8]}
    return out


class ProviderDown(Exception):
    """Bu sağlayıcı bu tur için kullanılamaz (anahtar/kredi/kota/erişim)."""


# ------------------------------------------------------------------ Claude
class ClaudeProvider:
    name = "Claude"

    def __init__(self, model: str):
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(max_retries=2)
        return self._client

    def assess(self, system: str, prompt: str, max_tokens: int = 900) -> dict | None:
        return self.ask(system, prompt, TOOL, max_tokens=max_tokens)

    def ask(self, system: str, prompt: str, tool: dict, fmt: str = "", max_tokens: int = 900,
            media: list | None = None) -> dict | None:
        content = prompt
        if media:                                   # [(mime, bytes)]: görseller ve PDF'ler (taranmış rapor)
            import base64
            content = [{"type": "document" if mime == "application/pdf" else "image",
                        "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}}
                       for mime, data in media] + [{"type": "text", "text": prompt}]
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=max_tokens, system=system,
                tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as e:
            name, text = type(e).__name__, str(e)
            fatal = name in ("AuthenticationError", "PermissionDeniedError", "RateLimitError",
                             "APIConnectionError", "APITimeoutError", "InternalServerError",
                             "OverloadedError", "NotFoundError") \
                or getattr(e, "status_code", 0) in (402, 429, 500, 502, 503, 529) \
                or re.search(r"credit balance|billing|quota|insufficient", text, re.I)
            if fatal:
                raise ProviderDown(f"{name}: {text[:160]}") from e
            raise
        for block in msg.content:
            if getattr(block, "type", "") == "tool_use":
                return dict(block.input)
        return None


# ------------------------------------------------------------------ Gemini
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_FORMAT = """
Yanıtını SADECE aşağıdaki alanlara sahip tek bir JSON nesnesi olarak ver (başka metin yok):
{"sentiment": "bullish|bearish|neutral", "confidence": 0-100 tam sayı,
 "materiality": "low|medium|high", "horizon": "intraday|days|weeks|long_term",
 "category": "kısa kategori", "headline_tr": "tek cümle başlık",
 "event_label": "en fazla 3 kelime, ör. Analist AL", "what": "ne oldu (≤8 kelime)",
 "why": "neden önemli (≤8 kelime)", "risk": "ana risk (≤8 kelime)", "summary": "2-3 cümle",
 "key_points": ["en fazla 4 madde"], "risks": ["en fazla 3 madde"],
 "affected_tickers": ["HİSSE KODLARI"], "figures": {"etiket": "değer"}}"""


def parse_json_text(text: str) -> dict | None:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _gemini_msg(r) -> str:
    try:
        return str(r.json()["error"]["message"])[:140]
    except Exception:
        return r.text[:140]


def _quota_info(r) -> tuple[bool, float | None]:
    """429 gövdesinden: (günlük kota mı?, önerilen bekleme saniyesi)."""
    try:
        details = r.json()["error"].get("details") or []
    except Exception:
        return False, None
    daily, delay = False, None
    for d in details:
        for v in d.get("violations") or []:
            if "PerDay" in str(v.get("quotaId", "")):
                daily = True
        if d.get("retryDelay"):
            try:
                delay = float(str(d["retryDelay"]).rstrip("s"))
            except ValueError:
                pass
    return daily, delay


class GeminiProvider:
    name = "Gemini"

    def __init__(self, models: list[str], key: str, min_interval: float = 0.0, max_wait: float = 65.0):
        self.models = [m for m in models if m]
        self.model = self.models[0]
        self.key = key
        self.min_interval = min_interval      # ücretsiz katmanın dakika başı sınırına takılmamak için
        self.max_wait = max_wait
        self._last = 0.0

    def _pace(self) -> None:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def assess(self, system: str, prompt: str, max_tokens: int = 1200) -> dict | None:
        return self.ask(system, prompt, TOOL, GEMINI_FORMAT, max_tokens=max_tokens)

    def ask(self, system: str, prompt: str, tool: dict, fmt: str = "", max_tokens: int = 1200,
            media: list | None = None) -> dict | None:
        import base64
        import requests
        parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}} for mime, data in (media or [])]
        body = {
            "systemInstruction": {"parts": [{"text": system + "\n" + fmt}]},
            "contents": [{"role": "user", "parts": parts + [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                 "maxOutputTokens": max_tokens},
        }
        last = ""
        for model in list(self.models):
            for attempt in range(3):
                self._pace()
                try:
                    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=45,
                                      headers={"x-goog-api-key": self.key,
                                               "Content-Type": "application/json"})
                except requests.RequestException as e:
                    last = f"{type(e).__name__}"
                    time.sleep(2 * (attempt + 1))
                    continue
                if r.status_code == 200:
                    self.model = model
                    if self.models[0] != model:       # çalışan modeli bu tur için başa al (tekrar beklemesin)
                        self.models.remove(model)
                        self.models.insert(0, model)
                    data = r.json()
                    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    return parse_json_text(text)
                last = f"{model} HTTP {r.status_code}: {_gemini_msg(r)}"
                if r.status_code == 404:              # model adı yok/emekli: listeden çıkar, sıradakini dene
                    self.models.remove(model)
                    break
                if r.status_code == 429:
                    daily, delay = _quota_info(r)
                    if daily:                         # bu modelin günlük kotası bitti: bu tur çıkar, sıradakini dene
                        self.models.remove(model)
                        break
                    if attempt < 2:                   # dakikalık kota: Google'ın önerdiği kadar bekle
                        time.sleep(min(self.max_wait, (delay or 10) + 1))
                        continue
                    break
                if r.status_code in (500, 502, 503, 504):
                    if attempt < 2:
                        time.sleep(3 * (attempt + 1))
                        continue
                    break                             # bu model yoğun: sıradaki modeli dene
                if r.status_code == 400 and "API key" not in r.text:
                    raise RuntimeError(last)          # bu kayda özgü hata; sağlayıcı ayakta
                raise ProviderDown(last)              # 401/403: anahtar geçersiz
            else:
                continue                              # ağ hatası: sıradaki model
        raise ProviderDown(last or "Gemini modeli bulunamadı")


# ------------------------------------------------------------------ Analyzer
class Analyzer:
    def __init__(self, settings: dict):
        cfg = settings.get("analysis") or {}
        self.language = {"tr": "Türkçe", "en": "English"}.get(cfg.get("language", "tr"), "Türkçe")
        self.budget = int(cfg.get("max_items_per_run", 40))
        self.used = 0
        self.errors: list[str] = []
        self.counts: dict[str, int] = {}
        self.providers: list = []
        on = cfg.get("enabled", True)
        order = cfg.get("providers") or ["claude", "gemini"]
        for name in order:
            if name == "claude" and on and os.environ.get("ANTHROPIC_API_KEY"):
                self.providers.append(ClaudeProvider(cfg.get("model", "claude-haiku-4-5-20251001")))
            if name == "gemini" and on and os.environ.get("GEMINI_API_KEY"):
                models = [cfg.get("gemini_model", "gemini-3.8-flash"),
                          *(cfg.get("gemini_fallback_models") or ["gemini-3.7-flash", "gemini-flash-latest"])]
                self.providers.append(GeminiProvider(models, os.environ["GEMINI_API_KEY"],
                                                     float(cfg.get("gemini_min_interval_s", 4.5))))
        self.down: dict[str, str] = {}
        if not self.providers:
            log.info("AI anahtarı yok ya da analiz kapalı: değerlendirme atlanacak")

    @property
    def enabled(self) -> bool:
        return any(p.name not in self.down for p in self.providers)

    @property
    def model(self) -> str:
        live = [p for p in self.providers if p.name not in self.down]
        p = live[0] if live else (self.providers[0] if self.providers else None)
        return p.model if p else "yok"

    def status(self) -> dict:
        return {"model": self.model, "enabled": bool(self.providers), "used": self.used,
                "errors": self.errors, "by_provider": self.counts,
                "providers": [p.name for p in self.providers], "down": self.down}

    def can_run(self) -> bool:
        return self.enabled and self.used < self.budget

    def _err(self, msg: str) -> None:
        if len(self.errors) < 4 and msg not in self.errors:
            self.errors.append(msg)

    def prompt(self, item: Item, context: str) -> str:
        body = item.extra.get("full_text") or item.summary or "(özet yok)"
        doc = item.extra.get("doc")
        limit = 40000 if item.source_type == "report" or doc else 4000
        meta = {k: v for k, v in item.extra.items() if k not in ("full_text",)}
        note = DOC_NOTE.format(kind=doc["kind"]) if doc else ""
        return (note + f"Kaynak: {item.source} ({item.source_type})\nPiyasa: {item.market}\n"
                f"İlgili hisseler: {', '.join(item.tickers) or 'yok (piyasa geneli)'}\nYayın zamanı (UTC): {item.published}\n"
                f"Ek bilgi: {json.dumps(meta, ensure_ascii=False)}\n"
                f"Fiyat bağlamı: {context or 'yok'}\n\n"
                f"BAŞLIK: {item.title}\n\nMETİN:\n{body[:limit]}")

    def assess(self, item: Item, context: str = "") -> dict | None:
        if not self.can_run():
            return None
        self.used += 1
        system, prompt = SYSTEM.format(language=self.language), self.prompt(item, context)
        for p in self.providers:
            if p.name in self.down:
                continue
            try:
                out = normalize(p.assess(system, prompt, max_tokens=1600) if item.extra.get("doc")
                                else p.assess(system, prompt))
            except ProviderDown as e:
                self.down[p.name] = str(e)[:200]
                self._err(f"{p.name} devre dışı: {e}")
                log.warning("%s bu tur devre dışı, sıradaki sağlayıcıya geçiliyor: %s", p.name, e)
                continue
            except Exception as e:
                self._err(f"{p.name}: {type(e).__name__}: {str(e)[:140]}")
                log.warning("%s hatası (%s): %s", p.name, item.id, e)
                continue                               # bu kayıt için sıradaki sağlayıcıyı dene
            if out is None:
                self._err(f"{p.name}: geçersiz çıktı")
                continue
            out["model"] = p.model
            out["provider"] = p.name
            self.counts[p.name] = self.counts.get(p.name, 0) + 1
            return out
        return None

    def ask_json(self, system: str, prompt: str, tool: dict, fmt: str, max_tokens: int = 1500,
                 media: list | None = None) -> dict | None:
        """Genel amaçlı yapılandırılmış istek (ör. dönemsel özet, rapor okuma); aynı sağlayıcı sırası ve yedekleme.
        media: [(mime, bytes)] görsel/PDF ekleri (sağlayıcı görüntüden okur)."""
        for p in self.providers:
            if p.name in self.down:
                continue
            try:
                out = p.ask(system, prompt, tool, fmt, max_tokens, media=media) if media else p.ask(system, prompt, tool, fmt, max_tokens)
            except ProviderDown as e:
                self.down[p.name] = str(e)[:200]
                self._err(f"{p.name} devre dışı: {e}")
                continue
            except Exception as e:
                self._err(f"{p.name}: {type(e).__name__}: {str(e)[:140]}")
                continue
            if isinstance(out, dict):
                out["_provider"], out["_model"] = p.name, p.model
                return out
        return None
