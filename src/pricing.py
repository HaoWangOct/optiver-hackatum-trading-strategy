"""Executable basket valuations using bid and ask, not just midpoint."""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_volume: int
    ask_volume: int

    def __post_init__(self) -> None:
        if self.bid <= 0 or self.ask < self.bid:
            raise ValueError("Quote must have 0 < bid <= ask")
        if self.bid_volume <= 0 or self.ask_volume <= 0:
            raise ValueError("Book must have positive top-of-book liquidity")

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def _validate_weights(weights: Mapping[str, float], books: Mapping[str, Quote]) -> None:
    if not weights or any(w <= 0 for w in weights.values()):
        raise ValueError("Basket weights must be strictly positive")
    if abs(sum(weights.values()) - 1.0) > 1e-8:
        raise ValueError("Illustrative basket weights must sum to 1")
    if set(weights) - set(books):
        raise KeyError("Missing constituent quotes")


def basket_prices(weights: Mapping[str, float],
                  books: Mapping[str, Quote]) -> tuple[float, float, float]:
    """Return (liquidation bid, midpoint, acquisition ask) per normalized basket.

    Assumes all components use the same currency and share/ETF price scale.
    Real contracts may require conversion factors and FX adjustments.
    """
    _validate_weights(weights, books)
    bid = sum(w * books[s].bid for s, w in weights.items())
    mid = sum(w * books[s].mid for s, w in weights.items())
    ask = sum(w * books[s].ask for s, w in weights.items())
    return bid, mid, ask
