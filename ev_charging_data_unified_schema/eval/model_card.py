"""Render ``docs/MODEL_CARD.md`` from committed artifacts. Every number is read from
``artifacts/models/<version>/metadata.json`` and the evaluation artifacts listed in
``manifest.evaluations``; the JSON key is printed next to each figure. ``scripts/check_model_card.py``
fails while the shipped placeholder card is still in place."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment

from ev_charging_data_unified_schema.config import ARTIFACTS_DIR, PROJECT, REPO_ROOT
from ev_charging_data_unified_schema.eval import drift
from ev_charging_data_unified_schema.models import registry

TEMPLATE = """# Model card — {{ meta.model_version }}

_Generated {{ generated_at }} from committed artifacts; do not edit by hand. Regenerate with
`python scripts/evaluate.py`._

| Field | Value | Source key |
|---|---|---|
| Model version | `{{ meta.model_version }}` | `models/{{ meta.model_version }}/metadata.json: model_version` |
| Feature version | `{{ meta.feature_version }}` | `metadata.json: feature_version` |
| Champion candidate | {{ champion_summary }} | `metadata.json: cohorts[*].champion` |
| Target | {{ meta.target }} | `metadata.json: target` |
| Data | `{{ meta.data_library }}`, {{ meta.input_rows }} rows, sha256 `{{ meta.input_sha256[:12] }}…` | `metadata.json: data_library, input_rows, input_sha256` |
| Data through (training pull) | {{ season_name }} {{ meta.data_through.season }}, {{ period_name }} {{ meta.data_through.period }} | `metadata.json: data_through` |
| Split | train {{ meta.seasons.train | join(', ') }} · validation {{ meta.seasons.val }} · test {{ meta.seasons.test }} (whole {{ season_name }}s, forward in time) | `metadata.json: seasons` |
| Trained at | {{ meta.trained_at_utc }} | `metadata.json: trained_at_utc` |
| Code commit (training) | `{{ meta.code_commit }}` | `metadata.json: code_commit` |
| Libraries | scikit-learn {{ meta.sklearn_version }} | `metadata.json: sklearn_version` |
| Interval method | {{ meta.interval_method }} | `metadata.json: interval_method` |

## What it predicts

`{{ target }}` ({{ units }}) for the upcoming {{ period_name }} of each {{ entity_name }}, using only that
{{ entity_name }}'s rows from strictly earlier {{ period_name }}s ({{ n_features }} features).

{% for ev in evals -%}
## {{ ev.title }} ({{ season_name }} {{ ev.season }}, champion per {{ cohort_name }})

Kind: `{{ ev.kind }}` — {{ ev.kind_note }}
Metric definitions: {{ ev.metric_definitions.mae }} (`mae`); {{ ev.metric_definitions.within_band1_rate }}
(`within_band1_rate`). Baseline: {{ ev.metric_definitions.baseline }}.
Source: `artifacts/eval/{{ ev.eval_id }}.json` (input `{{ ev.input.path }}`, sha256 `{{ ev.input.sha256[:12] }}…`, evaluation commit `{{ ev.code_commit }}`).

| Cohort | n | MAE | Median AE | RMSE | Within ±{{ band1 }} | Within ±{{ band2 }} | Baseline MAE | Baseline within ±{{ band1 }} |
|---|---|---|---|---|---|---|---|---|
| All | {{ ev.metrics.n }} | {{ ev.metrics.mae }} | {{ ev.metrics.median_ae }} | {{ ev.metrics.rmse }} | {{ pct(ev.metrics.within_band1_rate) }} | {{ pct(ev.metrics.within_band2_rate) }} | {{ ev.baseline.mae }} | {{ pct(ev.baseline.within_band1_rate) }} |
{% for c, m in ev.cohorts.items() -%}
| {{ c }} | {{ m.n }} | {{ m.mae }} | {{ m.median_ae }} | {{ m.rmse }} | {{ pct(m.within_band1_rate) }} | {{ pct(m.within_band2_rate) }} | {{ m.baseline.mae }} | {{ pct(m.baseline.within_band1_rate) }} |
{% endfor %}
Keys: `metrics.*`, `cohorts[c].*`, `baseline.*`, `cohorts[c].baseline.*`.
{% if ev.rolling_origin %}
Rolling origin ({{ ev.rolling_origin.candidate }}; {{ ev.rolling_origin.strategy }}): mean fold MAE
**{{ ev.rolling_origin.mean_mae }}** vs baseline **{{ ev.rolling_origin.mean_baseline_mae }}** over
{{ ev.rolling_origin.folds | length }} folds (`rolling_origin.mean_mae`, `rolling_origin.mean_baseline_mae`).
{% endif %}
{% endfor -%}

## Candidate comparison (validation {{ season_name }} {{ meta.seasons.val }} selects the champion)

| Cohort | Champion | {% for c in candidates %}{{ c }} val MAE | {{ c }} test MAE | {% endfor %}Cohort-mean baseline test MAE |
|---|---|{% for c in candidates %}---|---|{% endfor %}---|
{% for cohort, p in meta.cohorts.items() -%}
| {{ cohort }} | {{ p.champion }} | {% for c in candidates %}{{ '%.3f' | format(p.candidates[c].val_mae) }} | {{ '%.3f' | format(p.candidates[c].test_mae) }} | {% endfor %}{{ '%.3f' | format(p.baseline_cohort_mean.test_mae) }} |
{% endfor %}
Keys: `cohorts[c].candidates[cand].val_mae / test_mae`, `cohorts[c].baseline_cohort_mean.test_mae`.

## Intended use and limitations

* TODO(domain): who should use these predictions and for what decision; who should not.
* Features are the {{ entity_name }}'s own recent history only ({{ meta.feature_version }}); {{ entity_name }}s
  with no prior row get no prediction.
* The 10th/90th residual quantiles give an 80% empirical interval on the validation {{ season_name }},
  not a guarantee.
* Trained on {{ meta.seasons.train | join(', ') }}; drift is monitored every {{ period_name }} with PSI but
  the model is not retrained automatically.
* Drift thresholds: {{ 'calibrated' if drift_calibrated else '**NOT CALIBRATED** (the scheduled job cannot HOLD on drift; see eval/drift.py)' }}.
"""

KIND_TITLES = {
    "frozen_test": "Frozen test-season evaluation",
    "out_of_sample_season": "Out-of-sample season evaluation",
}
KIND_NOTES = {
    "frozen_test": "the season held out when the model was trained and selected.",
    "out_of_sample_season": "a complete season that no training, validation, selection, or tuning decision ever touched; scored with the same frozen artifact and feature builder.",
}


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def render(meta: dict[str, Any], eval_artifacts: list[dict[str, Any]]) -> str:
    env = Environment(autoescape=False, trim_blocks=False, lstrip_blocks=False)
    env.globals["pct"] = _pct
    champions = {c: v["champion"] for c, v in meta["cohorts"].items()}
    champion_summary = (
        f"`{next(iter(champions.values()))}` for every {PROJECT.cohort_name}"
        if len(set(champions.values())) == 1
        else ", ".join(f"{c}: `{v}`" for c, v in champions.items())
    )
    n_features = len({f for c in meta["cohorts"].values() for f in c["features"]})
    evals = []
    for ev in sorted(eval_artifacts, key=lambda e: (e.get("season") or 0, e["eval_id"])):
        kind = ev.get("kind", "frozen_test")
        evals.append(
            {
                **ev,
                "kind": kind,
                "title": KIND_TITLES.get(kind, kind),
                "kind_note": KIND_NOTES.get(kind, ""),
                "season": ev.get("season") or ev["split"]["test_start_season"],
            }
        )
    generated_at = max(e["generated_at_utc"] for e in evals) if evals else ""
    band1, band2 = PROJECT.within_k
    return env.from_string(TEMPLATE).render(
        meta=meta,
        evals=evals,
        champion_summary=champion_summary,
        n_features=n_features,
        generated_at=generated_at,
        season_name=PROJECT.season_name,
        period_name=PROJECT.period_name,
        entity_name=PROJECT.entity_name,
        cohort_name=PROJECT.cohort_name,
        target=PROJECT.target_column,
        units=PROJECT.target_units,
        band1=band1,
        band2=band2,
        candidates=list(meta["candidates"]),
        drift_calibrated=drift.CALIBRATED,
    )


def write_model_card(
    manifest: dict[str, Any],
    *,
    artifacts: Path = ARTIFACTS_DIR,
    out_path: Path = REPO_ROOT / "docs" / "MODEL_CARD.md",
) -> Path:
    model_version, _ = registry.slot(manifest, "champion")
    meta = json.loads(
        (artifacts / "models" / model_version / "metadata.json").read_text(encoding="utf-8")
    )
    evs = [
        json.loads((artifacts / e["path"]).read_text(encoding="utf-8"))
        for e in registry.evaluations(manifest)
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(meta, evs), encoding="utf-8")
    return out_path
