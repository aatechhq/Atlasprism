"""Compare two runs: what changed, and what is merely noise.

This answers the question a developer actually has after changing a prompt —
*did my fix work, and did I break anything else?* — which is PRD/blueprint
"Regression testing" and the core of the release-gating workflow.

Two rules this module will not bend:

1. **An error is not a failure.** If either side of a comparison errored, the
   pair is `inconclusive`. A service problem must never be reported as a
   regression, because the developer would go looking for a bug they did not
   write.
2. **A single sample is not a measurement.** Generation is sampled, so a case
   with `repeat_count: 1` can flip between runs with nothing changed. Flips on
   single-sample cases are counted and reported separately as
   `low_confidence`, with the remedy (`repeat_count`) named in the payload.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RunCase, TestRun

# A case pair is only comparable when both sides reached a scored verdict.
_SCORED = {"passed", "failed"}


def _key(rc: RunCase) -> str:
    """Identity of a case across runs.

    `test_case_id` is the real identity, but it is `SET NULL` if the case is
    later deleted, so fall back to the snapshot name. The snapshot is immutable,
    which makes the fallback stable for historical runs.
    """
    if rc.test_case_id:
        return f"id:{rc.test_case_id}"
    return f"name:{(rc.case_snapshot or {}).get('name', rc.id)}"


def _label(rc: RunCase) -> str:
    return (rc.case_snapshot or {}).get("name") or "(unnamed case)"


def _verdict(before: RunCase | None, after: RunCase | None, *, subset: bool) -> str:
    if before is None:
        return "added"
    if after is None:
        # A retest deliberately runs a subset. Those cases were not deleted and
        # saying "removed" would read as deletion, so name what actually
        # happened: they were not part of this run.
        return "not_in_this_run" if subset else "removed"
    if before.state not in _SCORED or after.state not in _SCORED:
        return "inconclusive"
    if before.passed and after.passed:
        return "still_passing"
    if not before.passed and not after.passed:
        return "still_failing"
    return "fixed" if after.passed else "regressed"


def _repeats(rc: RunCase | None) -> int:
    if rc is None:
        return 0
    try:
        return max(1, int((rc.case_snapshot or {}).get("repeat_count") or 1))
    except (TypeError, ValueError):
        return 1


def _pass_rate(run: TestRun) -> float | None:
    scored = run.passed_count + run.failed_count
    return round(run.passed_count / scored, 4) if scored else None


def _run_header(run: TestRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "status": run.status,
        "model_id": run.model_id,
        "scoring_version": run.scoring_version,
        "total_cases": run.total_cases,
        "passed": run.passed_count,
        "failed": run.failed_count,
        "errors": run.error_count,
        "pass_rate": _pass_rate(run),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def compare_runs(db: Session, *, baseline: TestRun, current: TestRun) -> dict[str, Any]:
    """Case-by-case diff of `current` against `baseline`."""
    before = {_key(rc): rc for rc in db.scalars(
        select(RunCase).where(RunCase.run_id == baseline.id)).all()}
    after = {_key(rc): rc for rc in db.scalars(
        select(RunCase).where(RunCase.run_id == current.id)).all()}

    # A retest covers only the cases that did not pass, so `current` is a
    # strict subset of `baseline`. Comparing aggregate rates across different
    # populations is meaningless, and this is how we detect that.
    subset = bool(after) and set(after).issubset(set(before)) and len(after) < len(before)

    cases: list[dict[str, Any]] = []
    summary = {"regressed": 0, "fixed": 0, "still_passing": 0, "still_failing": 0,
               "inconclusive": 0, "added": 0, "removed": 0, "not_in_this_run": 0}
    low_confidence = 0

    for key in sorted(before.keys() | after.keys(),
                      key=lambda k: _label(after.get(k) or before[k]).lower()):
        b, a = before.get(key), after.get(key)
        verdict = _verdict(b, a, subset=subset)
        summary[verdict] += 1
        # A flip measured from one sample on each side may be sampling, not a
        # change in behaviour. Say so per case rather than burying it.
        single_sample = verdict in {"regressed", "fixed"} and _repeats(b) < 2 and _repeats(a) < 2
        if single_sample:
            low_confidence += 1
        cases.append({
            "case": _label(a or b),
            "engine": ((a or b).case_snapshot or {}).get("engine"),
            "severity": ((a or b).case_snapshot or {}).get("severity"),
            "verdict": verdict,
            "low_confidence": single_sample,
            "baseline": None if b is None else {
                "state": b.state, "passed": b.passed, "repeat_count": _repeats(b),
                "explanation": b.explanation, "error_kind": b.error_kind,
            },
            "current": None if a is None else {
                "state": a.state, "passed": a.passed, "repeat_count": _repeats(a),
                "explanation": a.explanation, "error_kind": a.error_kind,
            },
        })

    b_rate, c_rate = _pass_rate(baseline), _pass_rate(current)
    # Comparable only when both runs covered the same cases. A retest's rate is
    # higher almost by construction -- it re-ran only what had failed -- so
    # publishing a delta there would invent an improvement.
    comparable = not subset and summary["added"] == 0 and summary["removed"] == 0
    delta = (None if (b_rate is None or c_rate is None or not comparable)
             else round(c_rate - b_rate, 4))

    return {
        "baseline": _run_header(baseline),
        "current": _run_header(current),
        "is_subset": subset,
        "populations_comparable": comparable,
        "pass_rate_delta": delta,
        "pass_rate_delta_note": (
            None if comparable else
            "Not reported: the two runs did not cover the same cases, so their "
            "pass rates describe different populations. Compare the per-case "
            "verdicts instead."
        ),
        "summary": summary,
        "low_confidence_changes": low_confidence,
        "cases": cases,
        "interpretation": {
            "regressed": "passed in the baseline, did not pass now",
            "not_in_this_run": (
                "present in the baseline but not executed in this run -- a "
                "retest runs only the cases that did not pass. The case was "
                "not deleted."
            ),
            "fixed": "did not pass in the baseline, passes now",
            "inconclusive": (
                "at least one side errored. An error is a service or network "
                "problem, never a failed test, so no regression is claimed."
            ),
            "low_confidence": (
                "a flip measured from a single generation on each side. "
                "Generation is sampled, so this may be variance rather than a "
                "behaviour change. Raise repeat_count to distinguish them."
            ),
            "model_changed": baseline.model_id != current.model_id,
            "scoring_changed": baseline.scoring_version != current.scoring_version,
        },
    }


def non_passing_case_ids(db: Session, run: TestRun) -> list[uuid.UUID]:
    """Test case ids worth retesting: everything that did not pass.

    Includes errored cases — an error means the case was never scored, so it
    still needs an answer. Cases whose definition has since been deleted are
    omitted, because there is nothing left to execute.
    """
    rows = db.scalars(
        select(RunCase).where(RunCase.run_id == run.id, RunCase.state != "passed")
    ).all()
    seen: list[uuid.UUID] = []
    for rc in rows:
        if rc.test_case_id and rc.test_case_id not in seen:
            seen.append(rc.test_case_id)
    return seen
