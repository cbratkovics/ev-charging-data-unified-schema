"""Column-level profiling of raw source files, written as a committed artifact.

Everything in ``docs/PROFILE.md`` is rendered from ``artifacts/profile/<run_id>.json``; the
artifact records the run id, code commit, every input file's sha256 and row count, and one
block per column (inferred type, null rate, distinct count, min / max where parseable, sample
values). Source-specific questions (stable ids, overlaps, durations, implausible sessions) are
answered by :func:`answer_questions` from declared column roles so the answers are reproducible.
No number may reach a doc except through this artifact.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ev_charging_data_unified_schema.config import REPO_ROOT

SAMPLE_VALUES = 5
DATE_PATTERNS: tuple[tuple[str, str], ...] = (
    # (regex on the whole trimmed value, pandas format)
    (r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "ISO"),
    (r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$", "%Y-%m-%d %H:%M"),
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
    (r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}(:\d{2})?$", "MDY_OR_DMY"),
    (r"^\d{1,2}/\d{1,2}/\d{4}$", "MDY_OR_DMY_DATE"),
    (r"^\d{1,2}/\d{1,2}/\d{2} \d{1,2}:\d{2}$", "MDY2_OR_DMY2"),
)
DURATION_HMS = re.compile(r"^\d{1,4}:\d{2}:\d{2}$")
NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # pragma: no cover - not a git checkout
        return ""


def run_id(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.UTC)
    return "profile-" + now.strftime("%Y%m%dT%H%M%SZ")


def _match_share(s: pd.Series, pattern: re.Pattern[str]) -> float:
    s = s.dropna().astype(str).str.strip()
    if s.empty:
        return 0.0
    return float(s.str.match(pattern).mean())


def infer_type(s: pd.Series) -> tuple[str, str | None]:
    """(inferred type, detail). Types: empty, integer, decimal, duration_hms, datetime,
    date, text. Detail carries the date pattern name. A column counts as a type when at least
    99% of its non-null values match; the residue is reported as parse failures."""
    nn = s.dropna().astype(str).str.strip()
    nn = nn[nn != ""]
    if nn.empty:
        return "empty", None
    if nn.str.match(r"^-?\d+$").mean() >= 0.99:
        return "integer", None
    if nn.str.match(NUMERIC).mean() >= 0.99:
        return "decimal", None
    if nn.str.match(DURATION_HMS).mean() >= 0.99:
        return "duration_hms", None
    for rx, name in DATE_PATTERNS:
        if nn.str.match(rx).mean() >= 0.99:
            return ("date" if "DATE" in name or name == "%Y-%m-%d" else "datetime"), name
    return "text", None


def day_first_evidence(s: pd.Series) -> dict[str, Any] | None:
    """For slash dates: how many values have a first field > 12 (impossible as a month) versus
    a second field > 12 (impossible as a day-first day). Decides MDY vs DMY from the data."""
    nn = s.dropna().astype(str).str.strip()
    m = nn.str.extract(r"^(\d{1,2})/(\d{1,2})/")
    if m.dropna().empty:
        return None
    a = pd.to_numeric(m[0], errors="coerce")
    b = pd.to_numeric(m[1], errors="coerce")
    return {
        "first_field_gt_12": int((a > 12).sum()),
        "second_field_gt_12": int((b > 12).sum()),
        "verdict": (
            "day_first"
            if (a > 12).sum() > 0 and (b > 12).sum() == 0
            else "month_first" if (b > 12).sum() > 0 and (a > 12).sum() == 0 else "ambiguous"
        ),
    }


def parse_datetime(s: pd.Series, pattern: str | None, *, dayfirst: bool = False) -> pd.Series:
    nn = s.astype("string").str.strip()
    if pattern == "ISO":
        return pd.to_datetime(nn, errors="coerce", utc=True, format="ISO8601")
    if pattern in ("MDY_OR_DMY", "MDY_OR_DMY_DATE", "MDY2_OR_DMY2", None):
        return pd.to_datetime(nn, errors="coerce", dayfirst=dayfirst)
    return pd.to_datetime(nn, errors="coerce", format=pattern)


def profile_column(name: str, s: pd.Series) -> dict[str, Any]:
    n = int(len(s))
    nn = s.dropna()
    nn = nn[nn.astype(str).str.strip() != ""]
    inferred, detail = infer_type(s)
    out: dict[str, Any] = {
        "name": name,
        "inferred_type": inferred,
        "pattern": detail,
        "rows": n,
        "null_or_blank": int(n - len(nn)),
        "null_rate": round(float((n - len(nn)) / n), 6) if n else None,
        "distinct": int(nn.nunique()),
        "sample_values": [str(v) for v in nn.drop_duplicates().head(SAMPLE_VALUES).tolist()],
    }
    if inferred in ("integer", "decimal"):
        num = pd.to_numeric(nn.astype(str).str.strip(), errors="coerce")
        out.update(
            {
                "min": float(num.min()),
                "max": float(num.max()),
                "mean": round(float(num.mean()), 6),
                "zero_count": int((num == 0).sum()),
                "negative_count": int((num < 0).sum()),
            }
        )
    elif inferred in ("datetime", "date"):
        ev = day_first_evidence(nn)
        dayfirst = bool(ev and ev["verdict"] == "day_first")
        parsed = parse_datetime(nn, detail, dayfirst=dayfirst)
        out.update(
            {
                "min": None if parsed.min() is pd.NaT else str(parsed.min()),
                "max": None if parsed.max() is pd.NaT else str(parsed.max()),
                "parse_failures": int(parsed.isna().sum()),
                "day_first_evidence": ev,
            }
        )
    elif inferred == "duration_hms":
        parts = nn.astype(str).str.strip().str.split(":", expand=True).astype(int)
        minutes = parts[0] * 60 + parts[1] + parts[2] / 60
        out.update(
            {
                "min_minutes": round(float(minutes.min()), 3),
                "max_minutes": round(float(minutes.max()), 3),
                "zero_count": int((minutes == 0).sum()),
                "over_24h_count": int((minutes > 24 * 60).sum()),
            }
        )
    return out


@dataclass
class FileProfile:
    path: str
    sha256: str
    bytes: int
    rows: int
    columns: list[str]
    exact_duplicate_rows: int
    column_profiles: list[dict[str, Any]] = field(default_factory=list)


def read_raw_strings(path: Path, **read_kwargs: Any) -> pd.DataFrame:
    """Every column as a nullable string; no type inference, no NA token guessing beyond
    the empty string."""
    path = Path(path)
    kwargs = {"dtype": "string", "keep_default_na": False, "na_values": [""], **read_kwargs}
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, **kwargs)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path).astype("string")
    raise ValueError(f"unsupported raw file {path}")


def profile_file(path: Path, frame: pd.DataFrame) -> FileProfile:
    return FileProfile(
        path=(
            path.resolve().relative_to(REPO_ROOT).as_posix()
            if path.resolve().is_relative_to(REPO_ROOT)
            else str(path)
        ),
        sha256=sha256_of(path),
        bytes=path.stat().st_size,
        rows=int(len(frame)),
        columns=[str(c) for c in frame.columns],
        exact_duplicate_rows=int(frame.duplicated().sum()),
        column_profiles=[profile_column(str(c), frame[c]) for c in frame.columns],
    )


def write_artifact(payload: dict[str, Any], out_dir: Path, rid: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{rid}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    (out_dir / "latest.json").write_text(json.dumps({"run_id": rid, "path": path.name}) + "\n")
    return path


def file_profile_dict(fp: FileProfile) -> dict[str, Any]:
    return asdict(fp)


# --- session-level helpers shared by the profiler and (later) the silver tests ------------------


def hms_to_minutes(s: pd.Series) -> pd.Series:
    """``H:MM:SS`` (hours unbounded, so 95:06:31 is 5,706 minutes) to float minutes; NaN where
    the value is missing or not of that shape."""
    parts = s.astype("string").str.strip().str.extract(r"^(\d+):(\d{2}):(\d{2})$")
    return (
        pd.to_numeric(parts[0], errors="coerce") * 60
        + pd.to_numeric(parts[1], errors="coerce")
        + pd.to_numeric(parts[2], errors="coerce") / 60
    )


def parse_mixed_us(s: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """A column that mixes ``M/D/YYYY H:MM`` and ISO ``YYYY-MM-DD HH:MM:SS`` (Boulder does).
    Returns naive timestamps and the count of rows in each shape."""
    st = s.astype("string").str.strip()
    is_iso = st.str.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$").fillna(False).astype(bool)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[is_iso] = pd.to_datetime(st[is_iso], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    out[~is_iso] = pd.to_datetime(st[~is_iso], format="%m/%d/%Y %H:%M", errors="coerce")
    return out, {"iso_rows": int(is_iso.sum()), "slash_rows": int((~is_iso).sum())}


def max_concurrency(start: pd.Series, end: pd.Series, by: pd.Series) -> dict[str, int]:
    """Max simultaneous sessions per key: a sweep over start / end events, ends before starts at
    the same instant. A lower bound on the number of ports the key has had in service."""
    out: dict[str, int] = {}
    df = pd.DataFrame({"s": start, "e": end, "k": by}).dropna()
    df = df[df["e"] >= df["s"]]
    for key, g in df.groupby("k"):
        ev = pd.concat(
            [pd.DataFrame({"t": g["s"], "d": 1}), pd.DataFrame({"t": g["e"], "d": -1})]
        ).sort_values(["t", "d"])
        out[str(key)] = int(ev["d"].cumsum().max())
    return out


def dst_transition_gaps(
    start: pd.Series, end: pd.Series, duration_min: pd.Series, transitions: list[str]
) -> dict[str, dict[str, Any]]:
    """For each DST transition date (local 01:00 to 02:00 window), the sessions that span the
    window and the distribution of (end - start) - duration in whole minutes. Wall-clock local
    timestamps show +60 at spring-forward and -60 at fall-back; UTC timestamps show 0."""
    gap = (end - start).dt.total_seconds() / 60 - duration_min
    out: dict[str, dict[str, Any]] = {}
    for day in transitions:
        dd = pd.Timestamp(day)
        mask = (start < dd + pd.Timedelta("2h")) & (end > dd + pd.Timedelta("1h"))
        counts = gap[mask].round(0).value_counts().head(4)
        out[day] = {
            "sessions_spanning_window": int(mask.sum()),
            "gap_minutes_counts": {str(int(k)): int(v) for k, v in counts.items()},
        }
    return out
