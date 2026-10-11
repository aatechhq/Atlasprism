"""Migrations must build the schema from a genuinely blank database."""
from __future__ import annotations

import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import settings

API_DIR = pathlib.Path(__file__).resolve().parents[1]
MIGRATION_DB = "atlas_prism_migration_test"

EXPECTED_TABLES = {
    "users", "projects", "model_connections", "test_suites", "test_cases",
    "test_runs", "run_cases", "inference_traces", "security_findings", "report_exports",
}


def test_alembic_upgrade_head_from_blank_database():
    root = settings.database_url.rsplit("/", 1)[0]
    admin = create_engine(root + "/postgres", isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    try:
        url = f"{root}/{MIGRATION_DB}"
        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")

        engine = create_engine(url, future=True)
        names = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= names, f"missing: {EXPECTED_TABLES - names}"
        assert "alembic_version" in names

        # Key constraints the data model depends on actually exist.
        insp = inspect(engine)
        run_cases_cols = {c["name"] for c in insp.get_columns("run_cases")}
        assert {"case_snapshot", "state", "passed", "score_metadata"} <= run_cases_cols
        assert insp.get_foreign_keys("run_cases"), "run_cases must have FK constraints"
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        admin.dispose()
