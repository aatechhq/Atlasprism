"""Run orchestration.

Order of operations is deliberate and load-bearing:

  1. Persist the run (status=queued) and every run_case with an immutable
     snapshot, inside one transaction, BEFORE any inference happens.
  2. Return the run id to the caller immediately.
  3. Execute with bounded concurrency, writing a trace per attempt.

Durability limit, stated plainly: execution uses a FastAPI background task in
the same process. If the process restarts mid-run, that run is left in
`running` with no worker. `recover_interrupted_runs()` is called at startup and
marks such runs `failed` with an explicit reason. This is NOT a durable queue
and is not described as one.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import InferenceResult, ModelConnector, Outcome
from app.core.config import settings
from app.db.session import SessionLocal
from app.evaluation.scoring import (
    SCORING_VERSION, UnknownEvaluator, consistency, score,
)
from app.models import (InferenceTrace, ModelConnection, Project, RunCase, SecurityFinding,
                        TestCase, TestRun, TestSuite)

TERMINAL_RUN_STATES = {"completed", "partially_completed", "failed", "cancelled"}
CONSISTENCY_EVALUATOR = "consistency"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def snapshot_case(
    case: TestCase, suite: TestSuite, app_system_prompt: str | None = None
) -> dict[str, Any]:
    """Immutable copy of the case as launched. Never contains a credential.

    `app_system_prompt` is the project's application profile at launch time.
    It is captured here, not read live, so editing the profile afterwards
    cannot change what a historical run reports.
    """
    return {
        "test_case_id": str(case.id),
        "app_system_prompt": app_system_prompt or None,
        "name": case.name,
        "suite_id": str(suite.id),
        "suite_name": suite.name,
        "suite_version": suite.version,
        "engine": suite.engine,
        "system_prompt": case.system_prompt,
        "user_prompt": case.user_prompt,
        "language": case.language,
        "category": case.category,
        "evaluator_type": case.evaluator_type,
        "evaluator_config": case.evaluator_config,
        "severity": case.severity,
        "severity_rationale": case.severity_rationale,
        "repeat_count": case.repeat_count,
        "case_version": case.version,
        "scoring_version": SCORING_VERSION,
        "snapshot_taken_at": _utcnow().isoformat(),
    }


def create_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    connection: ModelConnection,
    suites: list[TestSuite],
    max_concurrency: int | None = None,
    only_case_ids: list[uuid.UUID] | None = None,
) -> TestRun:
    """Persist run + cases first. Nothing is executed here.

    `only_case_ids` narrows the run to a subset -- used by retest, to re-run
    just the cases that did not pass. The cases are read LIVE, not from the
    previous run's snapshots, because the whole point of a retest is to
    exercise the current definitions and the current application profile.
    """
    concurrency = max(1, min(int(max_concurrency or settings.run_max_concurrency),
                             settings.run_max_concurrency))
    wanted = set(only_case_ids) if only_case_ids else None
    cases: list[tuple[TestCase, TestSuite]] = []
    for suite in suites:
        for case in sorted(suite.cases, key=lambda c: c.name):
            if wanted is not None and case.id not in wanted:
                continue
            cases.append((case, suite))

    if not cases:
        raise ValueError(
            "Cannot start a run with zero test cases."
            if wanted is None else
            "None of the cases to retest still exist in the selected suites."
        )
    if len(cases) > settings.run_max_cases:
        raise ValueError(
            f"Run would execute {len(cases)} cases, above RUN_MAX_CASES="
            f"{settings.run_max_cases}. Reduce the suite selection."
        )

    run = TestRun(
        project_id=project_id,
        connection_id=connection.id,
        status="queued",
        suite_ids=[str(s.id) for s in suites],
        suite_snapshot={
            "suites": [
                {"id": str(s.id), "name": s.name, "engine": s.engine, "version": s.version,
                 "case_count": len(s.cases)}
                for s in suites
            ]
        },
        scoring_version=SCORING_VERSION,
        model_id=connection.model_id,
        max_concurrency=concurrency,
        total_cases=len(cases),
    )
    db.add(run)
    db.flush()

    # The application profile is read once, here, and frozen into every case
    # snapshot alongside the test itself.
    project = db.get(Project, project_id)
    app_prompt = (project.app_system_prompt or "").strip() or None if project else None

    for case, suite in cases:
        db.add(RunCase(
            run_id=run.id,
            test_case_id=case.id,
            case_snapshot=snapshot_case(case, suite, app_prompt),
            state="queued",
        ))
    db.commit()
    db.refresh(run)
    return run


def _record_trace(
    db: Session, *, run_case: RunCase, project_id: uuid.UUID, attempt: int,
    result: InferenceResult, endpoint: str | None, store_response: bool = True,
) -> None:
    db.add(InferenceTrace(
        run_case_id=run_case.id,
        project_id=project_id,
        attempt=attempt,
        model_id=result.model_id,
        endpoint=endpoint,
        request_metadata=result.request_metadata or {},
        response_metadata=result.response_metadata or {},
        # Response text is evidence; it is stored because judges must be able to
        # see what the model actually said. It is model output, never a secret
        # we hold - seeded test secrets are fake by construction.
        response_text=(result.text if store_response else None),
        latency_ms=result.latency_ms,
        upstream_status=result.upstream_status,
        outcome=result.outcome.value,
        error_message=result.error_message,
    ))


async def _execute_case(
    run_case_id: uuid.UUID, project_id: uuid.UUID, connector: ModelConnector,
    endpoint: str | None, semaphore: asyncio.Semaphore,
) -> str:
    """Execute one case in its own session. Returns the terminal state."""
    async with semaphore:
        db = SessionLocal()
        try:
            run_case = db.get(RunCase, run_case_id)
            if run_case is None:
                return "error"
            snap = run_case.case_snapshot
            run_case.state = "running"
            db.commit()

            messages: list[dict[str, str]] = []
            # The application's own instructions go FIRST, so a Shield case has
            # real rules to try to override and a Guard case measures adherence
            # to the developer's requirements. The case's own system prompt is
            # layered after it and can add specifics.
            if snap.get("app_system_prompt"):
                messages.append({"role": "system", "content": snap["app_system_prompt"]})
            if snap.get("system_prompt"):
                messages.append({"role": "system", "content": snap["system_prompt"]})
            messages.append({"role": "user", "content": snap["user_prompt"]})
            language = snap.get("language") or "en"

            repeats = max(1, min(int(snap.get("repeat_count") or 1), settings.run_max_repeats))
            successes: list[InferenceResult] = []
            failures: list[InferenceResult] = []

            for attempt in range(1, repeats + 1):
                result = await connector.generate(messages, language=language)
                _record_trace(db, run_case=run_case, project_id=project_id,
                              attempt=attempt, result=result, endpoint=endpoint)
                (successes if result.ok else failures).append(result)

            # --- no scorable attempt -> ERROR, never a failed test ----------
            if not successes:
                worst = failures[0]
                run_case.state = "error"
                run_case.passed = None
                run_case.error_kind = worst.outcome.value
                run_case.error = (
                    f"No scorable response after {repeats} attempt(s). "
                    f"Last outcome: {worst.outcome.value} - {worst.error_message}"
                )
                run_case.explanation = (
                    "Not scored: the inference attempt(s) did not produce a response. "
                    "An infrastructure or credential error is recorded as an error, "
                    "never as a failed quality test or a successful defense."
                )
                run_case.score_metadata = {
                    "attempts": repeats,
                    "successful_attempts": 0,
                    "outcomes": [f.outcome.value for f in failures],
                }
                run_case.completed_at = _utcnow()
                db.commit()
                return "error"

            evaluator = snap.get("evaluator_type") or ""
            texts = [r.text or "" for r in successes]
            try:
                if evaluator == CONSISTENCY_EVALUATOR:
                    outcome = consistency(texts, snap.get("evaluator_config") or {})
                else:
                    outcome = score(evaluator, texts[0], snap.get("evaluator_config") or {})
            except (UnknownEvaluator, ValueError) as exc:
                run_case.state = "error"
                run_case.passed = None
                run_case.error_kind = "evaluator_config"
                run_case.error = f"Scorer could not run: {exc}"
                run_case.explanation = "Not scored: the case's evaluator configuration is invalid."
                run_case.completed_at = _utcnow()
                db.commit()
                return "error"

            run_case.state = "passed" if outcome.passed else "failed"
            run_case.passed = outcome.passed
            run_case.explanation = outcome.explanation
            run_case.score_metadata = {
                **outcome.metadata,
                "rule": outcome.rule,
                "scoring_version": SCORING_VERSION,
                "attempts": repeats,
                "successful_attempts": len(successes),
                "errored_attempts": len(failures),
                "errored_outcomes": [f.outcome.value for f in failures],
                "latency_ms_per_attempt": [r.latency_ms for r in successes],
            }
            run_case.completed_at = _utcnow()

            # A Shield failure is a finding, tied to the exact rule and case.
            if snap.get("engine") == "shield" and not outcome.passed:
                db.add(SecurityFinding(
                    run_case_id=run_case.id,
                    category=snap.get("category") or "unspecified",
                    severity=snap.get("severity") or "unrated",
                    rule_id=outcome.rule,
                    evidence=(
                        f"Case {snap.get('name')!r}: {outcome.explanation} "
                        f"(attack text recorded in the case snapshot; model response "
                        f"recorded in the inference trace)."
                    ),
                    mitigation=(
                        "Review the system prompt's instruction hierarchy and add an "
                        "explicit refusal policy for this category. This is a test "
                        "outcome, not a security guarantee."
                    ),
                    severity_rationale=snap.get("severity_rationale"),
                ))
            db.commit()
            return run_case.state
        except Exception as exc:  # defensive: never leave a case 'running'
            db.rollback()
            rc = db.get(RunCase, run_case_id)
            if rc is not None and rc.state in ("queued", "running"):
                rc.state = "error"
                rc.passed = None
                rc.error_kind = "internal"
                rc.error = f"{type(exc).__name__}: {exc}"
                rc.completed_at = _utcnow()
                db.commit()
            return "error"
        finally:
            db.close()


async def execute_run(run_id: uuid.UUID, connector: ModelConnector) -> None:
    """Execute a persisted run with bounded concurrency."""
    db = SessionLocal()
    try:
        run = db.get(TestRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATES:
            return
        run.status = "running"
        run.started_at = _utcnow()
        db.commit()
        project_id = run.project_id
        concurrency = run.max_concurrency
        conn = db.get(ModelConnection, run.connection_id)
        endpoint = conn.endpoint if conn else None
        case_ids = list(
            db.scalars(select(RunCase.id).where(RunCase.run_id == run_id)).all()
        )
    finally:
        db.close()

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(_execute_case(cid, project_id, connector, endpoint, semaphore) for cid in case_ids),
        return_exceptions=True,
    )

    db = SessionLocal()
    try:
        run = db.get(TestRun, run_id)
        if run is None:
            return
        passed = sum(1 for r in results if r == "passed")
        failed = sum(1 for r in results if r == "failed")
        errored = sum(1 for r in results if r == "error" or isinstance(r, BaseException))
        skipped = sum(1 for r in results if r == "skipped")
        run.passed_count, run.failed_count = passed, failed
        run.error_count, run.skipped_count = errored, skipped
        run.completed_at = _utcnow()
        if errored == 0:
            run.status = "completed"
        elif passed + failed > 0:
            run.status = "partially_completed"
            run.error_summary = (
                f"{errored} of {len(results)} case(s) could not be scored "
                "(infrastructure, credential or configuration errors). These are "
                "excluded from the pass-rate denominator."
            )
        else:
            run.status = "failed"
            run.error_summary = (
                f"No case produced a scorable response ({errored} errored). "
                "Check the model connection: this is not a quality result."
            )
        db.commit()
    finally:
        db.close()


def recover_interrupted_runs() -> int:
    """Mark runs orphaned by a process restart as failed. Called at startup."""
    db = SessionLocal()
    try:
        stale = list(db.scalars(select(TestRun).where(TestRun.status.in_(["queued", "running"]))).all())
        for run in stale:
            run.status = "failed"
            run.completed_at = _utcnow()
            run.error_summary = (
                "Interrupted: the API process restarted while this run was in "
                f"'{run.status}'. Execution uses in-process background tasks, not a "
                "durable queue, so the run cannot be resumed. Re-launch it."
            )
            for rc in run.cases:
                if rc.state in ("queued", "running"):
                    rc.state = "error"
                    rc.passed = None
                    rc.error_kind = "interrupted"
                    rc.error = "Interrupted by API process restart; never executed or not completed."
                    rc.completed_at = _utcnow()
            run.error_count = sum(1 for rc in run.cases if rc.state == "error")
        db.commit()
        return len(stale)
    finally:
        db.close()


def pass_rate(passed: int, failed: int) -> float | None:
    """passed / (passed + failed). Errors are NOT in the denominator."""
    scored = passed + failed
    return None if scored == 0 else round(passed / scored, 4)
