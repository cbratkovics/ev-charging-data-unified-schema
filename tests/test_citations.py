"""The number checker's branches on a temporary document and artifact (ADR-0013 item 4)."""

from __future__ import annotations

import json
from pathlib import Path

from ev_charging_data_unified_schema import citations as c


def _repo(tmp_path: Path) -> Path:
    art = tmp_path / "artifacts" / "silver"
    art.mkdir(parents=True)
    (art / "silver-x.json").write_text(
        json.dumps(
            {
                "by_source": {
                    "boulder": {
                        "accepted": 77826,
                        "ratio": 0.1136,
                        "list": [1, 2, {"n": 5463}],
                        "q": {"0.999": 31.988},
                    }
                }
            }
        )
    )
    (art / "latest.json").write_text(json.dumps({"run_id": "silver-x", "path": "silver-x.json"}))
    return tmp_path


def _check(tmp_path: Path, text: str, *, adr: bool = False):
    p = tmp_path / ("docs/adr/0001.md" if adr else "README.md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return c.check_document(p, tmp_path, allow_scratch=adr)


def test_resolve_walks_latest_and_dotted_keys(tmp_path) -> None:
    root = _repo(tmp_path)
    assert c.resolve("artifacts/silver/latest.json", "by_source.boulder.accepted", root) == 77826
    assert c.resolve("artifacts/silver/silver-x.json", "by_source.boulder.list[2].n", root) == 5463
    assert (
        c.resolve("artifacts/silver/silver-x.json", 'by_source.boulder.q["0.999"]', root) == 31.988
    )


def test_cited_matching_number_passes_and_percent_is_compared_to_a_ratio(tmp_path) -> None:
    root = _repo(tmp_path)
    text = "Boulder keeps 77,826 rows. <!-- cite: artifacts/silver/latest.json#by_source.boulder.accepted -->\n\nUtilization is 11.4%. <!-- cite: artifacts/silver/latest.json#by_source.boulder.ratio -->\n"
    problems, checked, scratch, params = _check(root, text)
    assert problems == [] and checked == 2 and scratch == 0 and params == 0


def test_uncited_measured_number_fails_but_small_integers_years_and_adr_ids_pass(tmp_path) -> None:
    root = _repo(tmp_path)
    text = "There are 77,826 rows.\n\nSee ADR-0005, Phase 4, item 3 and the year 2023; N = 5; three sources.\n"
    problems, checked, _, _ = _check(root, text)
    assert len(problems) == 1 and "uncited number 77,826" in problems[0]


def test_mismatch_and_dangling_citation_fail(tmp_path) -> None:
    root = _repo(tmp_path)
    text = "Boulder keeps 77,000 rows. <!-- cite: artifacts/silver/latest.json#by_source.boulder.accepted -->\n\nMore 5,463 rows. <!-- cite: artifacts/silver/latest.json#by_source.boulder.missing -->\n"
    problems, _, _, _ = _check(root, text)
    assert any("does not match" in p for p in problems) and any(
        "dangling citation" in p for p in problems
    )


def test_generated_blocks_and_code_fences_are_skipped(tmp_path) -> None:
    root = _repo(tmp_path)
    text = "<!-- generated:results start -->\n| 77,826 | 12.5% |\n<!-- generated:results end -->\n\n```\n99,999 rows\n```\n"
    problems, checked, _, _ = _check(root, text)
    assert problems == [] and checked == 0


def test_scratch_marker_only_in_adrs(tmp_path) -> None:
    root = _repo(tmp_path)
    text = "The first build quarantined 10,627 rows. <!-- scratch -->\n"
    problems, checked, scratch, _ = _check(root, text, adr=True)
    assert problems == [] and checked == 0 and scratch == 1
    problems, _, _, _ = _check(root, text, adr=False)
    assert any("scratch marker" in p for p in problems)


def test_unit_words_make_small_numbers_measured(tmp_path) -> None:
    root = _repo(tmp_path)
    problems, checked, _, _ = _check(root, "It kept 45 rows.\n")
    assert checked == 1 and problems


def test_param_marker_allows_design_constants_everywhere(tmp_path) -> None:
    root = _repo(tmp_path)
    problems, checked, _, params = _check(
        root, "A DST day has 1,380 or 1,500 minutes; the threshold is 30 days. <!-- param -->\n"
    )
    assert problems == [] and checked == 0 and params == 1
