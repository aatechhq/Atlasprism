"""Organisations, membership and reusable datasets.

Two capabilities that share a theme: things that outlive a single project.

An **organisation** lets several people reach the same project, each at a role.
A **dataset** is a versioned library of cases that belongs to a person or a
team rather than to one project, so a Shield library can be authored once and
instantiated wherever it is needed instead of copied between projects by hand.

Dataset versions are immutable. Editing creates the next version, so a suite
instantiated from version 2 keeps meaning what it meant after version 3 exists
— the same reasoning as the per-run case snapshot.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, writable_project
from app.core.errors import BadRequest, Forbidden, NotFound
from app.db.session import get_db
from app.models import (
    Dataset, DatasetVersion, Membership, Organization, Project, TestCase, TestSuite, User,
)
from app.schemas.api import (
    DatasetCreate, DatasetInstantiate, DatasetOut, DatasetVersionCreate, DatasetVersionOut,
    MemberAdd, MemberOut, OrganizationCreate, OrganizationOut, SuiteOut,
)

router = APIRouter(tags=["teams"])

# Only these fields are copied from a dataset case into a test case. A dataset
# may carry extra keys (notes, provenance); they are stored but never fed to
# the evaluator.
CASE_FIELDS = (
    "name", "user_prompt", "system_prompt", "language", "category",
    "evaluator_type", "evaluator_config", "severity", "severity_rationale",
    "repeat_count",
)


# --------------------------------------------------------------- organisations

def _membership_or_404(db: Session, org_id: uuid.UUID, user: User) -> Membership:
    m = db.scalar(select(Membership).where(
        Membership.organization_id == org_id, Membership.user_id == user.id))
    if m is None:
        # 404 rather than 403: do not confirm that an organisation exists to
        # someone who is not in it.
        raise NotFound("Organisation not found.")
    return m


def _org_out(db: Session, org: Organization, role: str | None) -> OrganizationOut:
    count = db.scalar(select(func.count(Membership.id)).where(
        Membership.organization_id == org.id)) or 0
    out = OrganizationOut.model_validate(org)
    out.role = role
    out.member_count = int(count)
    return out


@router.post("/organizations", response_model=OrganizationOut, status_code=201)
def create_organization(
    body: OrganizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> OrganizationOut:
    """Create an organisation. The creator becomes its owner."""
    org = Organization(name=body.name.strip())
    db.add(org)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(org)
    return _org_out(db, org, "owner")


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> list[OrganizationOut]:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.created_at.desc())
    ).all()
    return [_org_out(db, org, role) for org, role in rows]


@router.get("/organizations/{org_id}/members", response_model=list[MemberOut])
def list_members(
    org_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user),
) -> list[MemberOut]:
    _membership_or_404(db, org_id, user)
    rows = db.execute(
        select(Membership, User.email).join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == org_id)
        .order_by(Membership.created_at)
    ).all()
    return [MemberOut(user_id=m.user_id, email=email, role=m.role, created_at=m.created_at)
            for m, email in rows]


@router.post("/organizations/{org_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    org_id: uuid.UUID, body: MemberAdd,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> MemberOut:
    """Add an existing user to the organisation, at a role.

    The person must already have an account: inviting by email address alone
    would mean creating accounts on someone else's behalf, which is a different
    feature with its own consent questions.
    """
    mine = _membership_or_404(db, org_id, user)
    if not mine.can_administer:
        raise Forbidden("Only an admin or the owner can add members.")

    email = body.email.strip().lower()
    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        raise BadRequest(
            f"No account exists for {email}. They need to sign in once before "
            f"they can be added to an organisation.",
            email=email,
        )
    existing = db.scalar(select(Membership).where(
        Membership.organization_id == org_id, Membership.user_id == target.id))
    if existing is not None:
        raise BadRequest(f"{email} is already a member, with role "
                         f"'{existing.role}'.", role=existing.role)
    if body.role == "owner" and mine.role != "owner":
        raise Forbidden("Only an owner can grant the owner role.")

    m = Membership(organization_id=org_id, user_id=target.id, role=body.role)
    db.add(m)
    db.commit()
    db.refresh(m)
    return MemberOut(user_id=target.id, email=email, role=m.role, created_at=m.created_at)


@router.delete("/organizations/{org_id}/members/{user_id}", status_code=204)
def remove_member(
    org_id: uuid.UUID, user_id: uuid.UUID,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> None:
    mine = _membership_or_404(db, org_id, user)
    target = db.scalar(select(Membership).where(
        Membership.organization_id == org_id, Membership.user_id == user_id))
    if target is None:
        raise NotFound("That person is not a member.")
    # Anyone may remove themselves. Removing someone else needs admin.
    if target.user_id != user.id and not mine.can_administer:
        raise Forbidden("Only an admin or the owner can remove another member.")
    if target.role == "owner" and mine.role != "owner":
        raise Forbidden("Only an owner can remove an owner.")
    remaining_owners = db.scalar(select(func.count(Membership.id)).where(
        Membership.organization_id == org_id, Membership.role == "owner")) or 0
    if target.role == "owner" and remaining_owners <= 1:
        raise BadRequest(
            "This is the last owner. Grant the owner role to someone else "
            "first, or the organisation would be left with nobody who can "
            "manage it."
        )
    db.delete(target)
    db.commit()


@router.post("/projects/{project_id}/organization", response_model=OrganizationOut)
def attach_project(
    project_id: uuid.UUID, org_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> OrganizationOut:
    """Share a project with an organisation.

    Only the project's **owner** may do this: it widens who can reach the
    project, so an organisation admin must not be able to pull somebody else's
    project in.
    """
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise NotFound("Project not found.")
    mine = _membership_or_404(db, org_id, user)
    if not mine.can_administer:
        raise Forbidden("Only an admin or the owner of the organisation can do this.")
    project.organization_id = org_id
    db.commit()
    org = db.get(Organization, org_id)
    return _org_out(db, org, mine.role)


# --------------------------------------------------------------------- datasets

def _readable_dataset(db: Session, dataset_id: uuid.UUID, user: User) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise NotFound("Dataset not found.")
    if ds.owner_id == user.id:
        return ds
    if ds.organization_id is not None:
        m = db.scalar(select(Membership).where(
            Membership.organization_id == ds.organization_id,
            Membership.user_id == user.id))
        if m is not None:
            return ds
    raise NotFound("Dataset not found.")


def _dataset_out(ds: Dataset) -> DatasetOut:
    out = DatasetOut.model_validate(ds)
    out.versions = [DatasetVersionOut.model_validate(v) for v in ds.versions]
    out.latest_version = max((v.version for v in ds.versions), default=None)
    return out


def _clean_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reject a dataset that could not produce a scorable case."""
    out: list[dict[str, Any]] = []
    for i, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise BadRequest(f"Case {i} is not an object.")
        if not case.get("name"):
            raise BadRequest(f"Case {i} has no name.")
        if not case.get("user_prompt"):
            raise BadRequest(f"Case {i} ({case['name']}) has no user_prompt.")
        if not case.get("evaluator_type"):
            raise BadRequest(
                f"Case {i} ({case['name']}) has no evaluator_type, so it would "
                f"have no observable oracle."
            )
        out.append(case)
    return out


@router.post("/datasets", response_model=DatasetOut, status_code=201)
def create_dataset(
    body: DatasetCreate, db: Session = Depends(get_db), user: User = Depends(current_user),
) -> DatasetOut:
    """Create a dataset and its first version."""
    if body.organization_id is not None:
        m = _membership_or_404(db, body.organization_id, user)
        if not m.can_write:
            raise Forbidden("A viewer cannot create a shared dataset.")
    cases = _clean_cases(body.cases)
    ds = Dataset(owner_id=user.id, organization_id=body.organization_id,
                 name=body.name.strip(), engine=body.engine, description=body.description)
    db.add(ds)
    db.flush()
    db.add(DatasetVersion(dataset_id=ds.id, version=1, cases=cases, notes="Initial version."))
    db.commit()
    db.refresh(ds)
    return _dataset_out(ds)


@router.get("/datasets", response_model=list[DatasetOut])
def list_datasets(
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> list[DatasetOut]:
    """Datasets the caller owns, plus those shared with their organisations."""
    org_ids = [r for (r,) in db.execute(
        select(Membership.organization_id).where(Membership.user_id == user.id)).all()]
    q = select(Dataset).where(Dataset.owner_id == user.id)
    if org_ids:
        q = select(Dataset).where(
            (Dataset.owner_id == user.id) | (Dataset.organization_id.in_(org_ids)))
    return [_dataset_out(ds) for ds in
            db.scalars(q.order_by(Dataset.created_at.desc())).all()]


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user),
) -> DatasetOut:
    return _dataset_out(_readable_dataset(db, dataset_id, user))


@router.get("/datasets/{dataset_id}/versions/{version}")
def get_dataset_version(
    dataset_id: uuid.UUID, version: int,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> dict:
    ds = _readable_dataset(db, dataset_id, user)
    v = next((x for x in ds.versions if x.version == version), None)
    if v is None:
        raise NotFound(f"Version {version} does not exist.")
    return {"dataset_id": str(ds.id), "name": ds.name, "engine": ds.engine,
            "version": v.version, "notes": v.notes, "case_count": v.case_count,
            "cases": v.cases}


@router.post("/datasets/{dataset_id}/versions", response_model=DatasetVersionOut,
             status_code=201)
def add_version(
    dataset_id: uuid.UUID, body: DatasetVersionCreate,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> DatasetVersion:
    """Add the next version. Existing versions are never modified."""
    ds = _readable_dataset(db, dataset_id, user)
    if ds.owner_id != user.id:
        m = db.scalar(select(Membership).where(
            Membership.organization_id == ds.organization_id,
            Membership.user_id == user.id)) if ds.organization_id else None
        if m is None or not m.can_write:
            raise Forbidden("You do not have write access to this dataset.")
    cases = _clean_cases(body.cases)
    nxt = max((v.version for v in ds.versions), default=0) + 1
    v = DatasetVersion(dataset_id=ds.id, version=nxt, cases=cases, notes=body.notes)
    db.add(v)
    ds.updated_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    db.refresh(v)
    return v


@router.post("/datasets/{dataset_id}/instantiate", response_model=SuiteOut, status_code=201)
def instantiate(
    dataset_id: uuid.UUID, body: DatasetInstantiate,
    db: Session = Depends(get_db), user: User = Depends(current_user),
) -> SuiteOut:
    """Create a suite in a project from a dataset version.

    This is the cross-project reuse: one library, instantiated wherever it is
    needed. The suite records which dataset and version it came from, so a
    result can be traced back to the library that produced it.
    """
    ds = _readable_dataset(db, dataset_id, user)
    writable_project(body.project_id, db, user)

    version = body.version or max((v.version for v in ds.versions), default=0)
    v = next((x for x in ds.versions if x.version == version), None)
    if v is None:
        raise NotFound(f"Version {version} does not exist for this dataset.")
    if not v.cases:
        raise BadRequest("That version contains no cases.")

    suite = TestSuite(
        project_id=body.project_id,
        name=body.suite_name or f"{ds.name} (v{version})",
        engine=ds.engine,
        description=(f"Instantiated from dataset {ds.name!r} version {version}. "
                     f"{ds.description or ''}").strip(),
    )
    db.add(suite)
    db.flush()

    made = 0
    for case in v.cases:
        payload = {k: case[k] for k in CASE_FIELDS if k in case}
        payload.setdefault("language", "en")
        payload.setdefault("repeat_count", 1)
        db.add(TestCase(suite_id=suite.id, version=1, **payload))
        made += 1
    db.commit()
    db.refresh(suite)
    # case_count is computed, not a column: returning the ORM object directly
    # would report 0 for a suite that just received `made` cases.
    out = SuiteOut.model_validate(suite)
    out.case_count = made
    return out
