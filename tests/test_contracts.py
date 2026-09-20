"""Contract and drift-policy branches on tiny frames (docs/BRIEF.md § 5)."""

from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema.data import contracts as c

FAM = c.FamilyContract(
    family="f",
    file_pattern="fixture",
    columns=(
        c.ColumnSpec("id", "integer"),
        c.ColumnSpec("kwh", "decimal"),
        c.ColumnSpec("note", "text", required=False),
    ),
    aliases={"Energy": "kwh"},
    null_tokens=("NA",),
)
CON = c.SourceContract(source="s", families=(FAM,))


def _codes(drift: c.FileDrift) -> set[tuple[str, str, str]]:
    return {(f.column, f.severity, f.code) for f in drift.findings}


def test_conforming_file_is_ok() -> None:
    frame = pd.DataFrame(
        {"id": ["1", "2"], "kwh": ["1.5", "NA"], "note": ["a", None]}, dtype="string"
    )
    out, drift = c.check_file(frame, CON, "fixture.csv")
    assert drift.outcome == "ok" and drift.reason_codes == [] and drift.family == "f"
    assert list(out.columns) == ["id", "kwh", "note"] and drift.rows == 2


def test_unknown_column_warns_and_is_kept() -> None:
    frame = pd.DataFrame({"id": ["1"], "kwh": ["1"], "extra": ["x"]}, dtype="string")
    out, drift = c.check_file(frame, CON, "fixture.csv")
    assert drift.outcome == "warn" and ("extra", "warn", "unknown_column") in _codes(drift)
    assert ("note", "info", "missing_optional") in _codes(drift)
    assert "extra" in out.columns


def test_missing_required_column_quarantines() -> None:
    frame = pd.DataFrame({"id": ["1"]}, dtype="string")
    _, drift = c.check_file(frame, CON, "fixture.csv")
    assert drift.outcome == "quarantine" and drift.reason_codes == ["missing_required"]


def test_retyped_required_column_quarantines_but_optional_only_warns() -> None:
    frame = pd.DataFrame({"id": ["a", "b"], "kwh": ["1", "2"]}, dtype="string")
    _, drift = c.check_file(frame, CON, "fixture.csv")
    assert drift.outcome == "quarantine" and ("id", "quarantine", "retyped_required") in _codes(
        drift
    )
    fam2 = c.FamilyContract(
        "g",
        "fixture",
        (c.ColumnSpec("id", "integer"), c.ColumnSpec("kwh", "decimal", required=False)),
    )
    _, drift2 = c.check_file(
        pd.DataFrame({"id": ["1"], "kwh": ["x"]}, dtype="string"),
        c.SourceContract("s", (fam2,)),
        "fixture.csv",
    )
    assert drift2.outcome == "warn" and ("kwh", "warn", "retyped_optional") in _codes(drift2)


def test_integer_values_satisfy_a_decimal_declaration_and_text_accepts_anything() -> None:
    frame = pd.DataFrame({"id": ["1"], "kwh": ["3"], "note": ["2020-01-01"]}, dtype="string")
    _, drift = c.check_file(frame, CON, "fixture.csv")
    assert drift.outcome == "ok"


def test_alias_renames_and_records_and_a_double_presence_warns() -> None:
    frame = pd.DataFrame({"id": ["1"], "Energy": ["2.5"]}, dtype="string")
    out, drift = c.check_file(frame, CON, "fixture.csv")
    assert "kwh" in out.columns and "Energy" not in out.columns
    assert ("Energy", "info", "aliased") in _codes(drift) and drift.outcome in ("ok", "info")
    both = pd.DataFrame({"id": ["1"], "Energy": ["2.5"], "kwh": ["2.5"]}, dtype="string")
    out2, drift2 = c.check_file(both, CON, "fixture.csv")
    assert ("Energy", "warn", "alias_target_present") in _codes(drift2) and "Energy" in out2.columns


def test_null_tokens_do_not_break_typing_and_all_null_is_info() -> None:
    frame = pd.DataFrame({"id": ["NA", "NA"], "kwh": ["1", "2"]}, dtype="string")
    _, drift = c.check_file(frame, CON, "fixture.csv")
    assert ("id", "info", "all_null") in _codes(drift) and drift.outcome == "info"


def test_unknown_family_quarantines() -> None:
    _, drift = c.check_file(pd.DataFrame({"id": ["1"]}, dtype="string"), CON, "something-else.csv")
    assert drift.outcome == "quarantine" and drift.reason_codes == ["unknown_family"]


def test_drift_artifact_summarises_outcomes() -> None:
    _, ok = c.check_file(
        pd.DataFrame({"id": ["1"], "kwh": ["1"], "note": ["x"]}, dtype="string"),
        CON,
        "fixture-a.csv",
    )
    _, bad = c.check_file(pd.DataFrame({"id": ["1"]}, dtype="string"), CON, "fixture-b.csv")
    art = c.drift_artifact("ingest-x", "abc", [ok, bad])
    assert art["summary"]["by_outcome"] == {"ok": 1, "info": 0, "warn": 0, "quarantine": 1}
    assert art["summary"]["quarantined_files"] == ["s/fixture-b.csv"]
    assert art["files"][1]["reason_codes"] == ["missing_required"] and "policy" in art


def test_real_contracts_cover_every_configured_source_and_declare_no_user_columns() -> None:
    from ev_charging_data_unified_schema.config import PROJECT

    assert set(c.CONTRACTS) == set(PROJECT.source_names)
    for con in c.CONTRACTS.values():
        assert con.user_level_columns == ()
        for fam in con.families:
            assert fam.required_names(), fam.family
