"""Ordered stage registry. Each stage module registers its run function here as it lands."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from .config import RegionConfig
from .workspace import Workspace

StageFn = Callable[[RegionConfig, Workspace, logging.Logger], Optional[dict]]

ORDER: tuple[str, ...] = ("fetch", "extract", "classify", "grid", "poles", "validate", "publish")


def registry() -> dict[str, StageFn | None]:
    """Stage name -> run function, or None for stages that later plan stages will add."""
    reg: dict[str, StageFn | None] = {name: None for name in ORDER}
    from . import fetch
    reg["fetch"] = fetch.run
    from . import classify
    reg["classify"] = classify.run
    from . import extract
    reg["extract"] = extract.run
    from . import grid
    reg["grid"] = grid.run
    return reg
