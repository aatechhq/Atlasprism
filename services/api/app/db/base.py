"""Declarative base. All timestamps are UTC, all primary keys are UUIDs."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
