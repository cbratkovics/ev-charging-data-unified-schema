"""API contract tests against the committed artifacts (no network, no database). Skipped until
`make bootstrap` has produced artifacts/manifest.json."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT
from ev_charging_data_unified_schema.serve import app as app_module
from ev_charging_data_unified_schema.serve import marts, schemas

pytestmark = pytest.mark.skipif(
    not (ARTIFACTS_DIR / "manifest.json").exists(),
    reason="no committed manifest; run make bootstrap",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app_module.app) as c:
        yield c


def test_root_and_health(client) -> None:
    assert client.get("/").json()["health"] == "/health"
    body = schemas.Health.model_validate(client.get("/health").json())
    assert body.status == "ok" and sorted(body.cohorts_loaded) == sorted(PROJECT.cohorts)


def test_performance_lists_every_registered_evaluation(client) -> None:
    body = schemas.EvaluationsResponse.model_validate(client.get("/performance").json())
    assert body.evaluations
    for art in body.evaluations:
        assert art["metrics"]["n"] > 0 and set(art["cohorts"]) <= set(PROJECT.cohorts)
        assert client.get(f"/performance/{art['eval_id']}").json()["eval_id"] == art["eval_id"]
    assert client.get("/performance/nope").status_code == 404


def test_predictions_latest_period(client) -> None:
    m = client.get("/manifest").json()["manifest"]
    latest = m.get("predictions", {}).get("latest")
    if not latest:
        pytest.skip("no scored period yet")
    season, period = latest.split("/")[1], int(latest.rsplit("_", 1)[1].split(".")[0])
    body = schemas.PredictionsResponse.model_validate(
        client.get(f"/predictions/{season}/{period}").json()
    )
    assert body.n > 0 and all(p.floor <= p.prediction <= p.ceiling for p in body.predictions)
    assert client.get(f"/predictions/{season}/{period}?cohort=nope").status_code == 422


def test_marts_endpoint(client) -> None:
    r = client.get("/marts/fct_period_eval?cohort=ALL")
    if r.status_code == 404:
        pytest.skip("marts not exported yet")
    body = schemas.MartResponse.model_validate(r.json())
    assert body.n == len(body.rows) and all(row["cohort"] == "ALL" for row in body.rows)
    assert client.get("/marts/fct_period_eval?nope=1").status_code == 422
    assert client.get("/marts/not_a_mart").status_code == 422


def test_versioned_mart_is_read_at_an_explicit_version() -> None:
    assert (
        marts.mart_table("fct_decision_policy", marts.DECISIONS_MART_VERSION)
        == "fct_decision_policy"
    )
    assert marts.mart_table("fct_decision_policy", 2) == "fct_decision_policy_v2"
    with pytest.raises(KeyError):
        marts.mart_table("fct_decision_policy")
