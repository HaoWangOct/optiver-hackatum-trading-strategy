"""RTG protocol tests use the genuine downloaded SDK; optional in offline-only CI."""
import asyncio
import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

RUNTIME = Path(__file__).resolve().parents[1] / "external/ready-trader-go/pyready_trader_go_pyside6"


@unittest.skipUnless((RUNTIME / "ready_trader_go").is_dir(), "Run python3 run_ready_trader_go.py --setup first")
class ReadyTraderTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(RUNTIME))
        self.module = importlib.import_module("rtg_autotrader")
        self.loop = asyncio.new_event_loop()
        config = (RUNTIME / "exchange.json").read_text()
        with patch("builtins.open", mock_open(read_data=config)):
            self.bot = self.module.AutoTrader(self.loop, "Test", "local-simulation")
        self.bot.send_hedge_order = Mock()
        self.bot.send_cancel_order = Mock()
        self.bot.send_insert_order = Mock()
        self.future = self.module.Instrument.FUTURE
        self.etf = self.module.Instrument.ETF
        self.buy, self.sell = self.module.Side.BUY, self.module.Side.SELL
        self.bot.books[self.future] = ([10100] * 5, [100] * 5, [9900] * 5, [100] * 5)
        self.bot.books[self.etf] = ([10300] * 5, [100] * 5, [9700] * 5, [100] * 5)

    def tearDown(self):
        self.bot.forecasts.close()
        self.loop.close()

    def tick(self):
        self.bot.last_quote = -100
        self.bot.on_order_book_update_message(self.future, 1, *self.bot.books[self.future])

    def test_partial_hedge_waits_for_fill_and_then_retries_residual(self):
        self.bot.orders[123] = {"side": self.buy, "remaining": 5, "price": 9900, "cancelling": False}
        self.bot.on_order_filled_message(123, 9900, 5)
        hedge_id, side, _, quantity = self.bot.send_hedge_order.call_args.args
        self.assertEqual((side, quantity), (self.sell, 5))
        self.assertEqual(self.bot.future_position, 0)
        self.bot._hedge()
        self.assertEqual(self.bot.send_hedge_order.call_count, 1)
        self.bot.on_hedge_filled_message(hedge_id, 9900, 2)
        self.assertEqual(self.bot.future_position, -2)
        self.bot._hedge()
        self.assertEqual(self.bot.send_hedge_order.call_args.args[-1], 3)

    def test_cancelled_quote_remains_reserved_until_status_ack(self):
        self.bot.orders[123] = {"side": self.buy, "remaining": 5, "price": 9500, "cancelling": False}
        self.tick()
        self.bot.send_cancel_order.assert_called_once_with(123)
        self.assertFalse(any(c.args[1] == self.buy for c in self.bot.send_insert_order.call_args_list))
        self.bot.on_order_status_message(123, 0, 0, 0)
        self.tick()
        self.assertTrue(any(c.args[1] == self.buy for c in self.bot.send_insert_order.call_args_list))

    def test_two_leg_position_limit_and_rejection_halt(self):
        self.bot.etf_position, self.bot.future_position = 100, -100
        self.tick()
        calls = self.bot.send_insert_order.call_args_list
        self.assertTrue(calls)
        self.assertTrue(all(c.args[1] == self.sell for c in calls))
        self.bot.on_error_message(0, b"test rejection")
        count = len(calls)
        self.tick()
        self.assertEqual(self.bot.send_insert_order.call_count, count)

    def test_budget_leaves_headroom(self):
        self.assertEqual(sum(self.bot._budget() for _ in range(100)), 35)


if __name__ == "__main__":
    unittest.main()
