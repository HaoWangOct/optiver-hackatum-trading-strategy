"""Optibook challenge trader: python trading.py --demo --cycles 100."""
import argparse
import itertools
import json
import logging
import math
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from fractions import Fraction

from forecast import HistoryManager

LOG = logging.getLogger(__name__)


def round_tick(price, tick, side):
    rounding = ROUND_FLOOR if side == "bid" else ROUND_CEILING
    units = Decimal(str(price)) / Decimal(str(tick))
    units += Decimal("1e-9") if side == "bid" else -Decimal("1e-9")
    return float(units.to_integral_value(
        rounding=rounding) * Decimal(str(tick)))


def session_open(sessions, now):
    """UTC recurring sessions, including overnight intervals; [] means use paused."""
    minute = now.hour * 60 + now.minute
    for start, end in sessions:
        a, b = [int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in (start, end)]
        if a == b or (a <= minute < b if a < b else minute >= a or minute < b):
            return True
    return not sessions


def validate(config):
    etfs, weights, instruments = config["etfs"], config["weights"], config["instruments"]
    if len(etfs) != 2 or len(set(etfs)) != 2 or not weights or set(etfs) & set(weights):
        raise ValueError("Need two distinct equivalent ETFs and separate constituent weights")
    if set(instruments) != set(etfs) | set(weights):
        raise ValueError("Instrument settings must cover exactly the ETFs and constituents")
    for field in ("max_order_volume", "quote_volume", "requests_per_second", "cycle_seconds",
                  "quote_refresh_seconds", "settlement_seconds", "ioc_reservation_seconds",
                  "min_edge", "quote_half_spread", "forecast_max_error", "forecast_max_shift",
                  "max_book_age_seconds", "closed_nav_max_age_seconds", "max_loss"):
        if not math.isfinite(config[field]) or config[field] <= 0:
            raise ValueError(f"{field} must be finite and positive")
    for field in ("fee_per_lot", "inventory_skew", "closed_nav_penalty"):
        if not math.isfinite(config[field]) or config[field] < 0:
            raise ValueError(f"{field} must be finite and nonnegative")
    if not 0 <= config["forecast_weight"] <= 1:
        raise ValueError("forecast_weight must be between zero and one")
    for field in ("max_order_volume", "quote_volume"):
        if int(config[field]) != config[field]:
            raise ValueError(f"{field} must be an integer")
    if not math.isfinite(config["cash_component"]):
        raise ValueError("cash_component must be finite")
    if not all(math.isfinite(v) and v > 0 for v in weights.values()):
        raise ValueError("Weights are positive share quantities per ETF, not percentage labels")
    for spec in instruments.values():
        if not math.isfinite(spec["tick_size"]) or spec["tick_size"] <= 0:
            raise ValueError("Invalid tick size")
        limit = spec["position_limit"]
        if not math.isfinite(limit) or int(limit) != limit or limit <= 0:
            raise ValueError("Invalid position limit")
        for pair in spec["sessions_utc"]:
            if len(pair) != 2:
                raise ValueError("Session requires start and end")
            for t in pair:
                datetime.strptime(t, "%H:%M")


class Gateway:
    """Single thread owns the synchronous Exchange; all calls share a paced budget."""
    def __init__(self, exchange, rate):
        self.exchange, self.spacing, self.next_call = exchange, 1 / rate, 0

    def call(self, method, *args, **kwargs):
        time.sleep(max(0, self.next_call - time.monotonic()))
        self.next_call = time.monotonic() + self.spacing
        return getattr(self.exchange, method)(*args, **kwargs)


class Trader:
    def __init__(self, exchange, config, dry_run=False, before_cycle=None, record=False):
        validate(config)
        self.c, self.dry_run = config, dry_run
        self.before_cycle = before_cycle
        self.record = record
        self.samples = []
        self.started = time.monotonic()
        self.api = Gateway(exchange, config["requests_per_second"])
        self.history = HistoryManager()
        self.pending = []  # Conservative IOC reservations in addition to observed positions.
        self.quotes_at = {iid: 0.0 for iid in config["instruments"]}
        self.cache, self.books, self.instruments = {}, {}, {}
        self.baseline_pnl = None
        self.last_report = 0
        self.quote_ids = set()
        self.shadow_limits = {}  # Accepted limits not yet visible on the info channel.

    def discover(self):
        instruments = self.api.call("get_instruments")
        missing = set(self.c["instruments"]) - set(instruments)
        if missing:
            raise ValueError(f"Unknown instrument IDs: {sorted(missing)}")
        for iid, spec in self.c["instruments"].items():
            actual = getattr(instruments[iid], "tick_size", None)
            if actual is not None and not math.isclose(float(actual), spec["tick_size"]):
                raise ValueError(f"Tick size mismatch for {iid}: config={spec['tick_size']}, exchange={actual}")
        self.instruments = instruments

    def is_open(self, iid):
        meta = self.instruments[iid]
        return (not getattr(meta, "paused", True)
                and session_open(self.c["instruments"][iid]["sessions_utc"],
                                 datetime.now(timezone.utc)))

    def snapshot(self):
        self.instruments = self.api.call("get_instruments")
        self.books = {}
        for iid in self.c["instruments"]:
            if iid not in self.instruments:
                raise RuntimeError(f"Instrument disappeared: {iid}")
            book = self.api.call("get_last_price_book", iid)
            if book and book.bids and book.asks:
                timestamp = getattr(book, "timestamp", None)
                if timestamp is None:
                    raise RuntimeError(f"No book timestamp for {iid}; cannot verify freshness")
                stamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
                age = (datetime.now(timezone.utc) - stamp).total_seconds()
                bid, ask = book.bids[0], book.asks[0]
                if (0 <= age <= self.c["max_book_age_seconds"] and
                        all(math.isfinite(p) and p > 0 for p in (bid.price, ask.price)) and
                        bid.price < ask.price and bid.volume > 0 and ask.volume > 0):
                    if self.is_open(iid):
                        self.cache[iid] = ((bid.price + ask.price) / 2, time.monotonic())
                        self.books[iid] = book
            # Polling avoids replaying get_trade_tick_history on every cycle.
            ticks = self.api.call("poll_new_trade_ticks", iid)
            for tick in ticks:
                side = str(getattr(tick, "aggressor_side", "")).lower().split(".")[-1]
                stamp = tick.timestamp
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                self.history.add(iid, side, tick.price, tick.volume, stamp.timestamp())

    def state(self, ids=None):
        positions = self.api.call("get_positions")
        outstanding = {iid: self.api.call("get_outstanding_orders", iid)
                       for iid in (self.c["instruments"] if ids is None else ids)}
        self.pending = [p for p in self.pending if p[3] > time.monotonic()]
        return positions, outstanding

    def capacity(self, iid, side, state):
        positions, orders = state
        sign = 1 if side == "bid" else -1
        limit = self.c["instruments"][iid]["position_limit"]
        reserved = sum(o.volume for o in orders[iid].values() if o.side == side)
        reserved += sum(v for i, s, v, _ in self.pending if i == iid and s == side)
        reserved += sum(v for (i, oid), (s, v) in self.shadow_limits.items()
                        if i == iid and s == side and oid not in orders[iid])
        return max(0, limit - sign * positions.get(iid, 0) - reserved)

    def cancel(self, iid):
        if self.dry_run:
            return
        self.api.call("delete_orders", iid)
        # Confirm cancellation before freeing reservations or inserting replacements.
        if self.api.call("get_outstanding_orders", iid):
            raise RuntimeError(f"Cancellation not yet confirmed for {iid}")
        self.quote_ids.discard(iid)
        self.shadow_limits = {k: v for k, v in self.shadow_limits.items() if k[0] != iid}

    def cancel_all(self):
        errors = []
        for iid in self.c["instruments"]:
            try:
                self.cancel(iid)
            except Exception as error:
                LOG.error("Cancel failed for %s: %s", iid, error)
                errors.append(error)
        if errors:
            raise errors[0]

    def send(self, iid, side, price, volume, order_type):
        # Refresh both exchange status and book before execution. Snapshot scans and
        # cancellation confirmations can otherwise age a perfectly valid signal.
        self.instruments = self.api.call("get_instruments")
        if iid not in self.books or not self.is_open(iid):
            return False
        fresh = self.api.call("get_last_price_book", iid)
        if not fresh or not fresh.bids or not fresh.asks:
            return False
        self.books[iid] = fresh
        volume = min(int(volume), self.c["max_order_volume"],
                     self.capacity(iid, side, self.state([iid])))
        if volume <= 0:
            return False
        # Risk reads may take time; reject execution on an aged snapshot.
        stamp = self.books[iid].timestamp
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        if (datetime.now(timezone.utc) - stamp).total_seconds() > self.c["max_book_age_seconds"]:
            LOG.info("Skip %s: execution snapshot expired", iid)
            return False
        price = round_tick(price, self.c["instruments"][iid]["tick_size"], side)
        if price <= 0:
            return False
        if order_type == "limit" and (price >= fresh.asks[0].price if side == "bid" else price <= fresh.bids[0].price):
            return False
        LOG.info("%s %s %s price=%.6f volume=%d", "DRY" if self.dry_run else "ORDER",
                 iid, side, price, volume)
        if self.dry_run:
            return False
        response = self.api.call("insert_order", iid, price=price, volume=volume,
                                 side=side, order_type=order_type)
        if not response.success:
            raise RuntimeError(f"Order rejected: {response!r}")
        LOG.info("Inserted order successfully, order_id=%s", response.order_id)
        if order_type == "ioc":
            self.pending.append((iid, side, volume,
                                 time.monotonic() + self.c["ioc_reservation_seconds"]))
            time.sleep(self.c["settlement_seconds"])
        else:
            self.quote_ids.add(iid)
            self.shadow_limits[(iid, response.order_id)] = (side, volume)
        return True

    def exposures(self, positions):
        total_etf = sum(positions.get(i, 0) for i in self.c["etfs"])
        return {s: positions.get(s, 0) + w * total_etf for s, w in self.c["weights"].items()}

    def hedge(self):
        """Reconcile aggregate *actual* filled exposure, including partial IOC fills."""
        positions = self.api.call("get_positions")
        exposure = self.exposures(positions)
        for iid, delta in exposure.items():
            if abs(delta) < 1:
                continue
            if iid not in self.books:
                continue  # Keep retrying on reopening; never use a stale executable price.
            # Wait for an earlier IOC to settle before retrying this hedge.
            if any(p[0] == iid and p[3] > time.monotonic() for p in self.pending):
                continue
            self.cancel(iid)
            side = "ask" if delta > 0 else "bid"
            level = self.books[iid].bids[0] if side == "ask" else self.books[iid].asks[0]
            self.send(iid, side, level.price, min(int(abs(delta)), level.volume), "ioc")
        remaining = self.exposures(self.api.call("get_positions"))
        return all(abs(v) < 1 for v in remaining.values())

    def nav(self):
        value, closed = self.c["cash_component"], False
        for iid, weight in self.c["weights"].items():
            if iid in self.books:
                book = self.books[iid]
                value += weight * (book.bids[0].price + book.asks[0].price) / 2
            elif iid in self.cache and time.monotonic() - self.cache[iid][1] <= self.c["closed_nav_max_age_seconds"]:
                value += weight * self.cache[iid][0]
                closed = True
            else:
                return None, True
        return value, closed

    def opportunities(self):
        """Return executable-cost plans: [(iid, side, price, volume), ...]."""
        candidates = []
        a, b = self.c["etfs"]
        for buy, sell in ((a, b), (b, a)):
            if buy in self.books and sell in self.books:
                ask, bid = self.books[buy].asks[0], self.books[sell].bids[0]
                profit = bid.price - ask.price - 2 * self.c["fee_per_lot"]
                qty = min(ask.volume, bid.volume, self.c["max_order_volume"])
                if profit > self.c["min_edge"]:
                    candidates.append((profit, [(buy, "bid", ask.price, qty),
                                                 (sell, "ask", bid.price, qty)]))
        # Exact rational hedge lots, e.g. (0.5,0.3,0.2) -> 10 ETF : 5,3,2 stocks.
        fractions = {i: Fraction(str(w)) for i, w in self.c["weights"].items()}
        lot = 1
        for w in fractions.values():
            lot = math.lcm(lot, w.denominator)
        if lot > self.c["max_order_volume"]:
            return candidates
        if not all(s in self.books for s in fractions):
            return candidates
        for etf in self.c["etfs"]:
            if etf not in self.books:
                continue
            for sign in (1, -1):
                # sign=1: buy ETF and sell basket, reverse for sign=-1.
                e_side = "bid" if sign == 1 else "ask"
                e_level = self.books[etf].asks[0] if sign == 1 else self.books[etf].bids[0]
                legs = [(etf, e_side, e_level.price, lot)]
                basket = self.c["cash_component"]
                for s, weight in fractions.items():
                    level = self.books[s].bids[0] if sign == 1 else self.books[s].asks[0]
                    quantity = int(weight * lot)
                    basket += float(weight) * level.price
                    legs.append((s, "ask" if sign == 1 else "bid", level.price, quantity))
                fees = sum(v for _, _, _, v in legs) * self.c["fee_per_lot"] / lot
                profit = sign * (basket - e_level.price) - fees
                available = e_level.volume >= lot and all(
                    (self.books[s].bids[0] if side == "ask" else self.books[s].asks[0]).volume >= v
                    and v <= self.c["max_order_volume"] for s, side, _, v in legs[1:])
                if available and profit > self.c["min_edge"]:
                    candidates.append((profit, legs))
        return candidates

    def arbitrage(self):
        candidates = sorted(self.opportunities(), reverse=True)
        if not candidates:
            return False
        self.cancel_all()
        state = self.state()
        for edge, legs in candidates:
            if any(self.capacity(i, s, state) < v for i, s, _, v in legs):
                continue
            iid, side, price, volume = legs[0]
            before = state[0].get(iid, 0)
            LOG.info("ARBITRAGE expected edge/unit=%.4f plan=%s", edge, legs)
            if not self.send(iid, side, price, volume, "ioc"):
                return False
            after = self.api.call("get_positions").get(iid, 0)
            filled = (after - before) * (1 if side == "bid" else -1)
            if filled > 0:
                for hedge_id, hedge_side, hedge_price, hedge_qty in legs[1:]:
                    actual = int(hedge_qty * min(filled, volume) / volume)
                    if actual:
                        self.send(hedge_id, hedge_side, hedge_price, actual, "ioc")
            # Any missing/late fills are reconciled by hedge() on subsequent cycles.
            return True
        return False

    def quote(self):
        nav, closed = self.nav()
        positions = self.api.call("get_positions")
        # Quote the less liquid ETF. Leave stocks to hedge; closed stocks use the other ETF.
        available = [i for i in self.c["etfs"] if i in self.books]
        if not available:
            return
        if closed and len(available) < 2:
            return
        if closed and any(abs(positions.get(s, 0)) >= 1 for s in self.c["weights"]):
            return
        iid = max(available, key=lambda i: self.books[i].asks[0].price - self.books[i].bids[0].price)
        if time.monotonic() - self.quotes_at[iid] < self.c["quote_refresh_seconds"]:
            return
        for old in list(self.quote_ids - {iid}):
            self.cancel(old)
        book = self.books[iid]
        other = next((i for i in available if i != iid), None)
        reference = ((self.books[other].bids[0].price + self.books[other].asks[0].price) / 2
                     if other else nav)
        if reference is None:
            return
        fair = reference if closed or nav is None else (reference + nav) / 2
        prediction = self.history.get(iid)
        usable = [p for p in prediction.values() if p.error <= self.c["forecast_max_error"]]
        if usable:
            predicted = sum(p.price for p in usable) / len(usable)
            shift = max(-self.c["forecast_max_shift"], min(self.c["forecast_max_shift"], predicted - fair))
            confidence = max(0, 1 - max(p.error for p in usable) / self.c["forecast_max_error"])
            fair += self.c["forecast_weight"] * confidence * shift
        total = sum(positions.get(i, 0) for i in self.c["etfs"])
        fair -= self.c["inventory_skew"] * total
        half = self.c["quote_half_spread"] + self.c["fee_per_lot"]
        if closed:
            if not self.c["allow_closed_quoting"]:
                return
            half += self.c["closed_nav_penalty"]
        tick = self.c["instruments"][iid]["tick_size"]
        bid = round_tick(min(fair - half, book.bids[0].price + tick, book.asks[0].price - tick), tick, "bid")
        ask = round_tick(max(fair + half, book.asks[0].price - tick, book.bids[0].price + tick), tick, "ask")
        # Quoting must remain hedgeable at current executable prices, after fees.
        use_etf_hedge = closed and other is not None
        if use_etf_hedge:
            bid = min(bid, round_tick(self.books[other].bids[0].price - self.c["min_edge"]
                                      - 2 * self.c["fee_per_lot"], tick, "bid"))
            ask = max(ask, round_tick(self.books[other].asks[0].price + self.c["min_edge"]
                                      + 2 * self.c["fee_per_lot"], tick, "ask"))
        elif not closed:
            sell_basket = self.c["cash_component"] + sum(w * self.books[s].bids[0].price for s, w in self.c["weights"].items())
            buy_basket = self.c["cash_component"] + sum(w * self.books[s].asks[0].price for s, w in self.c["weights"].items())
            fee = (1 + sum(self.c["weights"].values())) * self.c["fee_per_lot"]
            bid = min(bid, round_tick(sell_basket - self.c["min_edge"] - fee, tick, "bid"))
            ask = max(ask, round_tick(buy_basket + self.c["min_edge"] + fee, tick, "ask"))
        if bid <= 0 or bid >= ask:
            return
        self.cancel(iid)
        hedge_state = self.state()
        for side, price in (("bid", bid), ("ask", ask)):
            hedge_side = "ask" if side == "bid" else "bid"
            if use_etf_hedge:
                level = self.books[other].bids[0] if hedge_side == "ask" else self.books[other].asks[0]
                volume = min(self.c["quote_volume"], level.volume,
                             self.capacity(other, hedge_side, hedge_state))
            else:
                volume = self.c["quote_volume"]
                for stock, weight in self.c["weights"].items():
                    level = self.books[stock].bids[0] if hedge_side == "ask" else self.books[stock].asks[0]
                    volume = min(volume, int(min(level.volume, self.capacity(stock, hedge_side, hedge_state)) / weight))
            # A buyer-initiated trade consumes our ask; a seller consumes our bid.
            flow = prediction.get("ask" if side == "bid" else "bid")
            if flow and flow.error <= self.c["forecast_max_error"]:
                volume = min(volume, max(1, int(flow.volume)))
            self.send(iid, side, price, volume, "limit")
        self.quotes_at[iid] = time.monotonic()

    def closed_hedge(self):
        """When stocks close, neutralize ETF exposure using another open listing."""
        if all(i in self.books for i in self.c["weights"]):
            return False
        positions = self.api.call("get_positions")
        total = sum(positions.get(i, 0) for i in self.c["etfs"])
        # A pre-existing stock position cannot be hedged exactly with one basket.
        if any(abs(positions.get(s, 0)) >= 1 for s in self.c["weights"]):
            return False
        if total:
            self.cancel_all()
            side = "ask" if total > 0 else "bid"
            for iid in self.c["etfs"]:
                if iid not in self.books or any(p[0] == iid for p in self.pending):
                    continue
                level = self.books[iid].bids[0] if side == "ask" else self.books[iid].asks[0]
                if self.send(iid, side, level.price, min(abs(total), level.volume), "ioc"):
                    break
        return total == 0

    def cycle(self):
        if self.before_cycle:
            self.before_cycle()
        self.snapshot()
        # Existing quotes must be removed if any inputs become unusable.
        self.cancel_all_if_stale()
        pnl = self.api.call("get_pnl")
        if not math.isfinite(pnl):
            raise RuntimeError("Invalid PNL")
        if self.baseline_pnl is None:
            self.baseline_pnl = pnl
        if pnl - self.baseline_pnl <= -self.c["max_loss"]:
            raise RuntimeError("Session loss stop reached")
        if time.monotonic() - self.last_report > 5:
            LOG.info("My PNL is: %.2f; positions=%s", pnl, self.api.call("get_positions"))
            for iid in self.c["etfs"]:
                for side, prediction in self.history.get(iid).items():
                    LOG.info("FORECAST %s aggressor=%s price=%.4f volume=%.2f MAE=%.4f",
                             iid, side, prediction.price, prediction.volume, prediction.error)
            self.last_report = time.monotonic()
        # Reconcile first; cancel all passive risk while hedging outstanding exposure.
        exposure = self.exposures(self.api.call("get_positions"))
        if any(abs(v) >= 1 for v in exposure.values()):
            self.cancel_all()
            if not self.closed_hedge():
                self.hedge()
            return
        self.state()  # Expire conservative IOC reservations.
        if self.pending:
            return
        if not self.arbitrage():
            self.quote()

    def cancel_all_if_stale(self):
        closed = not all(i in self.books for i in self.c["weights"])
        positions = self.api.call("get_positions") if closed else {}
        stock_inventory = closed and any(abs(positions.get(s, 0)) >= 1 for s in self.c["weights"])
        for iid in list(self.quote_ids):
            if iid not in self.books or (closed and (
                    stock_inventory or not self.c["allow_closed_quoting"]
                    or len([i for i in self.c["etfs"] if i in self.books]) < 2)):
                self.cancel(iid)

    def run(self, cycles=None):
        self.discover()
        try:
            self.cancel_all()
            # Seed each bounded buffer once. Exchange calls remain on this thread.
            for iid in self.c["instruments"]:
                for tick in self.api.call("get_trade_tick_history", iid):
                    stamp = tick.timestamp
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    side = str(getattr(tick, "aggressor_side", "")).lower().split(".")[-1]
                    self.history.add(iid, side, tick.price, tick.volume, stamp.timestamp())
            self.history.start()
            if self.record:
                self.sample(0)
            for index in range(cycles) if cycles is not None else itertools.count():
                self.cycle()
                if self.record:
                    self.sample(index + 1)
                time.sleep(self.c["cycle_seconds"])
        finally:
            if self.history.thread.is_alive():
                self.history.close()
            self.cancel_all()

    def sample(self, index):
        positions = self.api.call("get_positions")
        marks = {}
        for iid in self.c["instruments"]:
            book = self.api.call("get_last_price_book", iid)
            if book and book.bids and book.asks:
                marks[iid] = (book.bids[0].price + book.asks[0].price) / 2
        self.samples.append({"cycle": index, "elapsed_seconds": time.monotonic() - self.started,
                             "pnl": self.api.call("get_pnl"), "positions": positions,
                             "marks": marks, "exposures": self.exposures(positions)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.example.json")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--live", action="store_true", help="Send real competition orders")
    parser.add_argument("--inspect", action="store_true", help="Print instrument metadata only")
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--report", help="Write final metrics as JSON after a finite run")
    args = parser.parse_args()
    if args.report and args.cycles is None and not args.demo:
        parser.error("--report requires a finite --cycles value")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")
    with open(args.config) as f:
        config = json.load(f)
    if args.demo:
        if args.live:
            parser.error("--demo and --live are mutually exclusive")
        from simulator import SimExchange, demo_config
        config = demo_config(config)
        exchange = SimExchange(config)
    else:
        # Optibook is supplied by the competition VM, not a similarly named PyPI package.
        from optibook.synchronous_client import Exchange
        exchange = Exchange()
        exchange.connect()
    if args.inspect:
        required = ("get_instruments", "get_last_price_book", "get_positions", "get_pnl",
                    "get_outstanding_orders", "delete_orders", "insert_order",
                    "get_trade_tick_history", "poll_new_trade_ticks")
        print("Missing SDK methods:", [m for m in required if not callable(getattr(exchange, m, None))])
        for iid, meta in exchange.get_instruments().items():
            print(iid, repr(meta), "tick_size=", getattr(meta, "tick_size", None),
                  "paused=", getattr(meta, "paused", None))
        return
    if args.live and (config.get("verified") is not True or "REPLACE" in json.dumps(config)):
        parser.error("Fill actual instruments, basket formula and limits; set verified=true first")
    try:
        trader = Trader(exchange, config, dry_run=not (args.demo or args.live),
                        before_cycle=exchange.advance if args.demo else None, record=bool(args.report))
        trader.run(
            args.cycles if args.cycles is not None else (100 if args.demo else None))
        pnl, positions = trader.api.call("get_pnl"), trader.api.call("get_positions")
        LOG.info("FINAL PNL=%.2f positions=%s", pnl, positions)
        if args.report:
            metrics = {"mode": "synthetic_demo" if args.demo else "live" if args.live else "dry_run",
                       "pnl": pnl, "positions": positions,
                       "constituent_exposures": trader.exposures(positions),
                       "samples": trader.samples,
                       "limits": {i: s["position_limit"] for i, s in config["instruments"].items()},
                       "forecast_max_error": config["forecast_max_error"],
                       "fill_events": exchange.fill_events if args.demo else None,
                       "forecasts": {i: {s: vars(p) for s, p in trader.history.get(i).items()}
                                     for i in config["instruments"]},
                       "note": "Synthetic demo metrics do not establish live profitability."}
            with open(args.report, "w") as f:
                json.dump(metrics, f, indent=2)
                f.write("\n")
    except KeyboardInterrupt:
        LOG.info("Stopped; outstanding orders cancelled. Positions are retained.")


if __name__ == "__main__":
    main()
