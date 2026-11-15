import unittest
from src.pricing import Quote
from src.risk import RiskLimits, check_trade, check_package
from src.simulator import ToyBroker


class RiskSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.books = {"A": Quote(99, 101, 5, 5), "B": Quote(99, 101, 5, 5)}
        self.marks = {"A": 100, "B": 100}

    def test_limit_prevents_overfill(self):
        limits = RiskLimits(max_abs_position=3, max_gross_notional=500)
        self.assertFalse(check_trade({"A": 3}, "A", 1, self.marks, limits))
        self.assertTrue(check_trade({"A": 3}, "A", -1, self.marks, limits))

    def test_package_checks_total_exposure(self):
        limits = RiskLimits(max_abs_position=10, max_gross_notional=150)
        self.assertFalse(check_package({}, {"A": 1, "B": -1}, self.marks, limits))

    def test_buy_and_sell_accounting(self):
        broker = ToyBroker(fee_per_unit=0.1)
        self.assertTrue(broker.execute("A", 2, self.books))
        self.assertEqual(broker.positions["A"], 2)
        self.assertAlmostEqual(broker.equity(self.books), -2.2)
        self.assertTrue(broker.execute("A", -2, self.books))
        self.assertEqual(broker.positions["A"], 0)
        self.assertAlmostEqual(broker.equity(self.books), -4.4)

    def test_reject_more_than_displayed_depth(self):
        broker = ToyBroker()
        self.assertFalse(broker.execute("A", 6, self.books))
        self.assertEqual(broker.trade_count, 0)

    def test_short_liquidation_uses_ask(self):
        broker = ToyBroker()
        self.assertTrue(broker.execute("A", -1, self.books))
        self.assertAlmostEqual(broker.liquidation_equity(self.books), -2.01)


if __name__ == "__main__":
    unittest.main()
