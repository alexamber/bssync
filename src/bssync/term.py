"""ANSI color helpers.

Colors disable automatically when stdout isn't a TTY, when NO_COLOR is set
(https://no-color.org), or when TERM=dumb. No dependencies.
"""

import os
import sys


def _enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


_ON = _enabled()

RESET = "\033[0m" if _ON else ""
BOLD = "\033[1m" if _ON else ""
DIM = "\033[2m" if _ON else ""
RED = "\033[31m" if _ON else ""
GREEN = "\033[32m" if _ON else ""
YELLOW = "\033[33m" if _ON else ""
CYAN = "\033[36m" if _ON else ""


def ok(s: str) -> str:
    return f"{GREEN}{s}{RESET}"


def warn(s: str) -> str:
    return f"{YELLOW}{s}{RESET}"


def err(s: str) -> str:
    return f"{RED}{s}{RESET}"


def dim(s: str) -> str:
    return f"{DIM}{s}{RESET}"


def bold(s: str) -> str:
    return f"{BOLD}{s}{RESET}"


def info(s: str) -> str:
    return f"{CYAN}{s}{RESET}"
