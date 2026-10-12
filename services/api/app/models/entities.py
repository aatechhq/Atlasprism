"""Domain model (PRD 5).

Conventions, applied uniformly:
  * UUID primary keys, FK constraints, UTC timestamps.
  * No credential is ever stored in plaintext in a snapshot, log or report.
  * `run_cases.case_snapshot` is written once and never updated, so a
    historical run cannot change when its suite is later edited.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_subject: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _updated()

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # The application under test: the system prompt and rules the developer's
    # own assistant runs with. Prism layers this beneath every test case, so
    # Guard measures adherence to THESE instructions and Shield attempts to
    # override THESE rules -- rather than evaluating the base model alone.
    # Nullable and empty by default: an empty profile changes nothing, so
    # existing suites and historical runs behave exactly as before.
    app_system_prompt: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _updated()

    owner: Mapped[User] = relationship(back_populates="projects")


class ModelConnection(Base):
    """A configured inference target.

    The API key is NOT stored here. `secret_ref` names where the credential
    lives (currently the server environment variable NATLAS_API_KEY); the
    value never enters the database, a response, a log or a report.
    """

    __tablename__ = "model_connections"

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="natlas")
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(200), nullable=False, default="env:NATLAS_API_KEY")
    # unverified | verified | failed | blocked
    verification_state: Mapped[str] = mapped_column(String(20), nullable=False, default="unverified")
    verification_detail: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _updated()

    __table_args__ = (
        CheckConstraint(
            "verification_state IN ('unverified','verified','failed','blocked')",
            name="ck_connection_verification_state",
        ),
    )


class TestSuite(Base):
    __tablename__ = "test_suites"

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    engine: Mapped[str] = mapped_column(String(20), nullable=False)  # guard | shield
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _updated()

    cases: Mapped[list["TestCase"]] = relationship(
        back_populates="suite", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("engine IN ('guard','shield')", name="ck_suite_engine"),
    )


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[uuid.UUID] = _pk()
    suite_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    category: Mapped[str | None] = mapped_column(String(100))
    evaluator_type: Mapped[str] = mapped_column(String(50), nullable=False)
    evaluator_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str | None] = mapped_column(String(20))
    severity_rationale: Mapped[str | None] = mapped_column(Text)
    repeat_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[dt.datetime] = _created()
    updated_at: Mapped[dt.datetime] = _updated()

    suite: Mapped[TestSuite] = relationship(back_populates="cases")


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = _pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_connections.id", ondelete="RESTRICT"), nullable=False
    )
    # queued | running | completed | partially_completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="queued", index=True)
    suite_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    suite_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scoring_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    model_id: Mapped[str | None] = mapped_column(String(200))
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    total_cases: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    cases: Mapped[list["RunCase"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','completed','partially_completed','failed','cancelled')",
            name="ck_run_status",
        ),
    )


class RunCase(Base):
    """One case within one run.

    `case_snapshot` is the immutable copy of the test case as it was at launch:
    editing the suite afterwards must not change a historical result.
    """

    __tablename__ = "run_cases"

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("test_cases.id", ondelete="SET NULL")
    )
    case_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # queued | running | passed | failed | error | skipped
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean)  # NULL for error/skipped
    score_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    explanation: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = _created()
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[TestRun] = relationship(back_populates="cases")
    traces: Mapped[list["InferenceTrace"]] = relationship(
        back_populates="run_case", cascade="all, delete-orphan"
    )
    findings: Mapped[list["SecurityFinding"]] = relationship(
        back_populates="run_case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','running','passed','failed','error','skipped')",
            name="ck_run_case_state",
        ),
        Index("ix_run_cases_run_state", "run_id", "state"),
    )


class InferenceTrace(Base):
    """One attempted inference call. Every Pulse metric derives from these rows."""

    __tablename__ = "inference_traces"

    id: Mapped[uuid.UUID] = _pk()
    run_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_id: Mapped[str | None] = mapped_column(String(200))
    endpoint: Mapped[str | None] = mapped_column(String(500))
    request_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_text: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    upstream_status: Mapped[int | None] = mapped_column(Integer)
    # ok | auth | rate_limit | timeout | network | upstream_error | schema | empty | blocked
    outcome: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()

    run_case: Mapped[RunCase] = relationship(back_populates="traces")


class SecurityFinding(Base):
    __tablename__ = "security_findings"

    id: Mapped[uuid.UUID] = _pk()
    run_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    mitigation: Mapped[str | None] = mapped_column(Text)
    severity_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created()

    run_case: Mapped[RunCase] = relationship(back_populates="findings")


class ReportExport(Base):
    __tablename__ = "report_exports"

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # json | csv
    generation_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = _created()
