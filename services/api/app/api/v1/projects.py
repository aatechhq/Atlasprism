"""Projects and N-ATLAS connections."""
from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_connection, owned_project
from app.connectors.generic import GenericHttpConnector
from app.connectors.natlas import NatlasConnector
from app.core import netguard, ownership
from app.core.config import settings
from app.core.errors import BadRequest, NotFound
from app.core.security import redact_secret
from app.db.session import get_db
from app.models import HostVerification, ModelConnection, Project, User
from app.schemas.api import (
    ConnectionCreate, ConnectionOut, HostVerificationCreate, HostVerificationOut,
    ProjectCreate, ProjectOut, ProjectUpdate,
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


def connector_for(conn: ModelConnection):
    """Build the connector a connection's provider calls for.

    One place, so a provider can never be honoured in one route and ignored in
    another -- which would be a way to reach an unverified host.
    """
    if conn.provider == "openai_compatible":
        return GenericHttpConnector(
            base_url=conn.endpoint, model_id=conn.model_id,
            api_key=settings.natlas_api_key or None,
            timeout_ms=settings.natlas_timeout_ms,
        )
    return connector_for(conn)


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

    if body.provider == "natlas":
        # The documented gateway: the server-side allowlist governs.
        allowed = settings.allowed_inference_hosts
        if allowed and host not in allowed:
            raise BadRequest(
                f"Endpoint host {host!r} is not allowlisted. Add it to "
                "NATLAS_ALLOWED_HOSTS server-side if it is legitimate.",
                allowed_hosts=sorted(allowed),
            )
    else:
        # A developer's own endpoint. TWO independent controls, both required.
        #
        # 1. Containment: the address must not be inside private or reserved
        #    space, whatever the caller claims about it.
        try:
            netguard.check_endpoint(endpoint)
        except netguard.EndpointRejected as exc:
            raise BadRequest(str(exc))
        # 2. Authorisation: the project must have PROVEN it controls the host.
        #    Shield sends attacks; a checkbox is not consent.
        hv = db.scalar(select(HostVerification).where(
            HostVerification.project_id == body.project_id,
            HostVerification.host == host))
        if hv is None or not hv.is_verified:
            raise BadRequest(
                f"Host {host!r} is not verified for this project. Create a "
                f"verification, publish the token by DNS TXT or as a file at "
                f"/.well-known/atlas-prism-verification.txt, then check it. "
                f"Prism does not send adversarial tests to a host the project "
                f"has not proven it controls.",
                host=host,
                verification_required=True,
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


@router.post("/verifications", response_model=HostVerificationOut, status_code=201)
def create_verification(
    body: HostVerificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> HostVerification:
    """Begin proving that this project controls a host.

    Returns a token to publish, by DNS TXT or as a file. Nothing is verified
    yet: call the check endpoint once the token is live.
    """
    owned_project(body.project_id, db, user)
    host = (body.host or "").strip().lower().removeprefix("https://").removeprefix("http://")
    host = host.split("/")[0].split(":")[0]
    if not host or "." not in host:
        raise BadRequest("Give a bare hostname, for example api.example.com.")

    existing = db.scalar(select(HostVerification).where(
        HostVerification.project_id == body.project_id, HostVerification.host == host))
    if existing:
        return existing

    hv = HostVerification(project_id=body.project_id, host=host, token=ownership.new_token())
    db.add(hv)
    db.commit()
    db.refresh(hv)
    return hv


@router.get("/verifications/{verification_id}/instructions")
def verification_instructions(
    verification_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Exactly what to publish, by either method."""
    hv = db.get(HostVerification, verification_id)
    if hv is None:
        raise NotFound("Verification not found.")
    owned_project(hv.project_id, db, user)
    ins = ownership.instructions_for(hv.host, hv.token)
    return {
        "id": str(hv.id),
        "host": hv.host,
        "verified": hv.is_verified,
        "methods": {
            "dns_txt": {
                "record_name": ins.dns_name,
                "record_type": "TXT",
                "record_value": ins.dns_value,
                "note": "DNS changes can take a few minutes to propagate.",
            },
            "https_file": {
                "url": ins.file_url,
                "contents": ins.file_contents,
                "note": "Must be served over https and must not redirect.",
            },
        },
        "why": (
            "Shield sends prompt-injection and secret-extraction attempts. "
            "Prism will not send those to a host until the project proves it "
            "controls it."
        ),
    }


@router.post("/verifications/{verification_id}/check", response_model=HostVerificationOut)
def check_verification(
    verification_id: uuid.UUID,
    method: str = Query("dns_txt", pattern="^(dns_txt|https_file)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> HostVerification:
    """Perform the check. Records the failure reason when it does not pass."""
    hv = db.get(HostVerification, verification_id)
    if hv is None:
        raise NotFound("Verification not found.")
    owned_project(hv.project_id, db, user)
    try:
        detail = ownership.verify(hv.host, hv.token, method)
    except ownership.VerificationFailed as exc:
        hv.last_error = str(exc)
        db.commit()
        db.refresh(hv)
        raise BadRequest(str(exc), host=hv.host, method=method)
    hv.method = method
    hv.verified_at = dt.datetime.now(dt.timezone.utc)
    hv.last_error = None
    db.commit()
    db.refresh(hv)
    return hv


@router.get("/verifications", response_model=list[HostVerificationOut])
def list_verifications(
    project_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[HostVerification]:
    owned_project(project_id, db, user)
    return list(db.scalars(
        select(HostVerification).where(HostVerification.project_id == project_id)
        .order_by(HostVerification.created_at.desc())).all())


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
    connector = connector_for(conn)
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
    return await connector_for(conn).health()
