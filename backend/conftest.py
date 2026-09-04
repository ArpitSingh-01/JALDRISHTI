"""
Shared pytest setup for the JALDRISHTI backend.

Two jobs:
  1. Put `backend/` on sys.path so `import jaldrishti` works no matter where
     pytest is invoked from.
  2. Provide the chart directory. Every validation test writes a PNG, because a
     passing assertion convinces a developer while a chart convinces a jury —
     and we need both.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Headless: these run in CI and on a laptop with no display. Must be set before
# pyplot is imported anywhere.
import matplotlib  # noqa: E402

matplotlib.use("Agg")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: full simulation validation, ~1 min (SPH benchmark)")


@pytest.fixture(scope="session")
def chart_dir() -> Path:
    """
    outputs/validation/ at the repo root — gitignored, so large PNGs never end
    up in version control, but the path is stable enough to reference from the
    report generator.
    """
    d = REPO_ROOT / "outputs" / "validation"
    d.mkdir(parents=True, exist_ok=True)
    return d
