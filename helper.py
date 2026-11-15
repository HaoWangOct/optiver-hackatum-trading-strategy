"""Read-only market discovery and reporting helpers for scripts and notebooks."""
import json
from pathlib import Path

from colors import signed_number


def load_demo(config_path="config.example.json"):
    from simulator import SimExchange, demo_config
    config = demo_config(json.loads(Path(config_path).read_text()))
    return SimExchange(config), config


def connect_optibook():
    """Connect using the official, externally installed SDK and local credentials."""
    try:
        from optibook.synchronous_client import Exchange
    except ImportError as error:
        raise RuntimeError("Install the official competition SDK first; see optibook/README.md") from error
    exchange = Exchange()
    exchange.connect()
    return exchange


def market_snapshot(exchange):
    """Inspect the market without submitting, amending, or cancelling orders."""
    instruments = exchange.get_instruments()
    books = {}
    for iid, meta in instruments.items():
        book = exchange.get_last_price_book(iid)
        books[iid] = {
            "paused": getattr(meta, "paused", None),
            "tick_size": getattr(meta, "tick_size", None),
            "bids": [{"price": level.price, "volume": level.volume}
                     for level in book.bids[:3]] if book else [],
            "asks": [{"price": level.price, "volume": level.volume}
                     for level in book.asks[:3]] if book else [],
        }
    return {"pnl": exchange.get_pnl(), "positions": exchange.get_positions(), "books": books}


def print_report(exchange):
    report = market_snapshot(exchange)
    print("PNL:", signed_number(report["pnl"]))
    print(json.dumps(report, indent=2))
    return report
