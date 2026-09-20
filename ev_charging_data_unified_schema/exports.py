"""The exports/ read contract (docs/BRIEF.md § 5, ADR-0015).

Every gold relation whose dbt meta says ``export: true`` is written to ``exports/<name>.parquet``
(zstd, rows sorted by the relation's grain key so two builds of the same inputs give the same
bytes) and, where ``export_json: true``, to ``exports/<name>.json`` (small relations only).
``exports/manifest.json`` records run id, code commit, and per file the row count, byte size
and sha256; ``exports/SCHEMA.md`` documents every column from the dbt manifest and carries the
licence attribution. Only station-day grain and above is exported; session-grain relations are
never written here (a test enforces the allowed set).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb

GRAIN_KEYS: dict[str, list[str]] = {
    "fct_station_day": ["station_key", "local_date"],
    "dim_station": ["station_key"],
    "dim_operator": ["operator_key"],
    "dim_date": ["date_key"],
    "mart_monthly": ["source", "operator_key", "year_month"],
}
SESSION_GRAIN = {"fct_charging_session", "meta_landed_files", "int_station_gaps"}
SIZE_CEILING_BYTES = 5 * 1024 * 1024
ATTRIBUTION = (
    "Contains public sector information licensed under the Open Government Licence v3.0 "
    "(UK Department for Transport, Electric Chargepoint Analysis 2017). Boulder, CO and Cary, NC "
    "data are published under CC0; see docs/DATA_SOURCES.md for the verbatim licences and URLs."
)


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "export-" + now.strftime("%Y%m%dT%H%M%SZ")


def export_models(dbt_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for node in dbt_manifest["nodes"].values():
        if node.get("resource_type") != "model" or "gold" not in node.get("tags", []):
            continue
        meta = (node.get("config") or {}).get("meta") or {}
        if not meta.get("export"):
            continue
        out.append(
            {
                "name": node["alias"] or node["name"],
                "json": bool(meta.get("export_json")),
                "columns": node.get("columns", {}),
                "description": node.get("description", ""),
            }
        )
    return sorted(out, key=lambda m: m["name"])


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_exports(
    con: duckdb.DuckDBPyConnection,
    dbt_manifest: dict[str, Any],
    out_dir: Path,
    *,
    rid: str,
    code_commit: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    models = export_models(dbt_manifest)
    for m in models:
        name = m["name"]
        if name in SESSION_GRAIN or name not in GRAIN_KEYS:
            raise ValueError(f"{name} is not an exportable grain (station-day or above)")
        keys = GRAIN_KEYS[name]
        df = con.execute(f"select * from gold.{name} order by {', '.join(keys)}").df()
        pq = out_dir / f"{name}.parquet"
        df.to_parquet(pq, index=False, compression="zstd")
        files[pq.name] = {
            "relation": name,
            "format": "parquet",
            "rows": int(len(df)),
            "bytes": pq.stat().st_size,
            "sha256": sha256_of(pq),
            "grain": keys,
        }
        if m["json"]:
            js = out_dir / f"{name}.json"
            js.write_text(df.to_json(orient="records", date_format="iso", indent=1) + "\n")
            files[js.name] = {
                "relation": name,
                "format": "json",
                "rows": int(len(df)),
                "bytes": js.stat().st_size,
                "sha256": sha256_of(js),
                "grain": keys,
            }
    manifest = {
        "artifact": "exports",
        "run_id": rid,
        "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit,
        "attribution": ATTRIBUTION,
        "size_ceiling_bytes": SIZE_CEILING_BYTES,
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (out_dir / "SCHEMA.md").write_text(render_schema(models, manifest))
    return manifest


def render_schema(models: list[dict[str, Any]], manifest: dict[str, Any]) -> str:
    lines = [
        "# exports/ — the read contract",
        "",
        "_Written by `scripts/export.py` from the gold layer; do not edit by hand. Every file is listed in "
        "`manifest.json` with its row count, byte size and sha256. Rows are sorted by the grain key, so two builds "
        "of the same inputs produce identical bytes._",
        "",
        "Grain: station-day and above only; no session-grain rows are exported (ADR-0015).",
        "",
        "## Attribution and licences",
        "",
        manifest["attribution"],
        "",
        "| Source | Licence | Where stated |",
        "|---|---|---|",
        '| Boulder, CO | CC0 ("CC0 License", linked to CC0 1.0) | ArcGIS item metadata, `licenseInfo` |',
        "| Cary, NC | CC0 1.0 Universal | Opendatasoft dataset metadata, `license` and `license_url` |",
        "| UK Department for Transport, 2017 | Open Government Licence v3.0 | both publication pages on gov.uk |",
        "",
        "Utilization is never stored: compute it as a ratio of sums (a measure's minutes over `available_port_minutes`) at whatever rollup you need.",
        "",
    ]
    for m in models:
        f = manifest["files"].get(f"{m['name']}.parquet", {})
        lines += [
            f"## `{m['name']}`",
            "",
            m["description"],
            "",
            (
                f"Grain: {', '.join(f['grain']) if f else 'n/a'}. Formats: parquet"
                + (", json" if m["json"] else "")
                + f". Rows: {f.get('rows', 'n/a'):,}."
                if f
                else ""
            ),
            "",
            "| Column | Type | Description |",
            "|---|---|---|",
        ]
        for cname, c in m["columns"].items():
            lines.append(f"| `{cname}` | {c.get('data_type') or ''} | {c.get('description', '')} |")
        lines.append("")
    return "\n".join(lines)
