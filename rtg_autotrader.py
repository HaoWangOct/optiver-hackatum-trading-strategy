# SPDX-License-Identifier: AGPL-3.0-or-later
# Independent Ready Trader Go integration, added 2026-11-15.
"""ETF/future quoting and fill-confirmed hedging for the downloadable RTG engine."""
import itertools
import json
import math
import time
from collections import deque

from ready_trader_go import BaseAutoTrader, Instrument, Lifespan, Side
from forecast import HistoryManager


class AutoTrader(BaseAutoTrader):
    def __init__(self, loop, team_name, secret):
        super().__init__(loop, team_name, secret)
        with open("exchange.json") as f:
            config = json.load(f)
        self.limit = config["Limits"]["PositionLimit"]
        self.tick = round(config["Instrument"]["TickSize"] * 100)
        self.speed = config["Engine"]["Speed"]
        self.rate = config["Limits"]["MessageFrequencyLimit"]
        self.ids = itertools.count(1)
        self.orders, self.hedges, self.books = {}, {}, {}
        self.etf_position = self.future_position = 0
        self.sent = deque()
        self.last_quote = 0.0
        self.halted = False
        self.forecasts = HistoryManager(interval=0.5)
        self.forecasts.start()

    def connection_lost(self, exc):
        self.forecasts.close()
        super().connection_lost(exc)

    def _budget(self, reserve=0):
        now = time.monotonic()
        # The template's limiter uses simulation time with a speed-scaled window.
        # This full wall-clock second is stricter, with headroom for hedge/cancel.
        while self.sent and self.sent[0] <= now - 1:
            self.sent.popleft()
        if len(self.sent) >= min(35, self.rate - 5) - reserve:
            return False
        self.sent.append(now)
        return True

    def _cancel_all(self):
        for oid, order in self.orders.items():
            if not order["cancelling"] and self._budget():
                order["cancelling"] = True
                self.send_cancel_order(oid)

    def _hedge(self):
        if self.hedges or Instrument.FUTURE not in self.books:
            return
        delta = self.etf_position + self.future_position
        if not delta:
            return
        side = Side.SELL if delta > 0 else Side.BUY
        sign = 1 if side == Side.BUY else -1
        capacity = self.limit - sign * self.future_position
        qty = min(abs(delta), capacity, 10)
        if qty <= 0 or not self._budget():
            return
        asks, ask_vol, bids, bid_vol = self.books[Instrument.FUTURE]
        price = bids[0] - 2 * self.tick if side == Side.SELL else asks[0] + 2 * self.tick
        if price <= 0:
            return
        oid = next(self.ids)
        self.hedges[oid] = (sign, qty)
        self.send_hedge_order(oid, side, price, qty)

    def on_hedge_filled_message(self, client_order_id, price, volume):
        pending = self.hedges.pop(client_order_id, None)
        if pending:
            self.future_position += pending[0] * volume
        # Retry a partially filled hedge on the next book update, not recursively.

    def on_order_filled_message(self, client_order_id, price, volume):
        order = self.orders.get(client_order_id)
        if order:
            self.etf_position += (1 if order["side"] == Side.BUY else -1) * volume
            order["remaining"] = max(0, order["remaining"] - volume)
            self._hedge()

    def on_order_status_message(self, client_order_id, fill_volume, remaining_volume, fees):
        if client_order_id in self.orders:
            if remaining_volume:
                self.orders[client_order_id]["remaining"] = remaining_volume
            else:
                del self.orders[client_order_id]

    def on_error_message(self, client_order_id, error_message):
        self.logger.error("RTG rejected order %d: %s", client_order_id, error_message.decode())
        self.halted = True
        self._cancel_all()
        # Keep conservative reservations: an error is not a cancellation ack.

    def on_order_book_update_message(self, instrument, sequence_number,
                                     ask_prices, ask_volumes, bid_prices, bid_volumes):
        if not ask_prices[0] or not bid_prices[0]:
            self._cancel_all()
            return
        self.books[instrument] = (list(ask_prices), list(ask_volumes), list(bid_prices), list(bid_volumes))
        if instrument != Instrument.FUTURE:
            return
        self._hedge()
        if self.halted or self.hedges or self.etf_position + self.future_position:
            self._cancel_all()
            return
        if Instrument.ETF not in self.books:
            return
        now = time.monotonic()
        if now - self.last_quote < max(0.15, 1 / self.speed):
            return
        self.last_quote = now
        future_asks, _, future_bids, _ = self.books[Instrument.FUTURE]
        etf_asks, _, etf_bids, _ = self.books[Instrument.ETF]
        mid = (future_asks[0] + future_bids[0]) / 2
        fair = mid - self.etf_position / self.limit * 2 * self.tick
        predictions = self.forecasts.get("FUTURE")
        usable = [p for p in predictions.values() if p.error <= self.tick / 100]
        if usable:
            forecast = sum(p.price for p in usable) / len(usable) * 100
            fair += .2 * max(-self.tick / 2, min(self.tick / 2, forecast - mid))
        bid = math.floor(min(fair - self.tick, future_bids[0], etf_asks[0] - self.tick) / self.tick) * self.tick
        ask = math.ceil(max(fair + self.tick, future_asks[0], etf_bids[0] + self.tick) / self.tick) * self.tick
        targets = {Side.BUY: bid, Side.SELL: ask}
        # Wait for cancellation acknowledgements; all remaining quantities stay reserved.
        for oid, order in self.orders.items():
            if order["price"] != targets[order["side"]] and not order["cancelling"] and self._budget():
                order["cancelling"] = True
                self.send_cancel_order(oid)
        for side, price in targets.items():
            if price <= 0 or any(o["side"] == side for o in self.orders.values()):
                continue
            sign = 1 if side == Side.BUY else -1
            etf_capacity = self.limit - sign * self.etf_position
            future_capacity = self.limit + sign * self.future_position
            qty = min(5, etf_capacity, future_capacity)
            if qty > 0 and self._budget(reserve=5):
                oid = next(self.ids)
                self.orders[oid] = {"side": side, "price": price, "remaining": qty, "cancelling": False}
                self.send_insert_order(oid, side, price, qty, Lifespan.GOOD_FOR_DAY)

    def on_trade_ticks_message(self, instrument, sequence_number,
                               ask_prices, ask_volumes, bid_prices, bid_volumes):
        if instrument != Instrument.FUTURE:
            return
        stamp = time.time()
        for side, prices, volumes in (("bid", ask_prices, ask_volumes), ("ask", bid_prices, bid_volumes)):
            qty = sum(volumes)
            if qty:
                price = sum(p * v for p, v in zip(prices, volumes)) / qty / 100
                self.forecasts.add("FUTURE", side, price, qty, stamp)
