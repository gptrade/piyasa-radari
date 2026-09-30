"""Claude ile haber/bildirim değerlendirmesi (yön, güven, önem, ufuk, gerekçe)."""
from __future__ import annotations

import json
import logging
import os

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


class Analyzer:
    def __init__(self, settings: dict):
        cfg = settings.get("analysis") or {}
        self.enabled = cfg.get("enabled", True) and bool(os.environ.get("ANTHROPIC_API_KEY"))
        self.model = cfg.get("model", "claude-haiku-4-5-20251001")
        self.language = {"tr": "Türkçe", "en": "English"}.get(cfg.get("language", "tr"), "Türkçe")
        self.budget = int(cfg.get("max_items_per_run", 40))
        self.used = 0
        self._client = None
        if not self.enabled:
            log.info("ANTHROPIC_API_KEY yok ya da analiz kapalı: AI değerlendirmesi atlanacak")

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def can_run(self) -> bool:
        return self.enabled and self.used < self.budget

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
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=900,
                system=SYSTEM.format(language=self.language),
                tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
                messages=[{"role": "user", "content": self.prompt(item, context)}],
            )
        except Exception as e:
            log.warning("Claude hatası (%s): %s", item.id, e)
            return None
        for block in msg.content:
            if getattr(block, "type", "") == "tool_use":
                out = dict(block.input)
                out["model"] = self.model
                return out
        return None
