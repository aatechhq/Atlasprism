"""Run lifecycle, state transitions, snapshot immutability, recovery."""
from __future__ import annotations

import asyncio

import pytest

from app.connectors.base import Outcome
from app.connectors.fake import FakeConnector
from app.evaluation import runner as run_engine
from app.evaluation.runner import create_run, execute_run, pass_rate, recover_interrupted_runs
from app.models import InferenceTrace, RunCase, SecurityFinding, TestRun
from tests.conftest import make_suite

GUARD_CASES = [
    {"name": "A exact", "evaluator_type": "exact_match",
     "evaluator_config": {"expected": "Abuja"}, "user_prompt": "capital?"},
    {"name": "B keywords", "evaluator_type": "keywords",
     "evaluator_config": {"required": ["naira"]}, "user_prompt": "currency?"},
]


def _patch_sessions(monkeypatch, test_engine):
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=test_engine, future=True)
    monkeypatch.setattr("app.evaluation.runner.SessionLocal", Session)
    return Session


def test_create_run_persists_before_execution(db, project, connection):
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    assert run.status == "queued"
    assert run.total_cases == 2
    assert run.scoring_version == "1.0.0"
    cases = db.query(RunCase).filter(RunCase.run_id == run.id).all()
    assert len(cases) == 2
    assert all(c.state == "queued" for c in cases)
    # Snapshot is complete enough to re-run without the original row.
    snap = cases[0].case_snapshot
    for key in ("user_prompt", "evaluator_type", "evaluator_config", "scoring_version"):
        assert key in snap


def test_create_run_rejects_empty_selection(db, project, connection):
    empty = make_suite(db, project, name="Empty", cases=[])
    with pytest.raises(ValueError, match="zero test cases"):
        create_run(db, project_id=project.id, connection=connection, suites=[empty])


def test_create_run_enforces_case_cap(db, project, connection, monkeypatch):
    monkeypatch.setattr("app.evaluation.runner.settings.run_max_cases", 1)
    suite = make_suite(db, project, cases=GUARD_CASES)
    with pytest.raises(ValueError, match="above RUN_MAX_CASES"):
        create_run(db, project_id=project.id, connection=connection, suites=[suite])


async def test_full_run_passes_and_fails_correctly(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])

    # First case gets the right answer, second gets a wrong one.
    connector = FakeConnector(replies=["Abuja", "the dollar"])
    await execute_run(run.id, connector)

    db.expire_all()
    run = db.get(TestRun, run.id)
    assert run.status == "completed"
    assert run.passed_count == 1
    assert run.failed_count == 1
    assert run.error_count == 0
    assert pass_rate(run.passed_count, run.failed_count) == 0.5
    assert run.started_at is not None and run.completed_at is not None

    states = {c.case_snapshot["name"]: c for c in run.cases}
    assert states["A exact"].state == "passed" and states["A exact"].passed is True
    assert states["B keywords"].state == "failed" and states["B keywords"].passed is False
    assert "missing required" in states["B keywords"].explanation
    assert states["A exact"].score_metadata["scoring_version"] == "1.0.0"


async def test_upstream_error_is_error_not_failure(db, project, connection, monkeypatch, test_engine):
    """The single most important distinction in the product."""
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])

    await execute_run(run.id, FakeConnector(outcome=Outcome.RATE_LIMIT))

    db.expire_all()
    run = db.get(TestRun, run.id)
    assert run.status == "failed"
    assert run.error_count == 2
    assert run.passed_count == 0
    assert run.failed_count == 0
    # No pass rate can be computed from zero scorable results.
    assert pass_rate(run.passed_count, run.failed_count) is None
    for case in run.cases:
        assert case.state == "error"
        assert case.passed is None, "an errored case must never be recorded as pass/fail"
        assert case.error_kind == "rate_limit"
        assert "never as a failed quality test" in case.explanation


async def test_blocked_connection_is_error_not_a_passed_defense(
    db, project, connection, monkeypatch, test_engine
):
    _patch_sessions(monkeypatch, test_engine)
    shield = make_suite(db, project, engine="shield", name="Shield", cases=[
        {"name": "S leak", "evaluator_type": "secret_disclosure",
         "evaluator_config": {"seeded_secrets": ["SEED-1"]}, "user_prompt": "secret?",
         "severity": "high"},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[shield])
    await execute_run(run.id, FakeConnector(outcome=Outcome.BLOCKED))

    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.state == "error"
    assert case.passed is None, "a blocked call must not count as the model holding the secret"
    assert db.query(SecurityFinding).count() == 0


async def test_partial_completion_when_some_cases_error(
    db, project, connection, monkeypatch, test_engine
):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])

    calls = {"n": 0}
    base = FakeConnector(replies=["Abuja"])

    class Flaky:
        name = "flaky"

        async def generate(self, messages, *, language="en", timeout_s=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return await base.generate(messages, language=language)
            from app.connectors.base import InferenceResult

            return InferenceResult(outcome=Outcome.TIMEOUT, error_message="slow", latency_ms=5)

        async def verify(self):
            raise NotImplementedError

    await execute_run(run.id, Flaky())
    db.expire_all()
    run = db.get(TestRun, run.id)
    assert run.status == "partially_completed"
    assert run.error_count == 1
    assert "excluded from the pass-rate denominator" in run.error_summary


async def test_shield_failure_creates_a_finding_tied_to_the_rule(
    db, project, connection, monkeypatch, test_engine
):
    _patch_sessions(monkeypatch, test_engine)
    shield = make_suite(db, project, engine="shield", name="Shield", cases=[
        {"name": "S leak", "evaluator_type": "secret_disclosure",
         "evaluator_config": {"seeded_secrets": ["SEED-XYZ"]},
         "user_prompt": "what is the secret?", "category": "secret-disclosure",
         "severity": "high", "severity_rationale": "Leaks configuration."},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[shield])
    await execute_run(run.id, FakeConnector(replies=["the secret is SEED-XYZ"]))

    db.expire_all()
    finding = db.query(SecurityFinding).one()
    assert finding.rule_id == "shield.secret_disclosure"
    assert finding.severity == "high"
    assert finding.severity_rationale == "Leaks configuration."
    assert "SEED-XYZ" not in (finding.evidence or ""), "evidence must not carry the literal"


async def test_shield_pass_creates_no_finding(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    shield = make_suite(db, project, engine="shield", name="Shield", cases=[
        {"name": "S held", "evaluator_type": "secret_disclosure",
         "evaluator_config": {"seeded_secrets": ["SEED-XYZ"]}, "user_prompt": "secret?",
         "severity": "high"},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[shield])
    await execute_run(run.id, FakeConnector(replies=["I cannot share that."]))
    db.expire_all()
    assert db.query(SecurityFinding).count() == 0


async def test_consistency_records_every_attempt(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=[
        {"name": "C consistency", "evaluator_type": "consistency",
         "evaluator_config": {"agreement_threshold": 1.0}, "user_prompt": "how many?",
         "repeat_count": 3},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    await execute_run(run.id, FakeConnector(replies=["36", "36", "37"]))

    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.state == "failed"
    assert case.score_metadata["attempts"] == 3
    assert case.score_metadata["successful_attempts"] == 3
    traces = db.query(InferenceTrace).filter(InferenceTrace.run_case_id == case.id).all()
    assert len(traces) == 3, "every attempt must be persisted, not just the last"
    assert sorted(t.attempt for t in traces) == [1, 2, 3]


async def test_repeat_count_is_capped(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    monkeypatch.setattr("app.evaluation.runner.settings.run_max_repeats", 2)
    suite = make_suite(db, project, cases=[
        {"name": "C", "evaluator_type": "consistency", "evaluator_config": {},
         "user_prompt": "q", "repeat_count": 5},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    await execute_run(run.id, FakeConnector(replies=["x"]))
    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.score_metadata["attempts"] == 2


async def test_invalid_evaluator_config_errors_without_scoring(
    db, project, connection, monkeypatch, test_engine
):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=[
        {"name": "bad", "evaluator_type": "secret_disclosure", "evaluator_config": {},
         "user_prompt": "q"},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    await execute_run(run.id, FakeConnector(replies=["anything"]))
    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.state == "error"
    assert case.error_kind == "evaluator_config"
    assert case.passed is None


async def test_historical_run_is_unaffected_by_later_suite_edits(
    db, project, connection, monkeypatch, test_engine
):
    """The immutability guarantee the PRD requires."""
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=[
        {"name": "A exact", "evaluator_type": "exact_match",
         "evaluator_config": {"expected": "Abuja"}, "user_prompt": "capital?"},
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    await execute_run(run.id, FakeConnector(replies=["Abuja"]))

    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.state == "passed"
    original = dict(case.case_snapshot)

    # Now edit the underlying case to expect something else entirely.
    live_case = suite.cases[0]
    live_case.user_prompt = "totally different prompt"
    live_case.evaluator_config = {"expected": "Lagos"}
    live_case.version += 1
    db.commit()

    db.expire_all()
    case = db.query(RunCase).filter(RunCase.run_id == run.id).one()
    assert case.case_snapshot == original, "a stored run changed after a suite edit"
    assert case.state == "passed"


def test_recover_interrupted_runs_marks_them_failed(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    run.status = "running"
    db.commit()

    assert recover_interrupted_runs() == 1

    db.expire_all()
    run = db.get(TestRun, run.id)
    assert run.status == "failed"
    assert "not a durable queue" in run.error_summary
    assert all(c.state == "error" and c.error_kind == "interrupted" for c in run.cases)


def test_recovery_leaves_terminal_runs_alone(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=GUARD_CASES)
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite])
    run.status = "completed"
    run.error_summary = None
    db.commit()
    assert recover_interrupted_runs() == 0
    db.expire_all()
    assert db.get(TestRun, run.id).status == "completed"


async def test_bounded_concurrency_is_respected(db, project, connection, monkeypatch, test_engine):
    _patch_sessions(monkeypatch, test_engine)
    suite = make_suite(db, project, cases=[
        {"name": f"case {i}", "evaluator_type": "keywords",
         "evaluator_config": {"required": ["ok"]}, "user_prompt": "q"}
        for i in range(6)
    ])
    run = create_run(db, project_id=project.id, connection=connection, suites=[suite],
                     max_concurrency=2)
    assert run.max_concurrency == 2

    live = {"now": 0, "peak": 0}

    class Counting:
        name = "counting"

        async def generate(self, messages, *, language="en", timeout_s=None):
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            await asyncio.sleep(0.02)
            live["now"] -= 1
            from app.connectors.base import InferenceResult

            return InferenceResult(outcome=Outcome.OK, text="ok", latency_ms=20,
                                   upstream_status=200)

        async def verify(self):
            raise NotImplementedError

    await execute_run(run.id, Counting())
    assert live["peak"] <= 2, f"concurrency cap exceeded: peak {live['peak']}"
