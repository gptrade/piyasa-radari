"""Ayarları ve izleme listesini yükler, metinden hisse eşleştirir."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "site" / "data"
INBOX = ROOT / "inbox"


@dataclass
class Stock:
    symbol: str
    name: str
    market: str            # BIST | US
    aliases: list[str]

    @property
    def yahoo(self) -> str:
        return f"{self.symbol}.IS" if self.market == "BIST" else self.symbol


def load_settings() -> dict:
    return yaml.safe_load((CONFIG / "settings.yml").read_text(encoding="utf-8"))


def load_watchlist() -> list[Stock]:
    raw = yaml.safe_load((CONFIG / "watchlist.yml").read_text(encoding="utf-8")) or {}
    out: list[Stock] = []
    for key, market in (("bist", "BIST"), ("us", "US")):
        for s in raw.get(key) or []:
            out.append(Stock(
                symbol=str(s["symbol"]).upper(),
                name=s.get("name", s["symbol"]),
                market=market,
                aliases=list(s.get("aliases") or []),
            ))
    return out


class TickerMatcher:
    """Serbest metinde izleme listesindeki hisseleri bulur.

    Sembol eşleşmesi büyük harf ve kelime sınırı ister ("AMD" evet, "amd" hayır),
    $NVDA gibi cashtag'leri de yakalar. Takma adlar büyük/küçük harf duyarsızdır.
    """

    def __init__(self, stocks: list[Stock]):
        self.stocks = stocks
        self._patterns: list[tuple[Stock, re.Pattern, re.Pattern | None]] = []
        for st in stocks:
            sym = re.compile(rf"(?<![A-Za-z0-9])\$?{re.escape(st.symbol)}(?![A-Za-z0-9])")
            alias = None
            if st.aliases:
                alt = "|".join(re.escape(a) for a in sorted(st.aliases, key=len, reverse=True))
                alias = re.compile(rf"(?<![\wçğıöşü])(?:{alt})(?![\wçğıöşü])", re.IGNORECASE)
            self._patterns.append((st, sym, alias))

    def match(self, text: str, market: str | None = None) -> list[str]:
        found: list[str] = []
        for st, sym, alias in self._patterns:
            if market and st.market != market:
                continue
            if sym.search(text) or (alias and alias.search(text)):
                found.append(st.symbol)
        return found

    def by_symbol(self, symbol: str) -> Stock | None:
        return next((s for s in self.stocks if s.symbol == symbol.upper()), None)
