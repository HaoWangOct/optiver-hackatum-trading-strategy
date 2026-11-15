"""Run a short five-product synthetic strategy session; never connects to Optibook."""
import sys

from trading import main


if __name__ == "__main__":
    main(["--demo", "--cycles", "25", *sys.argv[1:]])
