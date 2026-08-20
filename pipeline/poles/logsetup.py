"""One logger per run: stderr plus work/<region>/<snapshot>/log.txt."""
from __future__ import annotations

import logging

from .workspace import Workspace

FORMAT = "%(asctime)s %(levelname)s %(message)s"


def get_logger(ws: Workspace) -> logging.Logger:
    logger = logging.getLogger(f"poles.{ws.region}.{ws.snapshot}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        ws.base.mkdir(parents=True, exist_ok=True)
        for handler in (logging.StreamHandler(), logging.FileHandler(ws.base / "log.txt", encoding="utf-8")):
            handler.setFormatter(logging.Formatter(FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
            logger.addHandler(handler)
    return logger
