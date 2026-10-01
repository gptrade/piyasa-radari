"""Ücretli veri sağlayıcıları (Matriks, Foreks) için bağlantı arayüzü.

Gerçek bağlantı YAZILMADI: sözleşme ve API belgesi gelince `fetch_news` / `fetch_quotes` doldurulur.
Kimlik bilgileri GitHub Secrets'ta (ya da yerelde .env'de) tanımlıysa toplayıcı "yapılandırıldı ama bağlantı
yazılmadı" uyarısı verir; tanımlı değilse sessizce kapalı kalır (panelde "kapalı" görünür).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from ..models import Item
from . import Context

log = logging.getLogger("radar.vendors")


class VendorAdapter(ABC):
    name: str = ""
    env: tuple[str, ...] = ()             # gerekli ortam değişkenleri

    def configured(self) -> bool:
        return all(os.environ.get(k) for k in self.env)

    def creds(self) -> dict[str, str]:
        return {k: os.environ.get(k, "") for k in self.env}

    @abstractmethod
    def fetch_news(self, ctx: Context) -> list[Item]:
        """Sağlayıcının haber/bildirim akışı → Item listesi (source_type: news / disclosure)."""

    @abstractmethod
    def fetch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Anlık/gecikmeli fiyatlar: {sembol: {last, change_pct, volume, ts}}."""

    def collect(self, ctx: Context) -> list[Item]:
        if not self.configured():
            return []
        try:
            return self.fetch_news(ctx)
        except NotImplementedError:
            raise RuntimeError(f"{self.name} kimlik bilgileri tanımlı ama bağlantı henüz yazılmadı "
                               f"(radar/sources/vendors.py)") from None


class MatriksAdapter(VendorAdapter):
    name = "Matriks"
    env = ("MATRIKS_API_KEY", "MATRIKS_API_SECRET")

    def fetch_news(self, ctx: Context) -> list[Item]:
        raise NotImplementedError

    def fetch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        raise NotImplementedError


class ForeksAdapter(VendorAdapter):
    name = "Foreks"
    env = ("FOREKS_USERNAME", "FOREKS_PASSWORD")

    def fetch_news(self, ctx: Context) -> list[Item]:
        raise NotImplementedError

    def fetch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        raise NotImplementedError


MATRIKS, FOREKS = MatriksAdapter(), ForeksAdapter()


def collect_matriks(ctx: Context) -> list[Item]:
    return MATRIKS.collect(ctx)


def collect_foreks(ctx: Context) -> list[Item]:
    return FOREKS.collect(ctx)
