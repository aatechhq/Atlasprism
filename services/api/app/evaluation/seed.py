"""Seed the admin user and the baseline suites from datasets/.

Idempotent: re-running updates nothing silently - it skips what already exists
and reports what it did. Run with:

    python -m app.evaluation.seed
"""
from __future__ import annotations

import json
import pathlib
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Project, TestCase, TestSuite, User

DATASETS = pathlib.Path(__file__).resolve().parents[3].parent / "datasets"


def load_dataset(name: str) -> dict:
    path = DATASETS / name
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def seed(project_name: str = "ATLAS Prism Baseline") -> dict:
    if not settings.admin_password:
        raise SystemExit(
            "ADMIN_PASSWORD is empty. Set it in services/api/.env before seeding."
        )
    db = SessionLocal()
    report: dict[str, object] = {}
    try:
        email = settings.admin_email.strip().lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(settings.admin_password),
                is_admin=True,
            )
            db.add(user)
            db.flush()
            report["admin"] = f"created {email}"
        else:
            report["admin"] = f"exists {email}"

        project = db.scalar(
            select(Project).where(Project.owner_id == user.id, Project.name == project_name)
        )
        if project is None:
            project = Project(
                owner_id=user.id,
                name=project_name,
                description="Seeded baseline project with the Guard and Shield v1 suites.",
            )
            db.add(project)
            db.flush()
            report["project"] = f"created {project_name}"
        else:
            report["project"] = f"exists {project_name}"

        suites_report = []
        for filename in ("guard_baseline.json", "shield_baseline.json"):
            data = load_dataset(filename)
            existing = db.scalar(
                select(TestSuite).where(
                    TestSuite.project_id == project.id, TestSuite.name == data["name"]
                )
            )
            if existing is not None:
                suites_report.append(
                    f"{data['name']}: exists ({len(existing.cases)} cases), left untouched"
                )
                continue
            suite = TestSuite(
                project_id=project.id,
                name=data["name"],
                engine=data["engine"],
                description=data.get("description"),
                version=1,
            )
            db.add(suite)
            db.flush()
            for case in data["cases"]:
                db.add(TestCase(
                    suite_id=suite.id,
                    name=case["name"],
                    system_prompt=case.get("system_prompt"),
                    user_prompt=case["user_prompt"],
                    language=case.get("language", "en"),
                    category=case.get("category"),
                    evaluator_type=case["evaluator_type"],
                    evaluator_config=case.get("evaluator_config", {}),
                    severity=case.get("severity"),
                    severity_rationale=case.get("severity_rationale"),
                    repeat_count=int(case.get("repeat_count", 1)),
                    version=1,
                ))
            suites_report.append(f"{data['name']}: created with {len(data['cases'])} cases")
        report["suites"] = suites_report
        report["project_id"] = str(project.id)
        db.commit()
        return report
    finally:
        db.close()


if __name__ == "__main__":
    out = seed()
    for key, value in out.items():
        if isinstance(value, list):
            print(f"{key}:")
            for item in value:
                print(f"  - {item}")
        else:
            print(f"{key}: {value}")
    print("\nSeed complete.", file=sys.stderr)
