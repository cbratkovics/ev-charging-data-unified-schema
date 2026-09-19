"""Rules-based target from raw stat columns — the one TargetSpec of this project.

STUB. The synthetic loader publishes the target it computes with these exact rules, so
``reconcile`` returns no rows. When you plug in a real source, reimplement ``derive`` from the
source's documented rules and keep ``reconcile`` comparing against the value the source itself
publishes (``PUBLISHED_COLUMN``); the test ``test_target_spec_derives_and_reconciles`` must
pass row for row before any number is published. Never derive one format from another by a
fixed multiplier; write the rules.
"""

from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.config import PROJECT
from ev_charging_data_unified_schema.interfaces import TargetSpec

REQUIRED_COLUMNS: tuple[str, ...] = ("stat_a", "stat_b", "stat_c")
WEIGHTS: dict[str, float] = {"stat_a": 0.1, "stat_b": 0.5, "stat_c": 1.0}
PUBLISHED_COLUMN = PROJECT.target_column


def derive(df: pd.DataFrame) -> pd.Series:
    """The target under the rules; missing stats count as zero."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(f"target rules require columns {missing}")
    s = df[list(REQUIRED_COLUMNS)].astype("float64").fillna(0.0)
    out = sum(w * s[c] for c, w in WEIGHTS.items())
    out.name = PROJECT.target_column
    return out


def reconcile(df: pd.DataFrame, tolerance: float = 0.01) -> pd.DataFrame:
    """Rows where the rules disagree with the source's published target. Empty = ok."""
    if PUBLISHED_COLUMN not in df.columns:
        return pd.DataFrame(columns=[*PROJECT.grain, "ours", "published", "abs_diff"])
    ours = derive(df)
    theirs = pd.to_numeric(df[PUBLISHED_COLUMN], errors="coerce")
    mask = theirs.notna() & ((ours - theirs).abs() > tolerance)
    diff = df.loc[mask, list(PROJECT.grain)].copy()
    diff["ours"], diff["published"] = ours[mask], theirs[mask]
    diff["abs_diff"] = (ours[mask] - theirs[mask]).abs()
    return diff.reset_index(drop=True)


TARGET_SPEC = TargetSpec(
    column=PROJECT.target_column,
    units=PROJECT.target_units,
    required_columns=REQUIRED_COLUMNS,
    derive=derive,
    reconcile=reconcile,
)
