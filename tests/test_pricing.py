import unittest
from src.pricing import Quote, basket_prices
from src.strategy import cross_listing_signal, etf_basket_signal, inventory_quotes, StrategySettings


class PricingTests(unittest.TestCase):
    def test_basket_bid_and_ask(self):
        books = {"A": Quote(90, 92, 10, 10), "B": Quote(100, 104, 10, 10)}
        bid, mid, ask = basket_prices({"A": 0.5, "B": 0.5}, books)
        self.assertAlmostEqual(bid, 95)
        self.assertAlmostEqual(mid, 96.5)
        self.assertAlmostEqual(ask, 98)

    def test_invalid_quote(self):
        with self.assertRaises(ValueError):
            Quote(101, 100, 10, 10)

    def test_cross_listing_direction(self):
        us = Quote(100, 100.2, 10, 10)
        eu = Quote(100.7, 100.9, 10, 10)
        signal = cross_listing_signal(us, eu)
        self.assertEqual(signal.name, "BUY_US_SELL_EU")
        self.assertAlmostEqual(signal.edge_per_unit, 0.5)
        self.assertEqual(signal.legs["SEMIS_ETF_US"], 1)

    def test_no_cross_listing_edge(self):
        self.assertIsNone(cross_listing_signal(
            Quote(100, 101, 10, 10), Quote(100.5, 101.5, 10, 10)
        ))

    def test_basket_signal_is_indicative_not_executable(self):
        books = {"A": Quote(100, 100.2, 10, 10)}
        signal = etf_basket_signal(Quote(99, 99.2, 10, 10), books, {"A": 1.0})
        self.assertEqual(signal.name, "BUY_ETF_SELL_BASKET_INDICATIVE")
        self.assertEqual(dict(signal.legs), {})

    def test_inventory_skews_quotes_lower(self):
        neutral = inventory_quotes(100, 0)
        long = inventory_quotes(100, 25)
        self.assertLess(long[0], neutral[0])
        # A 0.05 reservation shift is smaller than the 0.10 price tick, so
        # outward rounding can keep the ask unchanged; it must not increase.
        self.assertLessEqual(long[1], neutral[1])
        full_tick_shift = inventory_quotes(100, 50)
        self.assertLess(full_tick_shift[0], neutral[0])
        self.assertLess(full_tick_shift[1], neutral[1])

    def test_invalid_weights(self):
        with self.assertRaises(ValueError):
            basket_prices({"A": 0.8}, {"A": Quote(100, 101, 10, 10)})


if __name__ == "__main__":
    unittest.main()
