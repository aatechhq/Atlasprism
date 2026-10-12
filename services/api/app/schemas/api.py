"""Pydantic request/response contracts. This is what the frontend builds against."""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    is_admin: bool


# --- projects ---
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    # The application under test: your assistant's own system prompt and rules.
    # Layered beneath every test case, so results describe YOUR application
    # rather than the base model. Optional -- leave empty to evaluate the model
    # directly.
    app_system_prompt: str | None = Field(default=None, max_length=20000)
    # Release thresholds (blueprint workflow 5). Optional; unset means no gate.
    gate_min_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    gate_max_critical_findings: int | None = Field(default=None, ge=0)


class ProjectUpdate(BaseModel):
    """Partial update. Only supplied fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    app_system_prompt: str | None = Field(default=None, max_length=20000)
    gate_min_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    gate_max_critical_findings: int | None = Field(default=None, ge=0)


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    app_system_prompt: str | None
    gate_min_pass_rate: float | None
    gate_max_critical_findings: int | None
    owner_id: uuid.UUID
    created_at: dt.datetime


# --- connections ---
class ConnectionCreate(BaseModel):
    project_id: uuid.UUID
    name: str | None = Field(default=None, max_length=200)
    provider: Literal["natlas"] = "natlas"
    endpoint: str | None = Field(default=None, max_length=500)
    model_id: str | None = Field(default=None, max_length=200)


class ConnectionOut(ORMModel):
    """Safe connection metadata. The credential is NEVER included."""

    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    endpoint: str
    model_id: str
    verification_state: str
    verification_detail: str | None
    verified_at: dt.datetime | None
    created_at: dt.datetime
    credential: str = "not configured"


class VerifyResponse(BaseModel):
    connection_id: uuid.UUID
    verified: bool
    state: str
    detail: str
    outcome: str
    model_id: str | None = None
    latency_ms: int | None = None
    upstream_status: int | None = None
    response_excerpt: str | None = None
    checked_at: dt.datetime


# --- suites & cases ---
class SuiteCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    engine: Literal["guard", "shield"]
    description: str | None = None


class TestCaseCreate(BaseModel):
    suite_id: uuid.UUID
    name: str = Field(min_length=1, max_length=300)
    user_prompt: str = Field(min_length=1)
    system_prompt: str | None = None
    language: str = Field(default="en", max_length=10)
    category: str | None = Field(default=None, max_length=100)
    evaluator_type: str = Field(min_length=1, max_length=50)
    evaluator_config: dict[str, Any] = Field(default_factory=dict)
    severity: str | None = Field(default=None, max_length=20)
    severity_rationale: str | None = None
    repeat_count: int = Field(default=1, ge=1, le=5)


class TestCaseUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    user_prompt: str | None = None
    system_prompt: str | None = None
    language: str | None = Field(default=None, max_length=10)
    category: str | None = Field(default=None, max_length=100)
    evaluator_type: str | None = Field(default=None, max_length=50)
    evaluator_config: dict[str, Any] | None = None
    severity: str | None = Field(default=None, max_length=20)
    severity_rationale: str | None = None
    repeat_count: int | None = Field(default=None, ge=1, le=5)


class TestCaseOut(ORMModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    system_prompt: str | None
    user_prompt: str
    language: str
    category: str | None
    evaluator_type: str
    evaluator_config: dict[str, Any]
    severity: str | None
    severity_rationale: str | None
    repeat_count: int
    version: int


class SuiteOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    engine: str
    version: int
    description: str | None
    created_at: dt.datetime
    case_count: int = 0


class SuiteDetailOut(SuiteOut):
    cases: list[TestCaseOut] = Field(default_factory=list)


# --- runs ---
class RunCreate(BaseModel):
    project_id: uuid.UUID
    connection_id: uuid.UUID
    suite_ids: list[uuid.UUID] = Field(min_length=1)
    max_concurrency: int = Field(default=2, ge=1, le=8)


class RunCreateResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    total_cases: int


class RunOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    connection_id: uuid.UUID
    status: str
    scoring_version: str
    model_id: str | None
    total_cases: int
    passed_count: int
    failed_count: int
    error_count: int
    skipped_count: int
    error_summary: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    pass_rate: float | None = None
    pass_rate_definition: str = "passed / (passed + failed); errored cases excluded"


class TraceOut(BaseModel):
    trace_id: uuid.UUID
    attempt: int
    outcome: str
    upstream_status: int | None
    latency_ms: int | None
    model_id: str | None
    response_text: str | None
    error_message: str | None
    recorded_at: dt.datetime | None


class RunCaseOut(BaseModel):
    run_case_id: uuid.UUID
    name: str | None
    engine: str | None
    category: str | None
    severity: str | None
    state: str
    passed: bool | None
    explanation: str | None
    error: str | None
    error_kind: str | None
    score_metadata: dict[str, Any]
    case_snapshot: dict[str, Any]
    traces: list[TraceOut] = Field(default_factory=list)


class PaginatedRunCases(BaseModel):
    run_id: uuid.UUID
    total: int
    limit: int
    offset: int
    items: list[RunCaseOut]
