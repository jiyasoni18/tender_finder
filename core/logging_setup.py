"""Rotating file + console logging, shared by every worker."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import LOGS_DIR, PIPELINE

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    level = getattr(logging, PIPELINE.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)-14s | %(name)-18s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "app.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet noisy third-party libs.
    for noisy in ("urllib3", "pdfminer", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
