"""Инструменты, по которым работает один бот.

Каждый инструмент — свой символ, таймфрейм, стратегия, спред и состояние сделки.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Instrument:
    key: str                  # короткое имя для команд: gold / eurusd / gbpusd
    symbol: str               # тикер Yahoo
    name: str                 # как показывать в сообщениях
    timeframe: str = "1h"     # "1h" | "4h"
    strategy: str = "breakout"
    strategies: list[str] = field(default_factory=list)  # параллельный режим
    params: dict = field(default_factory=dict)   # параметры стратегии (например channel)
    spread: float = 0.30      # издержки в единицах цены
    max_bars: int = 48        # максимум часов/баров в сделке
    pip: float = 1.0          # для отображения цены: 1.0 — 2 знака, 0.0001 — 5 знаков

    @property
    def digits(self) -> int:
        return 5 if self.pip < 0.01 else 2

    @property
    def slots(self) -> list[str]:
        """Список стратегий, которые работают по инструменту параллельно."""
        return self.strategies or [self.strategy]

    def to_dict(self) -> dict:
        data = {
            "key": self.key,
            "symbol": self.symbol,
            "name": self.name,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "params": dict(self.params),
            "spread": self.spread,
            "max_bars": self.max_bars,
            "pip": self.pip,
        }
        if self.strategies:
            data["strategies"] = list(self.strategies)
        return data


DEFAULTS = [
    Instrument(
        key="gold", symbol="GC=F", name="XAUUSD", timeframe="1h",
        strategy="breakout", spread=0.30, max_bars=48, pip=1.0,
    ),
    Instrument(
        key="eurusd", symbol="EURUSD=X", name="EURUSD", timeframe="4h",
        strategy="channel", params={"channel": 48}, spread=0.00012, max_bars=30, pip=0.0001,
    ),
    Instrument(
        key="gbpusd", symbol="GBPUSD=X", name="GBPUSD", timeframe="4h",
        strategy="channel", params={"channel": 24}, spread=0.00015, max_bars=30, pip=0.0001,
    ),
]


def from_config(raw: list[dict] | None) -> list[Instrument]:
    if not raw:
        return list(DEFAULTS)
    out: list[Instrument] = []
    for item in raw:
        try:
            strategies = [str(s) for s in (item.get("strategies") or []) if s]
            out.append(
                Instrument(
                    key=str(item["key"]),
                    symbol=str(item["symbol"]),
                    name=str(item.get("name", item["key"]).upper()),
                    timeframe=str(item.get("timeframe", "1h")),
                    strategy=str(item.get("strategy", (strategies or ["breakout"])[0])),
                    strategies=strategies,
                    params=dict(item.get("params") or {}),
                    spread=float(item.get("spread", 0.30)),
                    max_bars=int(item.get("max_bars", 48)),
                    pip=float(item.get("pip", 1.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out or list(DEFAULTS)


def find(instruments: list[Instrument], key: str | None) -> Instrument | None:
    if not key:
        return None
    low = key.lower().lstrip("@")
    for inst in instruments:
        if inst.key == low or inst.name.lower() == low or inst.symbol.lower() == low:
            return inst
    return None
