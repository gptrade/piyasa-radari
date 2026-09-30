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
            "summary": {"type": "string", "description": "2-3 cümlelik değerlendirme"},
            "key_points": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                      "description": "Değerlendirmeyi bozabilecek noktalar"},
            "affected_tickers": {"type": "array", "items": {"type": "string"}},
            "figures": {"type": "object", "additionalProperties": {"type": "string"},
                        "description": "Metinde geçen önemli rakamlar: ör. {'hedef fiyat': '45 TL'}"},
        },
        "required": ["sentiment", "confidence", "materiality", "horizon", "category",
                     "headline_tr", "summary", "key_points", "risks", "affected_tickers"],
    },
}


SENTIMENTS = {"bullish", "bearish", "neutral"}
LEVELS = {"low", "medium", "high"}
HORIZONS = {"intraday", "days", "weeks", "long_term"}


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

    def assess(self, system: str, prompt: str) -> dict | None:
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=900, system=system,
                tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
                messages=[{"role": "user", "content": prompt}],
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
 "category": "kısa kategori", "headline_tr": "tek cümle başlık", "summary": "2-3 cümle",
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


class GeminiProvider:
    name = "Gemini"

    def __init__(self, models: list[str], key: str):
        self.models = [m for m in models if m]
        self.model = self.models[0]
        self.key = key

    def assess(self, system: str, prompt: str) -> dict | None:
        import requests
        body = {
            "systemInstruction": {"parts": [{"text": system + "\n" + GEMINI_FORMAT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                 "maxOutputTokens": 1200},
        }
        last = ""
        for model in list(self.models):
            for attempt in range(3):
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
                    data = r.json()
                    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    return parse_json_text(text)
                last = f"HTTP {r.status_code}: {r.text[:160]}"
                if r.status_code == 404:              # model adı yok/emekli: sıradaki modeli dene
                    self.models.remove(model)
                    break
                if r.status_code in (429, 500, 502, 503) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                if r.status_code in (400,) and "API key" not in r.text:
                    raise RuntimeError(last)          # bu kayda özgü hata; sağlayıcı ayakta
                raise ProviderDown(last)
            else:
                raise ProviderDown(last)
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
                          *(cfg.get("gemini_fallback_models") or ["gemini-flash-latest", "gemini-3.7-flash"])]
                self.providers.append(GeminiProvider(models, os.environ["GEMINI_API_KEY"]))
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
        limit = 40000 if item.source_type == "report" else 4000
        meta = {k: v for k, v in item.extra.items() if k not in ("full_text",)}
        return (f"Kaynak: {item.source} ({item.source_type})\nPiyasa: {item.market}\n"
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
                out = normalize(p.assess(system, prompt))
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
