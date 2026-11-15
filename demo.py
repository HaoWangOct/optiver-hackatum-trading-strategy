"""Reproducible, synthetic educational demo (NOT HackaTUM market data)."""
from src.pricing import Quote, basket_prices
from src.strategy import StrategySettings, cross_listing_signal, etf_basket_signal, inventory_quotes
from src.simulator import ToyBroker
from src.forecast import fourier_extrapolate


def main() -> None:
    # Illustrative symbols, prices and weights, NOT official challenge contract specs.
    weights = {"STOCK_A": 0.40, "STOCK_B": 0.35, "STOCK_C": 0.25}
    books = {
        "STOCK_A": Quote(99.8, 100.2, 200, 200),
        "STOCK_B": Quote(109.8, 110.2, 200, 200),
        "STOCK_C": Quote(89.8, 90.2, 200, 200),
        "SEMIS_ETF_US": Quote(100.2, 100.4, 100, 100),
        "SEMIS_ETF_EU": Quote(100.8, 101.0, 100, 100),
    }
    settings = StrategySettings(min_edge=0.15)
    bid, mid, ask = basket_prices(weights, books)
    print(f"Synthetic basket: executable bid={bid:.2f}, mid={mid:.2f}, ask={ask:.2f}")
    print("ETF vs basket:", etf_basket_signal(books["SEMIS_ETF_US"], books, weights, settings))
    signal = cross_listing_signal(books["SEMIS_ETF_US"], books["SEMIS_ETF_EU"], settings)
    print("Cross-listed ETF:", signal)
    print("Inventory-adjusted quotes:", inventory_quotes(mid, position=15, settings=settings))
    broker = ToyBroker(fee_per_unit=0.02)
    if signal is not None:
        # Two legs evaluated individually: demo only, NOT atomic execution.
        for symbol, qty in signal.legs.items():
            ok = broker.execute(symbol, qty, books)
            print(f"Toy execution {symbol}: {qty:+d} -> {'filled' if ok else 'rejected'}")
    print("Positions:", broker.positions)
    print(f"Cash={broker.cash:.2f}; mid-marked equity={broker.equity(books):.2f}; "
          f"liquidation equity={broker.liquidation_equity(books):.2f}")
    prices = [100.0 + 0.3 * ((i % 8) - 4) for i in range(32)]
    print(f"Exploratory Fourier forecast={fourier_extrapolate(prices):.4f}")


if __name__ == "__main__":
    main()
