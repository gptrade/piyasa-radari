"""Kaynak toplayıcıları. Her biri `collect(ctx) -> list[Item]` sunar."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..config import Stock, TickerMatcher


@dataclass
class Context:
    settings: dict
    stocks: list[Stock]
    matcher: TickerMatcher
    since: datetime

    def cfg(self, name: str) -> dict:
        return (self.settings.get("sources") or {}).get(name) or {}

    def market(self, market: str) -> list[Stock]:
        return [s for s in self.stocks if s.market == market]
