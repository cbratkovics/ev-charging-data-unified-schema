"""Shared fixtures. Everything runs offline: the landed fixture under tests/fixtures/ is the
only input (it is hand-built and labelled as such in tests/fixtures/README.md)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ev_charging_data_unified_schema.config import FIXTURES_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def raw_frame() -> pd.DataFrame:
    """A small raw frame with mixed types, nulls and a duplicate row, as a source parser
    would hand it over before landing."""
    return pd.DataFrame(
        {
            "Station Name": ["A 1", "A 1", "B 2", None],
            "Start Date": ["2020-01-01 08:00", "2020-01-01 08:00", "01/02/2020 09:30", "x"],
            "Energy (kWh)": [1.5, 1.5, None, 0],
            "Port": [1, 1, 2, 2],
        }
    )
