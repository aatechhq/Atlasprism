"""SQLAlchemy models (PRD 5). Importing this registers every table."""
from app.models.entities import (  # noqa: F401
    InferenceTrace,
    ModelConnection,
    Project,
    ReportExport,
    RunCase,
    SecurityFinding,
    TestCase,
    TestRun,
    TestSuite,
    User,
)

__all__ = [
    "User", "Project", "ModelConnection", "TestSuite", "TestCase",
    "TestRun", "RunCase", "InferenceTrace", "SecurityFinding", "ReportExport",
]
