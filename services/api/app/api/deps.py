"""Auth + project-scoping dependencies.

Every protected route resolves the caller, then resolves the resource THROUGH
that caller's ownership. A project id belonging to someone else returns 404
(not 403) so the API does not confirm the existence of other tenants' ids.
"""
from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import NotFound, Unauthorized
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import ModelConnection, Project, TestRun, TestSuite, User

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise Unauthorized("Missing bearer token.")
    payload = decode_access_token(creds.credentials)
    if not payload or not payload.get("sub"):
        raise Unauthorized("Invalid or expired token.")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError:
        raise Unauthorized("Malformed token subject.")
    user = db.get(User, user_id)
    if user is None:
        raise Unauthorized("Token subject no longer exists.")
    return user


def owned_project(project_id: uuid.UUID, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise NotFound("Project not found.")
    return project


def owned_connection(connection_id: uuid.UUID, db: Session, user: User) -> ModelConnection:
    conn = db.get(ModelConnection, connection_id)
    if conn is None:
        raise NotFound("Connection not found.")
    owned_project(conn.project_id, db, user)
    return conn


def owned_suite(suite_id: uuid.UUID, db: Session, user: User) -> TestSuite:
    suite = db.get(TestSuite, suite_id)
    if suite is None:
        raise NotFound("Suite not found.")
    owned_project(suite.project_id, db, user)
    return suite


def owned_run(run_id: uuid.UUID, db: Session, user: User) -> TestRun:
    run = db.get(TestRun, run_id)
    if run is None:
        raise NotFound("Run not found.")
    owned_project(run.project_id, db, user)
    return run
