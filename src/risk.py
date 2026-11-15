"""Simple portfolio limits for simulated multi-instrument execution."""
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RiskLimits:
    max_abs_position: int = 100
    max_gross_notional: float = 50_000.0

    def __post_init__(self) -> None:
        if self.max_abs_position <= 0 or self.max_gross_notional <= 0:
            raise ValueError("Risk limits must be positive")


def check_trade(positions: Mapping[str, int],
                symbol: str,
                signed_quantity: int,
                marks: Mapping[str, float],
                limits: RiskLimits) -> bool:
    """Test projected *whole* portfolio, without executing anything."""
    if signed_quantity == 0 or symbol not in marks:
        return False
    projected = dict(positions)
    projected[symbol] = projected.get(symbol, 0) + signed_quantity
    if any(abs(q) > limits.max_abs_position for q in projected.values()):
        return False
    if any(s not in marks or marks[s] <= 0 for s in projected):
        return False
    gross = sum(abs(q) * marks[s] for s, q in projected.items())
    return gross <= limits.max_gross_notional


def check_package(positions: Mapping[str, int],
                  legs: Mapping[str, int],
                  marks: Mapping[str, float],
                  limits: RiskLimits) -> bool:
    """Check all proposed legs together; no single-leg permission implies hedgeability."""
    projected = dict(positions)
    if not legs or all(q == 0 for q in legs.values()):
        return False
    for symbol, signed_quantity in legs.items():
        if symbol not in marks:
            return False
        projected[symbol] = projected.get(symbol, 0) + signed_quantity
    if any(abs(q) > limits.max_abs_position for q in projected.values()):
        return False
    if any(s not in marks or marks[s] <= 0 for s in projected):
        return False
    return sum(abs(q) * marks[s] for s, q in projected.items()) <= limits.max_gross_notional
