"""dim_station's inferred ports must equal the sensitivity module's production definition per
station (the SQL sweep and the Python sweep implement the same rule; a divergence between them
was the Cary defect of ADR-0014). Runs on the fixture warehouse; skipped when it is absent."""

from __future__ import annotations

import duckdb
import pytest

from ev_charging_data_unified_schema.config import REPO_ROOT
from ev_charging_data_unified_schema.sensitivity import (
    _sessions,
    _stations,
    concurrency_levels,
    ports_by_definition,
)

FIXTURE_DB = REPO_ROOT / ".duckdb" / "fixture.duckdb"


def test_sql_and_python_port_inference_agree_per_station() -> None:
    if not FIXTURE_DB.exists():
        pytest.skip("fixture warehouse not built (make dbt-fixture)")
    con = duckdb.connect(str(FIXTURE_DB), read_only=True)
    try:
        sessions = _sessions(con)
        stations = _stations(con)
    finally:
        con.close()
    levels, _ = concurrency_levels(sessions[sessions["is_non_trivial"]])
    defs = ports_by_definition(levels, stations)
    expected = stations.set_index("station_key")["ports_inferred"]
    assert defs["production"].reindex(expected.index).tolist() == expected.tolist()
