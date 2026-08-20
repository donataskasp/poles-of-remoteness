import logging
from pathlib import Path

import pytest

from poles.config import load_region

REGIONS = Path(__file__).resolve().parents[1] / "regions"


@pytest.fixture
def regions_dir() -> Path:
    return REGIONS


@pytest.fixture
def cfg():
    return load_region(REGIONS / "europe.yaml")


@pytest.fixture
def log() -> logging.Logger:
    logger = logging.getLogger("poles.test")
    logger.setLevel(logging.DEBUG)
    return logger
