"""Test fixtures.

Tests run against a REAL PostgreSQL database (atlas_prism_test), created and
dropped per session, so the schema under test is the schema that ships. The
only mocked component is the model connector, which is what unit mocks are for
(build path 0.1: "Unit mocks are allowed in tests only").
"""
from __future__ import annotations

import os

# Must be set before app.connectors.fake is imported anywhere.
os.environ["ATLAS_PRISM_ALLOW_FAKE_CONNECTOR"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import ModelConnection, Project, TestCase, TestSuite, User

TEST_DB = "atlas_prism_test"


def _admin_url() -> str:
    """Connection URL to the maintenance database, for CREATE/DROP DATABASE."""
    return settings.database_url.rsplit("/", 1)[0] + "/postgres"


def _test_url() -> str:
    return settings.database_url.rsplit("/", 1)[0] + "/" + TEST_DB


@pytest.fixture(scope="session")
def test_engine():
    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    engine = create_engine(_test_url(), future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()

    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db(test_engine):
    """A clean database for each test: every table truncated."""
    Session = sessionmaker(bind=test_engine, future=True)
    session = Session()

    session.execute(text(
        "TRUNCATE users, projects, model_connections, test_suites, test_cases, "
        "test_runs, run_cases, inference_traces, security_findings, report_exports "
        "RESTART IDENTITY CASCADE"
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db, test_engine, monkeypatch):
    """TestClient wired to the test database."""
    Session = sessionmaker(bind=test_engine, future=True)
    monkeypatch.setattr("app.db.session.SessionLocal", Session)
    monkeypatch.setattr("app.evaluation.runner.SessionLocal", Session)

    def override_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db) -> User:
    user = User(email="tester@example.invalid",
                password_hash=hash_password("correct-horse"), is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_headers(client, admin_user) -> dict:
    resp = client.post("/api/v1/auth/login",
                       json={"email": admin_user.email, "password": "correct-horse"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def project(db, admin_user) -> Project:
    p = Project(owner_id=admin_user.id, name="Test Project")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def connection(db, project) -> ModelConnection:
    c = ModelConnection(
        project_id=project.id, provider="natlas",
        endpoint="https://gateway.example.invalid", model_id="NCAIR1/N-ATLaS",
        secret_ref="env:NATLAS_API_KEY", verification_state="unverified",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def make_suite(db, project, engine="guard", name="Suite", cases=()) -> TestSuite:
    suite = TestSuite(project_id=project.id, name=name, engine=engine, version=1)
    db.add(suite)
    db.flush()
    for spec in cases:
        db.add(TestCase(
            suite_id=suite.id,
            name=spec["name"],
            system_prompt=spec.get("system_prompt"),
            user_prompt=spec.get("user_prompt", "prompt"),
            language=spec.get("language", "en"),
            category=spec.get("category"),
            evaluator_type=spec["evaluator_type"],
            evaluator_config=spec.get("evaluator_config", {}),
            severity=spec.get("severity"),
            severity_rationale=spec.get("severity_rationale"),
            repeat_count=spec.get("repeat_count", 1),
            version=1,
        ))
    db.commit()
    db.refresh(suite)
    return suite
