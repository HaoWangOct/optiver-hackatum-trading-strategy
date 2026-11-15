import contextlib
import io
import unittest
from unittest.mock import patch

import bot
import example1
from helper import load_demo


class EntryPointSafetyTests(unittest.TestCase):
    def test_demo_route_rejects_live_flag_before_connecting(self):
        with patch("helper.connect_optibook") as connect:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    bot.main(["--engine", "demo", "--live"])
            self.assertNotEqual(raised.exception.code, 0)
            connect.assert_not_called()

    def test_discovery_example_never_mutates_orders(self):
        exchange, config = load_demo()
        with patch.object(exchange, "insert_order", side_effect=AssertionError("Discovery sent an order")):
            with patch.object(exchange, "delete_orders", side_effect=AssertionError("Discovery cancelled orders")):
                with patch("example1.load_demo", return_value=(exchange, config)):
                    with contextlib.redirect_stdout(io.StringIO()):
                        example1.main([])
        self.assertEqual(exchange.counter, 0)
        self.assertFalse(exchange.fills)
        self.assertFalse(exchange.positions)


if __name__ == "__main__":
    unittest.main()
