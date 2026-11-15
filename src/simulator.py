"""Minimal deterministic fill accounting. Not a realistic exchange matching engine."""
from dataclasses import dataclass, field
from typing import Mapping

from .pricing import Quote
from .risk import RiskLimits, check_trade


@dataclass
class ToyBroker:
    cash: float = 0.0
    fee_per_unit: float = 0.01
    limits: RiskLimits = field(default_factory=RiskLimits)
    positions: dict[str, int] = field(default_factory=dict)
    trade_count: int = 0
    paid_fees: float = 0.0

    def __post_init__(self) -> None:
        if self.fee_per_unit < 0:
            raise ValueError("fees cannot be negative")

    def execute(self, symbol: str, signed_quantity: int,
                books: Mapping[str, Quote]) -> bool:
        """Fill immediately at *top of book* for a sufficiently small order.

        Positive signed_quantity buys at ask; negative sells at bid. Orders
        violating top-level displayed volume, risk or symbol availability fail.
        Partial fills, leg atomicity and order queues are not implemented.
        """
        if symbol not in books or signed_quantity == 0:
            return False
        book = books[symbol]
        if signed_quantity > book.ask_volume or -signed_quantity > book.bid_volume:
            return False
        marks = {s: q.mid for s, q in books.items()}
        if not check_trade(self.positions, symbol, signed_quantity, marks, self.limits):
            return False
        px = book.ask if signed_quantity > 0 else book.bid
        fee = self.fee_per_unit * abs(signed_quantity)
        self.cash -= signed_quantity * px + fee
        self.paid_fees += fee
        self.positions[symbol] = self.positions.get(symbol, 0) + signed_quantity
        self.trade_count += 1
        return True

    def equity(self, books: Mapping[str, Quote]) -> float:
        """Mid-marked equity; ignores future market impact and liquidation fees."""
        return self.cash + sum(qty * books[s].mid
                               for s, qty in self.positions.items())

    def liquidation_equity(self, books: Mapping[str, Quote]) -> float:
        """Conservative executable bid/ask mark before incremental fees."""
        return self.cash + sum(
            qty * (books[s].bid if qty > 0 else books[s].ask)
            for s, qty in self.positions.items()
        )
