"""Main entry point for the free RTG replay, synthetic demo, or Optibook adapter."""
import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Examples: --engine rtg --speed 50; --engine demo --cycles 100; "
               "--engine optibook --inspect. Other arguments are forwarded to the selected engine.")
    parser.add_argument("--engine", choices=("rtg", "demo", "optibook"), default="rtg",
                        help="RTG is the default and needs no Optibook account")
    args, forwarded = parser.parse_known_args(argv)
    if args.engine == "rtg":
        from run_ready_trader_go import main as run
        return run(forwarded)
    if "--demo" in forwarded:
        parser.error("Select synthetic mode with --engine demo")
    if args.engine == "demo" and "--live" in forwarded:
        parser.error("--live requires --engine optibook")
    from trading import main as run
    return run((["--demo"] if args.engine == "demo" else []) + forwarded)


if __name__ == "__main__":
    main()
