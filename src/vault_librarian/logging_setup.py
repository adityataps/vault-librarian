"""Tiered stdout logging (architecture.md §4.14)."""

from __future__ import annotations

import logging


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy third-party loggers unless verbose was explicitly requested.
    logging.getLogger("watchdog").setLevel(logging.WARNING if not verbose else logging.DEBUG)
    logging.getLogger("LiteLLM").setLevel(logging.WARNING if not verbose else logging.INFO)
