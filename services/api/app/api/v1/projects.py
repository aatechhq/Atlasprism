"""Projects and N-ATLAS connections."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_connection, owned_project
from app.connectors.natlas import NatlasConnector
from app.core.config import settings
from app.core.errors import BadRequest
from app.core.security import redact_secret
from app.db.session import get_db
from app.models import ModelConnection, Project, User
from app.schemas.api import (
    ConnectionCreate, ConnectionOut, ProjectCreate, ProjectOut, ProjectUpdate,
    VerifyResponse,
)

router = APIRouter(tags=["projects"])


def _connection_out(conn: ModelConnection) -> ConnectionOut:
    out = ConnectionOut.model_validate(conn)
    # Only the fact and the last four characters, never the value (PRD 7).
    out.credential = redact_secret(settings.natlas_api_key)
    return out


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Project:
    project = Project(
        owner_id=user.id,
        name=body.name.strip(),
        description=body.description,
        app_system_prompt=(body.app_system_prompt or "").strip() or None,
        gate_min_pass_rate=body.gate_min_pass_rate,
        gate_max_critical_findings=body.gate_max_critical_findings,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[Project]:
    return list(db.scalars(
        select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())
    ).all())


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Project:
    """Edit a project, including its application profile.

    Changing the profile affects FUTURE runs only. Every run freezes the
    profile it executed with into each case snapshot, so historical results
    stay reproducible.
    """
    project = owned_project(project_id, db, user)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        project.name = data["name"].strip()
    if "description" in data:
        project.description = data["description"]
    if "app_system_prompt" in data:
        project.app_system_prompt = (data["app_system_prompt"] or "").strip() or None
    if "gate_min_pass_rate" in data:
        project.gate_min_pass_rate = data["gate_min_pass_rate"]
    if "gate_max_critical_findings" in data:
        project.gate_max_critical_findings = data["gate_max_critical_findings"]
    db.commit()
    db.refresh(project)
    return project


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(
    body: ConnectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ConnectionOut:
    owned_project(body.project_id, db, user)
    endpoint = (body.endpoint or settings.natlas_base_url or "").rstrip("/")
    if not endpoint:
        raise BadRequest(
            "No endpoint given and NATLAS_BASE_URL is not configured."
        )
    # SSRF guard at the write boundary: refuse to even store a non-allowlisted
    # host, so no run can later be pointed at an arbitrary URL.
    from urllib.parse import urlparse

    host = (urlparse(endpoint).hostname or "").lower()
    allowed = settings.allowed_inference_hosts
    if allowed and host not in allowed:
        raise BadRequest(
            f"Endpoint host {host!r} is not allowlisted. Add it to "
            "NATLAS_ALLOWED_HOSTS server-side if it is legitimate.",
            allowed_hosts=sorted(allowed),
        )
    conn = ModelConnection(
        project_id=body.project_id,
        provider=body.provider,
        endpoint=endpoint,
        model_id=body.model_id or settings.natlas_model_id,
        secret_ref="env:NATLAS_API_KEY",
        verification_state="unverified",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _connection_out(conn)


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[ConnectionOut]:
    owned_project(project_id, db, user)
    rows = db.scalars(
        select(ModelConnection).where(ModelConnection.project_id == project_id)
        .order_by(ModelConnection.created_at.desc())
    ).all()
    return [_connection_out(c) for c in rows]


@router.post("/connections/{connection_id}/verify", response_model=VerifyResponse)
async def verify_connection(
    connection_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> VerifyResponse:
    """Perform a REAL authenticated inference call. A health check never counts."""
    conn = owned_connection(connection_id, db, user)
    connector = NatlasConnector(base_url=conn.endpoint, model_id=conn.model_id)
    result = await connector.verify()

    conn.verification_state = result.state
    conn.verification_detail = result.detail
    conn.verified_at = dt.datetime.now(dt.timezone.utc) if result.verified else None
    db.commit()

    return VerifyResponse(
        connection_id=conn.id,
        verified=result.verified,
        state=result.state,
        detail=result.detail,
        outcome=result.outcome.value,
        model_id=result.model_id,
        latency_ms=result.latency_ms,
        upstream_status=result.upstream_status,
        response_excerpt=result.response_excerpt,
        checked_at=dt.datetime.now(dt.timezone.utc),
    )


@router.get("/connections/{connection_id}/gateway-health")
async def gateway_health(
    connection_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Diagnostic reachability probe. Explicitly NOT integration evidence."""
    conn = owned_connection(connection_id, db, user)
    return await NatlasConnector(base_url=conn.endpoint, model_id=conn.model_id).health()
