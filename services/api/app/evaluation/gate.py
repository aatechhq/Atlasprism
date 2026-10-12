"""Release gating: turn a run into a go / no-go against declared thresholds.

Blueprint section 7, workflow 5 -- "run Guard and Shield suites, check failure
thresholds, review changes against baseline, approve or block deployment,
archive evidence". This module is the "check failure thresholds" step.

The thresholds belong to the project, are declared before the run, and are
recorded in the verdict, so an approval record says what standard was applied
rather than only whether it was met.

What this module will not do:

* It will not invent a threshold. With none configured the verdict is
  `not_configured` -- never a quiet pass.
* It will not gate on a run that did not finish, or whose cases all errored.
  There is no evidence to gate on, so the verdict is `inconclusive`.
* It will not treat errors as failures. They are excluded from the pass rate,
  and reported separately so a reader can see the evidence was incomplete.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, RunCase, SecurityFinding, TestRun

_TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}


def _severity_counts(db: Session, run: TestRun) -> dict[str, int]:
    rows = db.execute(
        select(SecurityFinding.severity, func.count(SecurityFinding.id))
        .join(RunCase, SecurityFinding.run_case_id == RunCase.id)
        .where(RunCase.run_id == run.id)
        .group_by(SecurityFinding.severity)
    ).all()
    return {str(sev or "unspecified").lower(): int(n) for sev, n in rows}


def evaluate(db: Session, *, run: TestRun, project: Project) -> dict[str, Any]:
    """Decide whether this run meets the project's release thresholds."""
    scored = run.passed_count + run.failed_count
    pass_rate = round(run.passed_count / scored, 4) if scored else None
    findings = _severity_counts(db, run)
    critical = findings.get("critical", 0)

    min_rate = project.gate_min_pass_rate
    max_critical = project.gate_max_critical_findings
    configured = min_rate is not None or max_critical is not None

    checks: list[dict[str, Any]] = []
    if min_rate is not None:
        met = pass_rate is not None and pass_rate >= float(min_rate)
        checks.append({
            "check": "minimum_pass_rate",
            "threshold": float(min_rate),
            "observed": pass_rate,
            "met": bool(met),
            "detail": ("no case reached a scored verdict, so the pass rate is undefined"
                       if pass_rate is None else None),
        })
    if max_critical is not None:
        checks.append({
            "check": "maximum_critical_findings",
            "threshold": int(max_critical),
            "observed": critical,
            "met": critical <= int(max_critical),
            "detail": None,
        })

    if not configured:
        verdict = "not_configured"
    elif run.status not in _TERMINAL or scored == 0:
        verdict = "inconclusive"
    elif all(c["met"] for c in checks):
        verdict = "pass"
    else:
        verdict = "block"

    return {
        "run_id": str(run.id),
        "project_id": str(project.id),
        "verdict": verdict,
        "run_status": run.status,
        "checks": checks,
        "observed": {
            "pass_rate": pass_rate,
            "pass_rate_definition": "passed / (passed + failed); errored cases excluded",
            "passed": run.passed_count,
            "failed": run.failed_count,
            "errors": run.error_count,
            "scored_cases": scored,
            "findings_by_severity": findings,
        },
        "limitations": [
            "Thresholds are the project's own declared policy, not an external "
            "standard, and a passing gate is not a guarantee that the "
            "application is safe or accurate.",
            "Errors are excluded from the pass rate. A run with errors has "
            "incomplete evidence even when the gate passes."
            if run.error_count else
            "No inference errors occurred in this run.",
            "Generation is sampled, so a pass rate measured once can move "
            "between runs. Use repeat_count, or compare runs, before treating "
            "a change as real.",
        ],
        "notes": (
            "No thresholds are configured for this project, so no decision was "
            "made. Set gate_min_pass_rate and/or gate_max_critical_findings on "
            "the project to enable gating."
            if verdict == "not_configured" else
            "The run has not produced scored evidence to gate on."
            if verdict == "inconclusive" else None
        ),
    }
