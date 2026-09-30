"""Telegram bildirimleri."""
from __future__ import annotations

import html
import logging
import os

from . import http
from .models import Item

log = logging.getLogger("radar.notify")

LEVEL = {"low": 0, "medium": 1, "high": 2}
ICON = {"bullish": "🟢 YÜKSELİŞ", "bearish": "🔴 DÜŞÜŞ", "neutral": "⚪ NÖTR"}


def should_notify(item: Item, cfg: dict) -> bool:
    a = item.analysis
    if not a:
        return False
    if cfg.get("only_directional", True) and a.get("sentiment") == "neutral":
        return False
    if int(a.get("confidence", 0)) < int(cfg.get("min_confidence", 70)):
        return False
    return LEVEL.get(a.get("materiality", "low"), 0) >= LEVEL.get(cfg.get("min_materiality", "medium"), 1)


def format_message(item: Item, site_url: str | None) -> str:
    a = item.analysis or {}
    e = html.escape
    lines = [
        f"<b>{ICON.get(a.get('sentiment'), '')}</b> · %{a.get('confidence')} güven · {e(a.get('materiality', ''))} önem",
        f"<b>{e(' '.join('#' + t for t in (item.tickers or a.get('affected_tickers') or ['PiyasaGeneli'])))}</b>"
        f" — {e(a.get('headline_tr') or item.title)}",
        "",
        e(a.get("summary", "")),
    ]
    if a.get("key_points"):
        lines += [""] + [f"• {e(p)}" for p in a["key_points"][:3]]
    if a.get("risks"):
        lines += ["", f"⚠️ {e(a['risks'][0])}"]
    lines += ["", f"<i>{e(item.source)}</i>"]
    if item.url:
        lines.append(f'<a href="{e(item.url)}">Kaynak</a>' +
                     (f' · <a href="{e(site_url)}">Panel</a>' if site_url else ""))
    return "\n".join(lines)


def send(items: list[Item], cfg: dict) -> int:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not cfg.get("telegram", True) or not token or not chat:
        return 0
    site = os.environ.get("SITE_URL")
    sent = 0
    for it in items:
        if not should_notify(it, cfg):
            continue
        r = http.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
            "chat_id": chat, "text": format_message(it, site), "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, retries=1)
        sent += r is not None
    log.info("Telegram: %d bildirim", sent)
    return sent


def send_hello(summary: dict, ai: dict | None) -> bool:
    """Telegram bağlantısını doğrulamak için ilk seferde bir kez gönderilen mesaj."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    site = os.environ.get("SITE_URL")
    text = ("✅ <b>Piyasa Radarı bağlandı</b>\n\n"
            f"Bu turda {summary.get('collected', 0)} kayıt tarandı, {summary.get('new', 0)} yeni kayıt, "
            f"{summary.get('analyzed', 0)} AI değerlendirmesi.\n"
            f"AI: {html.escape(' → '.join(ai['providers'])) + ' (' + html.escape(ai['model']) + ')' if ai and ai.get('providers') else 'kapalı (AI anahtarı yok)'}\n\n"
            "Bundan sonra yalnızca güçlü sinyaller gelecek (ayarlar: config/settings.yml → notify)."
            + (f'\n<a href="{html.escape(site)}">Paneli aç</a>' if site else ""))
    r = http.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True,
    }, retries=1)
    if r is None:
        log.warning("Telegram test mesajı gönderilemedi (token ya da chat id hatalı olabilir)")
    return r is not None
