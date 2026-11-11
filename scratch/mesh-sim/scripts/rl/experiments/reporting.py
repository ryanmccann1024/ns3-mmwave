"""Batch reporting: scenario indexes, reviews, accepted training curves and summaries.

The sole writer of shared report destinations in a plan version 3 batch root.
It reads accepted task attempts (``accepted`` maps a task id to the attempt the
scheduler accepted) and never writes into, moves or relocates them.

- ``curves`` -- accepted training history per train task under
  ``analysis/<scenario>/curves/<key>/attempt-A/<row>/train-seed-<S>/``. History
  follows ``resume.parent`` links inside the root, excludes post-checkpoint
  tails and keeps complete-episode counting (status ``completed`` with exactly
  the row's decisions per episode). ``training_curve_sources.json`` keeps its
  version 1 payload; it has no completion-status field.
- ``review`` -- ``mission_review.json`` version 1 from
  ``episode_review.scene_review`` over pooled frozen deterministic views, plus
  the other accepted operation/baseline episodes in the same ``episodes`` map.
- ``index`` -- the atomic ``main/<scenario>/`` projection:
  ``mission_scenario.json`` version 4 with explicit relative references, a copy
  of the accepted review, optional ``phase_comparison.json`` version 1 history
  imports, hashed scenario assets and the reward summaries.
- :func:`build_comparison_view` -- verified per-model evaluation views for
  ``scripts.rl.compare --eval-dirs``.

Paths written to indexes are relative to the batch root and never escape it.
Metric formulas, windows and missing-value rules belong to
``policy.mission_metrics`` / ``policy.episode_review``; a missing value stays
``None``.
"""

from scripts.rl.experiments.report_artifacts import (
    _Batch,
    _new_attempt,
    _split_task,
)
from scripts.rl.experiments.report_artifacts import (
    check_relative as check_relative,
)
from scripts.rl.experiments.report_comparison import (
    VIEW_DIR as VIEW_DIR,
)
from scripts.rl.experiments.report_comparison import (
    VIEW_SOURCES as VIEW_SOURCES,
)
from scripts.rl.experiments.report_comparison import (
    _review,
)
from scripts.rl.experiments.report_comparison import (
    build_comparison_view as build_comparison_view,
)
from scripts.rl.experiments.report_curves import (
    CURVES_CSV as CURVES_CSV,
)
from scripts.rl.experiments.report_curves import (
    TRAINING_CURVE_SOURCES_VERSION as TRAINING_CURVE_SOURCES_VERSION,
)
from scripts.rl.experiments.report_curves import (
    _curves,
)
from scripts.rl.experiments.report_index import (
    MISSION_SCENARIO_VERSION as MISSION_SCENARIO_VERSION,
)
from scripts.rl.experiments.report_index import (
    PHASE_COMPARISON_NAME as PHASE_COMPARISON_NAME,
)
from scripts.rl.experiments.report_index import (
    PHASE_COMPARISON_VERSION as PHASE_COMPARISON_VERSION,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_CSV as REWARD_SUMMARY_CSV,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_FIELDS as REWARD_SUMMARY_FIELDS,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_JSON as REWARD_SUMMARY_JSON,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_METRICS as REWARD_SUMMARY_METRICS,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_NOTE as REWARD_SUMMARY_NOTE,
)
from scripts.rl.experiments.report_index import (
    REWARD_SUMMARY_VERSION as REWARD_SUMMARY_VERSION,
)
from scripts.rl.experiments.report_index import (
    _index,
)
from scripts.rl.experiments.report_index import (
    build_index as build_index,
)
from scripts.rl.experiments.report_index import (
    write_reward_summary as write_reward_summary,
)
from scripts.rl.experiments.report_selection import (
    selection_evidence as selection_evidence,
)

REPORT_HANDLERS = ("curves", "review", "index")


def run_report_task(
    task: dict, plan: dict, root, accepted: dict, *, attempt_dir=None, skipped=()
) -> dict:
    """Run one ``curves``/``review``/``index`` task; returns outputs (relative path -> sha256).

    ``accepted`` maps every completed task id of the batch (not only direct
    dependencies) to its accepted attempt directory; ``skipped`` names tasks in
    ``skipped_selection``. ``curves``/``review`` write a new ``attempt-N`` (or the
    given empty ``attempt_dir``, also accepted as a task field); ``index`` rebuilds
    ``main/<scenario>/``. ``accepted`` values are attempt directories or the
    scheduler's ``{state, attempt_dir}`` records.
    """
    task, attempt_dir = _split_task(task, attempt_dir)
    batch = _Batch(plan, root, accepted, skipped)
    if batch.by_id.get(task.get("id")) != task:
        raise ValueError(f"{task.get('id')} is not a task of this plan")
    handler = task.get("handler")
    if handler not in REPORT_HANDLERS:
        raise ValueError(
            f"{task['id']}: handler {handler!r} is not one of {REPORT_HANDLERS}"
        )
    if handler == "index":
        result = _index(batch, task)
        result["attempt_dir"] = None
    else:
        attempt = _new_attempt(batch, task, attempt_dir)
        result = (_curves if handler == "curves" else _review)(batch, task, attempt)
        result["attempt_dir"] = batch.rel(attempt)
    result["outputs"] = dict(sorted(result["outputs"].items()))
    return result
