"""Signal generation and inventory-aware quotes; no live orders."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from .pricing import Quote, basket_prices


@dataclass(frozen=True)
class Signal:
    name: str
    edge_per_unit: float
    legs: Mapping[str, int]


@dataclass(frozen=True)
class StrategySettings:
    min_edge: float = 0.15
    tick_size: float = 0.1
    half_spread: float = 0.2
    inventory_penalty: float = 0.002

    def __post_init__(self) -> None:
        if self.min_edge < 0 or self.tick_size <= 0 or self.half_spread <= 0:
            raise ValueError("Invalid strategy settings")
        if self.inventory_penalty < 0:
            raise ValueError("Inventory penalty cannot be negative")


def cross_listing_signal(us: Quote, eu: Quote,
                         settings: StrategySettings = StrategySettings(),
                         units: int = 1) -> Signal | None:
    """Compare actually executable prices; assumes equal contract units and currency."""
    if units <= 0:
        raise ValueError("units must be positive")
    buy_us_edge = eu.bid - us.ask
    buy_eu_edge = us.bid - eu.ask
    if max(buy_us_edge, buy_eu_edge) <= settings.min_edge:
        return None
    if buy_us_edge >= buy_eu_edge:
        return Signal("BUY_US_SELL_EU", buy_us_edge,
                      {"SEMIS_ETF_US": units, "SEMIS_ETF_EU": -units})
    return Signal("BUY_EU_SELL_US", buy_eu_edge,
                  {"SEMIS_ETF_EU": units, "SEMIS_ETF_US": -units})


def etf_basket_signal(etf: Quote, constituent_books: Mapping[str, Quote],
                      weights: Mapping[str, float],
                      settings: StrategySettings = StrategySettings()) -> Signal | None:
    """Indicative per-unit basket signal; weights can be fractional.

    No executable multi-leg order is returned because real shares, creation-unit
    sizes, FX and lot sizes are unknown from the retained challenge notes.
    """
    basket_bid, _, basket_ask = basket_prices(weights, constituent_books)
    cheap_etf = basket_bid - etf.ask
    rich_etf = etf.bid - basket_ask
    if max(cheap_etf, rich_etf) <= settings.min_edge:
        return None
    if cheap_etf >= rich_etf:
        return Signal("BUY_ETF_SELL_BASKET_INDICATIVE", cheap_etf, {})
    return Signal("SELL_ETF_BUY_BASKET_INDICATIVE", rich_etf, {})


def inventory_quotes(fair_value: float, position: int,
                     settings: StrategySettings = StrategySettings()) -> tuple[float, float]:
    """Quote around an inventory-skewed reservation price."""
    if fair_value <= 0:
        raise ValueError("fair_value must be positive")
    center = fair_value - settings.inventory_penalty * position
    tick = settings.tick_size
    bid_ticks = math.floor((center - settings.half_spread) / tick + 1e-9)
    ask_ticks = math.ceil((center + settings.half_spread) / tick - 1e-9)
    bid, ask = round(bid_ticks * tick, 8), round(ask_ticks * tick, 8)
    if bid <= 0 or bid >= ask:
        raise ValueError("Quote outside valid range")
    return bid, ask
