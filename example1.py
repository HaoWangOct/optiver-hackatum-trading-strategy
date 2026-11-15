"""Read-only instrument, book, position, and PNL discovery. Defaults to synthetic data."""
import argparse

from helper import connect_optibook, load_demo, print_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("demo", "optibook"), default="demo")
    parser.add_argument("--config", default="config.example.json")
    args = parser.parse_args(argv)
    exchange = connect_optibook() if args.engine == "optibook" else load_demo(args.config)[0]
    print_report(exchange)


if __name__ == "__main__":
    main()
