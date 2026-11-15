import copy
import json
import math
import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as Obj

from forecast import HistoryManager, extrapolate
from simulator import SimExchange, demo_config
from trading import Trader, round_tick, session_open, validate


class StrategyTests(unittest.TestCase):
    def setUp(self):
        with open("config.example.json") as f:
            self.c = demo_config(json.load(f))
        self.e = SimExchange(self.c)
        self.t = Trader(self.e, self.c, before_cycle=self.e.advance)
        self.t.discover()
        self.t.snapshot()

    def test_tick_and_overnight(self):
        self.assertEqual(round_tick(108.70000000000002, .1, "ask"), 108.7)
        self.assertEqual(round_tick(108.79, .1, "bid"), 108.7)
        self.assertTrue(session_open([["22:00", "02:00"]], datetime(2026, 1, 1, 23)))
        self.assertFalse(session_open([["22:00", "02:00"]], datetime(2026, 1, 1, 12)))

    def test_outstanding_and_ioc_reservations(self):
        i = self.c["etfs"][0]
        self.e.positions[i] = 95
        self.e.orders[i][1] = Obj(side="bid", volume=3)
        self.t.pending.append((i, "bid", 1, time.monotonic() + 30))
        self.assertEqual(self.t.capacity(i, "bid", self.t.state()), 1)
        self.assertGreater(self.t.capacity(i, "ask", self.t.state()), 100)

    def test_arbitrage_hedges_actual_partial_fill(self):
        a, b = self.c["etfs"]
        self.e.get_instruments = lambda: self.e.meta  # Hold the market fixed for this fill test.
        for stock in self.c["weights"]:
            self.t.books.pop(stock)
        self.t.books[a].asks[0].volume = 3
        original = self.e.insert_order
        def partial(iid, **kwargs):
            if iid == a:
                kwargs["volume"] = min(2, kwargs["volume"])
            return original(iid, **kwargs)
        self.e.insert_order = partial
        self.assertTrue(self.t.arbitrage())
        self.assertEqual(self.e.positions[a], 2)
        self.assertEqual(self.e.positions[b], -2)
        self.assertTrue(all(v == 0 for v in self.t.exposures(self.e.positions).values()))

    def test_basket_uses_executable_prices_and_integer_lots(self):
        a, b = self.c["etfs"]
        self.t.books.pop(b)
        self.t.books[a].asks[0].price -= 2
        plans = self.t.opportunities()
        plan = next(legs for _, legs in plans if len(legs) == 4)
        self.assertEqual([v for _, _, _, v in plan], [10, 5, 3, 2])
        self.assertTrue(self.t.arbitrage())
        self.assertTrue(all(v == 0 for v in self.t.exposures(self.e.positions).values()))

    def test_failed_hedge_cancels_quotes_and_blocks_new_risk(self):
        a = self.c["etfs"][0]
        self.e.positions[a] = 10
        stock = next(iter(self.c["weights"]))
        self.e.positions[stock] = 1
        self.e.meta[stock].paused = True
        self.t.cycle()
        self.assertEqual(self.e.positions[a], 10)
        self.assertFalse(any(self.e.orders.values()))
        self.assertEqual(self.e.positions[stock], 1)

    def test_closed_stocks_etf_hedge(self):
        a, b = self.c["etfs"]
        for stock in self.c["weights"]:
            self.e.meta[stock].paused = True
        self.e.positions[a] = 4
        self.t.snapshot()
        self.t.closed_hedge()
        self.assertEqual(sum(self.e.positions[i] for i in (a, b)), 0)

    def test_paused_stale_and_dry_run(self):
        a = self.c["etfs"][0]
        self.e.meta[a].paused = True
        self.t.snapshot()
        self.assertNotIn(a, self.t.books)
        self.e.meta[a].paused = False
        original = self.e.get_last_price_book
        def stale(iid):
            book = original(iid)
            book.timestamp = datetime(2000, 1, 1, tzinfo=timezone.utc)
            return book
        self.e.get_last_price_book = stale
        self.t.snapshot()
        self.assertFalse(self.t.books)
        dry = Trader(self.e, self.c, dry_run=True)
        dry.run(cycles=2)
        self.assertEqual(self.e.counter, 0)

    def test_loss_stop(self):
        self.t.baseline_pnl = 1000
        with self.assertRaisesRegex(RuntimeError, "loss stop"):
            self.t.cycle()

    def test_passive_quotes_and_cleanup(self):
        self.e.get_instruments = lambda: self.e.meta
        self.t.quote()
        orders = [o for group in self.e.orders.values() for o in group.values()]
        self.assertEqual({o.side for o in orders}, {"bid", "ask"})
        self.assertTrue(all(o.volume <= self.c["quote_volume"] for o in orders))
        self.t.cancel_all()
        self.assertFalse(self.t.shadow_limits)
        self.assertFalse(any(self.e.orders.values()))

    def test_unseen_accepted_limit_still_reserves_capacity(self):
        i = self.c["etfs"][0]
        self.e.positions[i] = 95
        self.t.shadow_limits[(i, 123)] = ("bid", 5)
        self.assertEqual(self.t.capacity(i, "bid", self.t.state()), 0)

    def test_quote_bound_matches_stock_hedge_when_stocks_open(self):
        self.t.quote()
        sell_basket = sum(w * self.t.books[s].bids[0].price for s, w in self.c["weights"].items())
        buy_basket = sum(w * self.t.books[s].asks[0].price for s, w in self.c["weights"].items())
        for group in self.e.orders.values():
            for order in group.values():
                if order.side == "bid":
                    self.assertLessEqual(order.price, sell_basket - self.c["min_edge"] + 1e-8)
                else:
                    self.assertGreaterEqual(order.price, buy_basket + self.c["min_edge"] - 1e-8)

    def test_closed_quoting_disabled_with_existing_stock_inventory(self):
        self.c["allow_closed_quoting"] = True
        s = next(iter(self.c["weights"]))
        self.e.meta[s].paused = True
        self.e.positions[s] = 1
        self.t.snapshot()
        self.t.quote()
        self.assertFalse(any(self.e.orders.values()))

    def test_order_rejection_does_not_create_phantom_reservation(self):
        self.e.insert_order = lambda *a, **kw: Obj(success=False)
        i = self.c["etfs"][0]
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            self.t.send(i, "bid", self.t.books[i].asks[0].price, 1, "ioc")
        self.assertFalse(self.t.pending)

    def test_configuration(self):
        c = copy.deepcopy(self.c)
        c["weights"][next(iter(c["weights"]))] = float("nan")
        with self.assertRaises(ValueError):
            validate(c)

    def test_forecast_bounded_and_does_not_leak_validation(self):
        self.assertAlmostEqual(extrapolate(list(range(64))), 64, places=6)
        h = HistoryManager(window=64)
        for n in range(200):
            h.add("A", "bid", 100 + math.sin(n / 8), 5, time.time() - 200 + n)
        h.calculate()
        self.assertEqual(len(h.history[("A", "bid")]), 64)
        self.assertTrue(math.isfinite(h.get("A")["bid"].price))
        self.assertNotIn("ask", h.get("A"))

    def test_integration_limits_and_cleanup(self):
        self.t.run(cycles=50)
        self.assertGreater(len(self.e.fills), 0)
        self.assertFalse(any(self.e.orders.values()))
        for i, p in self.e.positions.items():
            self.assertLessEqual(abs(p), self.c["instruments"][i]["position_limit"])

    def test_recorded_metrics_match_execution(self):
        self.t.record = True
        self.t.run(cycles=10)
        self.assertEqual(len(self.t.samples), 11)
        self.assertEqual(self.t.samples[-1]["cycle"], 10)
        self.assertAlmostEqual(self.t.samples[-1]["pnl"], self.e.get_pnl())
        self.assertEqual(self.t.samples[-1]["positions"], self.e.get_positions())
        self.assertEqual(len(self.e.fill_events), len(self.e.fills))
        self.assertAlmostEqual(sum(p * q for _, _, p, q in self.e.fills),
                               sum(f["price"] * f["volume"] for f in self.e.fill_events))


if __name__ == "__main__":
    unittest.main()
