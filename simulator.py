"""Deterministic execution harness, not evidence of real-market profitability."""
import copy
import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace as Obj


def demo_config(config):
    c = copy.deepcopy(config)
    names = dict(zip(c["etfs"] + list(c["weights"]),
                     ["SEMIS_ETF_US", "SEMIS_ETF_EU", "CHIP_A", "CHIP_B", "CHIP_C"]))
    c["etfs"] = [names[i] for i in c["etfs"]]
    c["weights"] = {names[i]: w for i, w in c["weights"].items()}
    c["instruments"] = {names[i]: s for i, s in c["instruments"].items()}
    c.update(requests_per_second=100000, cycle_seconds=0.002,
             quote_refresh_seconds=0.01, settlement_seconds=0.001,
             ioc_reservation_seconds=0.02, verified=True)
    return c


class SimExchange:
    def __init__(self, config):
        self.c = config
        self.positions = defaultdict(int)
        self.orders = {i: {} for i in config["instruments"]}
        self.meta = {i: Obj(paused=False, tick_size=s["tick_size"])
                     for i, s in config["instruments"].items()}
        self.counter, self.cycle, self.cash = 0, 0, 0.0
        self.books, self.ticks = {}, {}
        self.fills = []
        self.fill_events = []
        self._update()

    def _update(self):
        now = datetime.now(timezone.utc)
        mids = {i: 100 + n * 10 + 0.2 * math.sin(self.cycle / 8)
                for n, i in enumerate(self.c["weights"])}
        nav = self.c["cash_component"] + sum(w * mids[i] for i, w in self.c["weights"].items())
        a, b = self.c["etfs"]
        mids[a], mids[b] = nav, nav + (1.0 if self.cycle % 10 < 4 else 0)
        for iid, mid in mids.items():
            tick = self.c["instruments"][iid]["tick_size"]
            mid = round(mid / tick) * tick
            self.books[iid] = Obj(timestamp=now,
                                  bids=[Obj(price=round(mid - tick, 6), volume=50)],
                                  asks=[Obj(price=round(mid + tick, 6), volume=50)])
            self.ticks[iid] = [Obj(timestamp=now, price=round(mid + tick, 6),
                                   volume=5, aggressor_side="bid"),
                               Obj(timestamp=now, price=round(mid - tick, 6),
                                   volume=5, aggressor_side="ask")]
        # Synthetic takers sometimes hit passive quotes, including partial fills.
        if self.cycle % 3 == 0:
            for iid, orders in self.orders.items():
                for oid, order in list(orders.items()):
                    fair = mids[iid]
                    if ((order.side == "bid" and order.price >= fair - 0.5)
                            or (order.side == "ask" and order.price <= fair + 0.5)):
                        qty = min(1, order.volume)
                        self._fill(iid, order.side, order.price, qty)
                        order.volume -= qty
                        if not order.volume:
                            del orders[oid]

    def _fill(self, iid, side, price, volume):
        sign = 1 if side == "bid" else -1
        self.positions[iid] += sign * volume
        self.cash -= sign * price * volume + self.c["fee_per_lot"] * volume
        self.fills.append((iid, side, price, volume))
        self.fill_events.append({"cycle": self.cycle, "instrument": iid, "side": side,
                                 "price": price, "volume": volume})
        assert abs(self.positions[iid]) <= self.c["instruments"][iid]["position_limit"]

    def get_instruments(self):
        return self.meta

    def advance(self):
        self.cycle += 1
        self._update()

    def get_last_price_book(self, iid):
        return self.books[iid]

    def get_positions(self):
        return dict(self.positions)

    def get_outstanding_orders(self, iid):
        return self.orders[iid]

    def delete_orders(self, iid):
        self.orders[iid].clear()

    def insert_order(self, iid, price, volume, side, order_type):
        assert not self.meta[iid].paused
        assert volume > 0 and int(volume) == volume
        assert abs(price / self.meta[iid].tick_size - round(price / self.meta[iid].tick_size)) < 1e-7
        self.counter += 1
        book = self.books[iid]
        level = book.asks[0] if side == "bid" else book.bids[0]
        crosses = price >= level.price if side == "bid" else price <= level.price
        filled = min(volume, level.volume) if crosses else 0
        if filled:
            self._fill(iid, side, level.price, filled)
            level.volume -= filled
        if order_type == "limit" and filled < volume:
            self.orders[iid][self.counter] = Obj(side=side, price=price, volume=volume - filled)
        return Obj(success=True, order_id=self.counter)

    def get_pnl(self):
        return self.cash + sum(p * (self.books[i].bids[0].price + self.books[i].asks[0].price) / 2
                               for i, p in self.positions.items())

    def get_trade_tick_history(self, iid):
        return []

    def poll_new_trade_ticks(self, iid):
        return self.ticks[iid]
