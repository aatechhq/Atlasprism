"""Suites and test cases."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_project, owned_suite, writable_project
from app.core.errors import BadRequest, NotFound
from app.db.session import get_db
from app.evaluation.scoring import SCORERS
from app.models import TestCase, TestSuite, User
from app.schemas.api import (
    SuiteCreate, SuiteDetailOut, SuiteOut, TestCaseCreate, TestCaseOut, TestCaseUpdate,
)

router = APIRouter(tags=["suites"])
VALID_EVALUATORS = set(SCORERS) | {"consistency"}


def _suite_out(suite: TestSuite) -> SuiteOut:
    out = SuiteOut.model_validate(suite)
    out.case_count = len(suite.cases)
    return out


@router.post("/suites", response_model=SuiteOut, status_code=201)
def create_suite(
    body: SuiteCreate, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> SuiteOut:
    writable_project(body.project_id, db, user)
    suite = TestSuite(
        project_id=body.project_id, name=body.name.strip(),
        engine=body.engine, description=body.description,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return _suite_out(suite)


@router.get("/suites", response_model=list[SuiteOut])
def list_suites(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[SuiteOut]:
    owned_project(project_id, db, user)
    rows = db.scalars(
        select(TestSuite).where(TestSuite.project_id == project_id)
        .order_by(TestSuite.engine, TestSuite.name)
    ).all()
    return [_suite_out(s) for s in rows]


@router.get("/suites/{suite_id}", response_model=SuiteDetailOut)
def get_suite(
    suite_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> SuiteDetailOut:
    suite = owned_suite(suite_id, db, user)
    out = SuiteDetailOut.model_validate(suite)
    out.case_count = len(suite.cases)
    out.cases = [TestCaseOut.model_validate(c) for c in sorted(suite.cases, key=lambda c: c.name)]
    return out


def _validate_evaluator(evaluator_type: str, config: dict) -> None:
    if evaluator_type not in VALID_EVALUATORS:
        raise BadRequest(
            f"Unknown evaluator_type {evaluator_type!r}.",
            valid_evaluators=sorted(VALID_EVALUATORS),
        )
    required = {
        "exact_match": ["expected"],
        "json_schema": ["schema"],
        "secret_disclosure": ["seeded_secrets"],
        "forbidden_action": ["forbidden_patterns"],
    }.get(evaluator_type, [])
    missing = [k for k in required if k not in (config or {})]
    if missing:
        raise BadRequest(
            f"evaluator_config for {evaluator_type!r} requires {missing}.",
            required_keys=required,
        )
    if evaluator_type == "forbidden_action":
        import re as _re

        for pattern in (config or {}).get("forbidden_patterns") or []:
            try:
                _re.compile(pattern)
            except _re.error as exc:
                raise BadRequest(
                    f"forbidden_patterns contains an invalid regular expression: {exc}",
                    pattern=pattern,
                )
    if evaluator_type == "keywords" and not (
        (config or {}).get("required") or (config or {}).get("forbidden")
    ):
        raise BadRequest("evaluator_config for 'keywords' needs 'required' or 'forbidden'.")
    if evaluator_type == "refusal_expected" and not (
        (config or {}).get("compliance_markers") or (config or {}).get("refusal_markers")
    ):
        raise BadRequest(
            "evaluator_config for 'refusal_expected' needs 'compliance_markers' "
            "or 'refusal_markers' - a refusal must be detected by an explicit "
            "observable marker, never inferred from tone."
        )


@router.post("/test-cases", response_model=TestCaseOut, status_code=201)
def create_case(
    body: TestCaseCreate, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> TestCase:
    suite = owned_suite(body.suite_id, db, user)
    writable_project(suite.project_id, db, user)
    _validate_evaluator(body.evaluator_type, body.evaluator_config)
    case = TestCase(
        suite_id=suite.id, name=body.name.strip(), system_prompt=body.system_prompt,
        user_prompt=body.user_prompt, language=body.language, category=body.category,
        evaluator_type=body.evaluator_type, evaluator_config=body.evaluator_config,
        severity=body.severity, severity_rationale=body.severity_rationale,
        repeat_count=body.repeat_count, version=1,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.patch("/test-cases/{case_id}", response_model=TestCaseOut)
def update_case(
    case_id: uuid.UUID, body: TestCaseUpdate,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> TestCase:
    case = db.get(TestCase, case_id)
    if case is None:
        raise NotFound("Test case not found.")
    suite = owned_suite(case.suite_id, db, user)
    writable_project(suite.project_id, db, user)

    data = body.model_dump(exclude_unset=True)
    if not data:
        raise BadRequest("No fields supplied.")
    evaluator = data.get("evaluator_type", case.evaluator_type)
    config = data.get("evaluator_config", case.evaluator_config)
    _validate_evaluator(evaluator, config)

    for key, value in data.items():
        setattr(case, key, value)
    # Version bump: historical runs keep their own snapshot and are unaffected.
    case.version += 1
    db.commit()
    db.refresh(case)
    return case
