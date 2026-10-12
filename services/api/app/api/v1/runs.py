"""Run launch, status, results, traces, metrics, reports."""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (current_user, owned_connection, owned_project, owned_run,
                          writable_project)
from app.api.v1.projects import connector_for
from app.core.errors import BadRequest
from app.db.session import get_db
from app.engines.pulse import metrics as pulse
from app.evaluation import runner as run_engine
from app.evaluation import gate
from app.evaluation.comparison import compare_runs, non_passing_case_ids
from app.reporting.exporter import _mask as mask, _seeded_literals as seeded_literals
from app.models import InferenceTrace, ModelConnection, ReportExport, RunCase, TestRun, TestSuite, User
from app.reporting.exporter import build_csv, build_report
from app.schemas.api import (
    PaginatedRunCases, RunCaseOut, RunCreate, RunCreateResponse, RunOut, TraceOut,
)

router = APIRouter(tags=["runs"])


def _run_out(run: TestRun) -> RunOut:
    out = RunOut.model_validate(run)
    out.pass_rate = run_engine.pass_rate(run.passed_count, run.failed_count)
    return out


@router.post("/runs", response_model=RunCreateResponse, status_code=202)
def create_run(
    body: RunCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RunCreateResponse:
    """Persist the run, return its id immediately, then execute in background.

    Durability is limited by design (see runner docstring): execution is an
    in-process background task, not a durable queue.
    """
    writable_project(body.project_id, db, user)
    conn = owned_connection(body.connection_id, db, user)
    if conn.project_id != body.project_id:
        raise BadRequest("Connection does not belong to that project.")

    suites = list(db.scalars(
        select(TestSuite).where(
            TestSuite.id.in_(body.suite_ids), TestSuite.project_id == body.project_id
        )
    ).all())
    found = {s.id for s in suites}
    missing = [str(s) for s in body.suite_ids if s not in found]
    if missing:
        raise BadRequest("One or more suites not found in this project.", missing_suite_ids=missing)

    try:
        run = run_engine.create_run(
            db, project_id=body.project_id, connection=conn,
            suites=suites, max_concurrency=body.max_concurrency,
        )
    except ValueError as exc:
        raise BadRequest(str(exc))

    connector = connector_for(conn)
    background.add_task(run_engine.execute_run, run.id, connector)
    return RunCreateResponse(run_id=run.id, status=run.status, total_cases=run.total_cases)


@router.get("/runs/{run_id}/compare")
def compare_run(
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Case-by-case diff of this run against an earlier one.

    Answers "did my fix work, and did I break anything else" -- regression
    testing, and the evidence behind a release decision.

    Two distinctions are preserved rather than flattened into a single number:
    a case where either side errored is `inconclusive`, never a regression,
    because an error is a service problem and not a failed test; and a flip
    measured from one generation on each side is marked `low_confidence`,
    because generation is sampled and that may be variance.
    """
    current = owned_run(run_id, db, user)
    baseline = owned_run(baseline_run_id, db, user)
    if baseline.id == current.id:
        raise BadRequest("Cannot compare a run with itself.")
    if baseline.project_id != current.project_id:
        raise BadRequest("Both runs must belong to the same project.")
    return compare_runs(db, baseline=baseline, current=current)


@router.post("/runs/{run_id}/retest", response_model=RunCreateResponse, status_code=202)
def retest_run(
    run_id: uuid.UUID,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> RunCreateResponse:
    """Re-run only the cases that did not pass, using the CURRENT definitions.

    This is the verification half of a fix: change the application prompt or a
    case, retest, and compare. Errored cases are included because an error
    means the case was never scored and still needs an answer.

    The new run reads cases and the project's application profile live -- a
    retest that replayed the old snapshots would prove nothing about the fix.
    """
    source = owned_run(run_id, db, user)
    conn = owned_connection(source.connection_id, db, user)

    case_ids = non_passing_case_ids(db, source)
    if not case_ids:
        raise BadRequest(
            "Every case in that run passed; there is nothing to retest.",
            run_id=str(source.id),
        )

    suites = list(db.scalars(
        select(TestSuite).where(
            TestSuite.id.in_([uuid.UUID(s) for s in source.suite_ids]),
            TestSuite.project_id == source.project_id,
        )
    ).all())
    if not suites:
        raise BadRequest("The suites from that run no longer exist in this project.")

    try:
        run = run_engine.create_run(
            db, project_id=source.project_id, connection=conn, suites=suites,
            max_concurrency=source.max_concurrency, only_case_ids=case_ids,
        )
    except ValueError as exc:
        raise BadRequest(str(exc))

    connector = connector_for(conn)
    background.add_task(run_engine.execute_run, run.id, connector)
    return RunCreateResponse(run_id=run.id, status=run.status, total_cases=run.total_cases)


@router.get("/runs/{run_id}/gate")
def run_gate(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Go / no-go for this run against the project's declared thresholds.

    With no thresholds configured the verdict is `not_configured` rather than a
    quiet pass, and a run with no scored evidence is `inconclusive`. The
    thresholds applied are returned alongside the decision, so this doubles as
    the approval record for an archived release.
    """
    run = owned_run(run_id, db, user)
    project = owned_project(run.project_id, db, user)
    return gate.evaluate(db, run=run, project=project)


@router.get("/runs/{run_id}/findings")
def run_findings(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Shield findings for this run, with severity, rationale and mitigation.

    Seeded Shield literals are redacted with the same masking the exporter
    uses: a findings view that printed the planted secret would publish the
    string the test exists to detect.
    """
    run = owned_run(run_id, db, user)
    rows = db.scalars(
        select(RunCase).where(RunCase.run_id == run.id).order_by(RunCase.created_at)
    ).all()
    out: list[dict] = []
    by_severity: dict[str, int] = {}
    for rc in rows:
        if not rc.findings:
            continue
        seeds = seeded_literals(rc.case_snapshot or {})
        for f in rc.findings:
            sev = (f.severity or "unspecified").lower()
            by_severity[sev] = by_severity.get(sev, 0) + 1
            out.append({
                "run_case_id": str(rc.id),
                "case": (rc.case_snapshot or {}).get("name"),
                "engine": (rc.case_snapshot or {}).get("engine"),
                "state": rc.state,
                "category": f.category,
                "severity": f.severity,
                "rule_id": f.rule_id,
                "evidence": mask(f.evidence, seeds),
                "mitigation": f.mitigation,
                "severity_rationale": f.severity_rationale,
            })
    return {
        "run_id": str(run.id),
        "total": len(out),
        "by_severity": by_severity,
        "findings": out,
        "note": (
            "A finding is a reproducible test outcome against a pre-declared "
            "rule, not a proof of exploitability in production. Seeded secret "
            "literals are redacted."
        ),
    }


@router.get("/metrics/languages")
def metrics_languages(
    project_id: uuid.UUID = Query(...),
    run_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Quality and latency per language.

    The differentiator in the product blueprint: a Nigerian-language
    application can degrade in one language while the aggregate looks healthy.
    Computed from persisted run cases and traces; no synthetic data.
    """
    owned_project(project_id, db, user)
    if run_id is not None:
        owned_run(run_id, db, user)
    return pulse.by_language(db, project_id=project_id, run_id=run_id)


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RunOut]:
    owned_project(project_id, db, user)
    rows = db.scalars(
        select(TestRun).where(TestRun.project_id == project_id)
        .order_by(TestRun.created_at.desc()).limit(100)
    ).all()
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> RunOut:
    return _run_out(owned_run(run_id, db, user))


@router.get("/runs/{run_id}/results", response_model=PaginatedRunCases)
def run_results(
    run_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    state: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaginatedRunCases:
    run = owned_run(run_id, db, user)
    q = select(RunCase).where(RunCase.run_id == run.id)
    if state:
        q = q.where(RunCase.state == state)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(q.order_by(RunCase.created_at).limit(limit).offset(offset)).all())

    traces: dict[uuid.UUID, list[InferenceTrace]] = {}
    if rows:
        for t in db.scalars(
            select(InferenceTrace).where(InferenceTrace.run_case_id.in_([r.id for r in rows]))
        ).all():
            traces.setdefault(t.run_case_id, []).append(t)

    items = []
    for rc in rows:
        snap = rc.case_snapshot or {}
        items.append(RunCaseOut(
            run_case_id=rc.id, name=snap.get("name"), engine=snap.get("engine"),
            category=snap.get("category"), severity=snap.get("severity"),
            state=rc.state, passed=rc.passed, explanation=rc.explanation,
            error=rc.error, error_kind=rc.error_kind,
            score_metadata=rc.score_metadata or {}, case_snapshot=snap,
            traces=[
                TraceOut(
                    trace_id=t.id, attempt=t.attempt, outcome=t.outcome,
                    upstream_status=t.upstream_status, latency_ms=t.latency_ms,
                    model_id=t.model_id, response_text=t.response_text,
                    error_message=t.error_message, recorded_at=t.created_at,
                )
                for t in sorted(traces.get(rc.id, []), key=lambda x: x.attempt)
            ],
        ))
    return PaginatedRunCases(run_id=run.id, total=total, limit=limit, offset=offset, items=items)


@router.get("/traces")
def list_traces(
    project_id: uuid.UUID = Query(...),
    run_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    owned_project(project_id, db, user)
    if run_id is not None:
        owned_run(run_id, db, user)
    return pulse.recent_traces(db, project_id=project_id, run_id=run_id, limit=limit, offset=offset)


@router.get("/metrics/summary")
def metrics_summary(
    project_id: uuid.UUID = Query(...),
    run_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    owned_project(project_id, db, user)
    if run_id is not None:
        owned_run(run_id, db, user)
    return pulse.summary(db, project_id=project_id, run_id=run_id)


@router.get("/reports/{run_id}")
def report(
    run_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> dict:
    return build_report(db, owned_run(run_id, db, user))


@router.get("/reports/{run_id}/export")
def export_report(
    run_id: uuid.UUID,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    run = owned_run(run_id, db, user)
    data = build_report(db, run)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    db.add(ReportExport(
        run_id=run.id, kind=format,
        generation_metadata={"generated_at": stamp, "case_count": len(data["cases"])},
    ))
    db.commit()
    name = f"atlas-prism-run-{run.id}-{stamp}.{format}"
    if format == "csv":
        return Response(
            content=build_csv(data).encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    import json

    return Response(
        content=json.dumps(data, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
