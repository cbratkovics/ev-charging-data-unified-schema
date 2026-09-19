"""Gold marts for serving: parquet files exported by the scheduled dbt build, queried in-process.

``dbt run-operation export_gold`` writes ``artifacts/marts/<alias>.parquet`` and
``_export_manifest.json``. The API opens them with an in-memory DuckDB connection at startup: no
MotherDuck token, no network. Versioned marts are read at an explicit version; a version stays
served for at least one season after its successor ships (docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

MART_TABLES: tuple[str, ...] = (
    "dim_entity",
    "dim_model_version",
    "fct_entity_period",
    "fct_period_eval",
    "fct_decision_policy",
    "fct_decision_policy_v2",
)
EXPORT_MANIFEST = "_export_manifest.json"
MART_VERSIONS: dict[str, dict[int, str]] = {
    "fct_decision_policy": {1: "fct_decision_policy", 2: "fct_decision_policy_v2"}
}
DECISIONS_MART_VERSION = 1
# The marts /marts/{mart} may serve, and the columns a caller may filter on (equality).
SERVABLE: dict[str, tuple[str, ...]] = {
    "fct_period_eval": ("cohort", "season", "candidate", "model_version", "eval_window"),
    "fct_entity_period": ("station_id", "season", "candidate", "model_version"),
    "fct_decision_policy": ("season", "channel", "candidate", "min_floor"),
    "dim_entity": ("channel",),
    "dim_model_version": (),
}


def mart_table(mart: str, version: int | None = None) -> str:
    if mart not in MART_VERSIONS:
        if version not in (None, 1):
            raise KeyError(f"{mart} is not versioned")
        return mart
    versions = MART_VERSIONS[mart]
    if version is None or version not in versions:
        raise KeyError(f"{mart} is versioned; pass version= one of {sorted(versions)}")
    return versions[version]


class MartStore:
    def __init__(self, marts_dir: Path):
        self.dir = Path(marts_dir)
        manifest_path = self.dir / EXPORT_MANIFEST
        if not manifest_path.exists():
            raise FileNotFoundError(f"no exported marts at {self.dir} (missing {EXPORT_MANIFEST})")
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.export: dict[str, Any] = {
            "exported_at_utc": entries[0]["exported_at_utc"] if entries else None,
            "target": entries[0]["target"] if entries else None,
            "invocation_id": entries[0]["invocation_id"] if entries else None,
            "code_commit": (entries[0].get("code_commit") or None) if entries else None,
            "row_counts": {e["model"]: int(e["row_count"]) for e in entries},
        }
        self.con = duckdb.connect(database=":memory:")
        self.tables: list[str] = []
        for name in MART_TABLES:
            path = self.dir / f"{name}.parquet"
            if path.exists():
                quoted = str(path).replace("'", "''")
                self.con.execute(f"create view {name} as select * from read_parquet('{quoted}')")
                self.tables.append(name)

    def rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def query(
        self, mart: str, filters: dict[str, Any], *, limit: int = 5000
    ) -> list[dict[str, Any]]:
        if mart not in SERVABLE:
            raise KeyError(f"unknown mart {mart!r}; servable: {sorted(SERVABLE)}")
        table = mart_table(mart, DECISIONS_MART_VERSION) if mart in MART_VERSIONS else mart
        if table not in self.tables:
            raise FileNotFoundError(f"{table} was not exported")
        where, params = [], []
        for col, val in filters.items():
            if col not in SERVABLE[mart]:
                raise KeyError(f"{mart} cannot be filtered on {col!r}; allowed: {SERVABLE[mart]}")
            where.append(f"{col} = ?")
            params.append(val)
        clause = (" where " + " and ".join(where)) if where else ""
        return self.rows(f"select * from {table}{clause} limit {int(limit)}", params)


def load_marts(marts_dir: Path) -> MartStore | None:
    try:
        return MartStore(marts_dir)
    except FileNotFoundError:
        return None
