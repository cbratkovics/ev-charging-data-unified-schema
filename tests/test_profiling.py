from __future__ import annotations

import pandas as pd

from ev_charging_data_unified_schema import profiling as pr


def test_infer_type_branches() -> None:
    assert pr.infer_type(pd.Series(["1", "2", None]))[0] == "integer"
    assert pr.infer_type(pd.Series(["1.5", "2", "0"]))[0] == "decimal"
    assert pr.infer_type(pd.Series(["00:12:30", "1:00:00"]))[0] == "duration_hms"
    assert pr.infer_type(pd.Series(["2020-01-01 08:00:00", "2020-01-02T09:00:00Z"])) == (
        "datetime",
        "ISO",
    )
    assert pr.infer_type(pd.Series(["01/02/2020 09:30", "13/02/2020 09:30"]))[0] == "datetime"
    assert pr.infer_type(pd.Series(["2020-01-01"]))[0] == "date"
    assert pr.infer_type(pd.Series(["abc", "1"]))[0] == "text"
    assert pr.infer_type(pd.Series([None, ""]))[0] == "empty"


def test_day_first_evidence_reads_the_data_not_the_locale() -> None:
    dmy = pr.day_first_evidence(pd.Series(["13/02/2020 09:30", "01/02/2020 09:30"]))
    mdy = pr.day_first_evidence(pd.Series(["02/13/2020 09:30", "02/01/2020 09:30"]))
    amb = pr.day_first_evidence(pd.Series(["02/03/2020 09:30"]))
    assert dmy["verdict"] == "day_first" and mdy["verdict"] == "month_first"
    assert amb["verdict"] == "ambiguous"
    assert pr.day_first_evidence(pd.Series(["2020-01-01"])) is None


def test_profile_column_numeric_and_duration_and_datetime() -> None:
    num = pr.profile_column("e", pd.Series(["0", "1.5", "-2", None, ""]))
    assert num["null_or_blank"] == 2 and num["zero_count"] == 1 and num["negative_count"] == 1
    dur = pr.profile_column("d", pd.Series(["00:30:00", "25:00:00"]))
    assert dur["over_24h_count"] == 1 and dur["min_minutes"] == 30.0
    dtc = pr.profile_column("t", pd.Series(["13/02/2020 09:30", "01/02/2020 09:30", "bad"]))
    assert dtc["inferred_type"] == "text"  # 'bad' breaks the 99% rule on three values
    dtc2 = pr.profile_column("t", pd.Series(["13/02/2020 09:30", "01/02/2020 09:30"]))
    assert dtc2["day_first_evidence"]["verdict"] == "day_first"
    assert dtc2["min"].startswith("2020-02-01") and dtc2["parse_failures"] == 0


def test_profile_file_hashes_and_counts_duplicates(tmp_path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,x\n1,x\n2,\n")
    frame = pr.read_raw_strings(p)
    fp = pr.profile_file(p, frame)
    assert fp.rows == 3 and fp.exact_duplicate_rows == 1 and fp.columns == ["a", "b"]
    assert fp.sha256 == pr.sha256_of(p) and len(fp.sha256) == 64
    assert pd.isna(frame.loc[2, "b"]) and frame["a"].dtype == "string"


def test_hms_to_minutes_handles_hours_over_24_and_bad_values() -> None:
    m = pr.hms_to_minutes(pd.Series(["95:06:31", "0:00:25", "bad", None]))
    assert round(m[0], 3) == 5706.517 and round(m[1], 3) == 0.417
    assert pd.isna(m[2]) and pd.isna(m[3])


def test_parse_mixed_us_handles_both_shapes() -> None:
    out, counts = pr.parse_mixed_us(pd.Series(["1/9/2018 11:02", "2023-06-02 08:15:30", "x"]))
    assert counts == {"iso_rows": 1, "slash_rows": 2}
    assert str(out[0]) == "2018-01-09 11:02:00" and str(out[1]) == "2023-06-02 08:15:30"
    assert pd.isna(out[2])


def test_max_concurrency_counts_overlaps_and_ignores_touching_intervals() -> None:
    s = pd.to_datetime(
        ["2020-01-01 08:00", "2020-01-01 08:30", "2020-01-01 09:00", "2020-01-01 10:00"]
    )
    e = pd.to_datetime(
        ["2020-01-01 09:00", "2020-01-01 09:30", "2020-01-01 09:30", "2020-01-01 11:00"]
    )
    by = pd.Series(["A", "A", "A", "B"])
    conc = pr.max_concurrency(pd.Series(s), pd.Series(e), by)
    # 08:30-09:00 has two overlapping; the 09:00 start touches the 09:00 end (end first) -> 2
    assert conc == {"A": 2, "B": 1}


def test_dst_transition_gaps_detects_wall_clock_shift() -> None:
    # a session 00:30 -> 03:30 wall clock on spring-forward day has 3h span but 2h elapsed
    s = pd.Series(pd.to_datetime(["2023-03-12 00:30", "2023-03-12 12:00"]))
    e = pd.Series(pd.to_datetime(["2023-03-12 03:30", "2023-03-12 13:00"]))
    dur = pd.Series([120.0, 60.0])
    out = pr.dst_transition_gaps(s, e, dur, ["2023-03-12"])
    assert out["2023-03-12"] == {"sessions_spanning_window": 1, "gap_minutes_counts": {"60": 1}}
