"""Auth and project-scoping tests."""
from __future__ import annotations

import uuid

from app.core.security import hash_password
from app.models import Project, User


def test_login_succeeds_and_returns_token(client, admin_user):
    r = client.post("/api/v1/auth/login",
                    json={"email": admin_user.email, "password": "correct-horse"})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]


def test_wrong_password_rejected(client, admin_user):
    r = client.post("/api/v1/auth/login",
                    json={"email": admin_user.email, "password": "nope"})
    assert r.status_code == 401


def test_no_account_enumeration(client, admin_user):
    a = client.post("/api/v1/auth/login",
                    json={"email": admin_user.email, "password": "nope"})
    b = client.post("/api/v1/auth/login",
                    json={"email": "ghost@example.invalid", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"]["message"] == b.json()["detail"]["message"]


def test_protected_routes_require_a_token(client):
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/projects", json={"name": "x"}).status_code == 401
    assert client.post("/api/v1/runs", json={}).status_code == 401


def test_garbage_token_rejected(client):
    r = client.get("/api/v1/projects", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_token_for_deleted_user_rejected(client, db, auth_headers, admin_user):
    db.delete(admin_user)
    db.commit()
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401


def test_cross_project_access_is_404_not_403(client, db, auth_headers):
    """Another user's project must look non-existent, not merely forbidden."""
    other = User(email="other@example.invalid", password_hash=hash_password("x"))
    db.add(other)
    db.flush()
    foreign = Project(owner_id=other.id, name="Not Yours")
    db.add(foreign)
    db.commit()

    r = client.get(f"/api/v1/suites?project_id={foreign.id}", headers=auth_headers)
    assert r.status_code == 404
    r = client.get(f"/api/v1/metrics/summary?project_id={foreign.id}", headers=auth_headers)
    assert r.status_code == 404


def test_unknown_ids_are_404(client, auth_headers):
    rid = uuid.uuid4()
    assert client.get(f"/api/v1/runs/{rid}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/reports/{rid}", headers=auth_headers).status_code == 404


def test_health_states_its_own_scope(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "not a model integration check" in body["scope"]


def test_connection_response_never_contains_the_key(client, auth_headers, project, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.natlas_api_key", "super-secret-value-9999")
    monkeypatch.setattr("app.api.v1.projects.settings.natlas_api_key", "super-secret-value-9999")
    r = client.post("/api/v1/connections",
                    json={"project_id": str(project.id),
                          "endpoint": "https://gateway.example.invalid"},
                    headers=auth_headers)
    assert r.status_code in (201, 400)
    if r.status_code == 201:
        body = r.text
        assert "super-secret-value-9999" not in body
        assert "****9999" in body  # only the last four, as a fact of configuration


def test_invalid_regex_rejected_at_write_time(client, auth_headers, project, db):
    """Catch a bad pattern when the case is created, not mid-run."""
    from tests.conftest import make_suite

    suite = make_suite(db, project, engine="shield", name="S", cases=[])
    r = client.post("/api/v1/test-cases", json={
        "suite_id": str(suite.id), "name": "bad regex", "user_prompt": "q",
        "evaluator_type": "forbidden_action",
        # Literal backslashes: the malformed form that broke the first live run.
        "evaluator_config": {"forbidden_patterns": [r"transfer_funds\\s*\\("]},
    }, headers=auth_headers)
    assert r.status_code == 400
    assert "invalid regular expression" in r.json()["detail"]["message"]
