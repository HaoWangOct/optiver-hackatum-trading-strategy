"""Optional terminal colors; redirected output and NO_COLOR remain plain text."""
import os
import sys


def signed_number(value, decimals=2):
    text = f"{value:+,.{decimals}f}"
    if "NO_COLOR" in os.environ or not sys.stdout.isatty():
        return text
    color = "\033[32m" if value > 0 else "\033[31m" if value < 0 else "\033[90m"
    return color + text + "\033[0m"
