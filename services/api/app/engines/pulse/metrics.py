"""Pulse: every number here is computed from persisted inference traces.

No synthetic traffic, no invented cost or token price, no platform health. When
there is not enough data, that is reported as such rather than shown as zero.
"""
from __future__ import annotations

import statistics
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InferenceTrace, RunCase, TestRun


def _percentile(sorted_values: list[int], pct: float) -> int | None:
    """Nearest-rank percentile. Returns None when there is no data."""
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, int(round(pct / 100.0 * len(sorted_values) + 0.5)) - 1))
    return sorted_values[k]


def summary(db: Session, *, project_id: uuid.UUID, run_id: uuid.UUID | None = None) -> dict[str, Any]:
    q = select(InferenceTrace).where(InferenceTrace.project_id == project_id)
    if run_id is not None:
        case_ids = select(RunCase.id).where(RunCase.run_id == run_id)
        q = q.where(InferenceTrace.run_case_id.in_(case_ids))
    traces = list(db.scalars(q).all())

    by_outcome: dict[str, int] = {}
    for t in traces:
        by_outcome[t.outcome] = by_outcome.get(t.outcome, 0) + 1

    # Latency population: SUCCESSFUL attempts only, stated explicitly.
    latencies = sorted(t.latency_ms for t in traces if t.outcome == "ok" and t.latency_ms is not None)
    runs_q = select(TestRun).where(TestRun.project_id == project_id)
    if run_id is not None:
        runs_q = runs_q.where(TestRun.id == run_id)
    runs = list(db.scalars(runs_q).all())

    passed = sum(r.passed_count for r in runs)
    failed = sum(r.failed_count for r in runs)
    errored = sum(r.error_count for r in runs)

    return {
        "scope": {"project_id": str(project_id), "run_id": str(run_id) if run_id else None},
        "inference": {
            "attempts": len(traces),
            "successful": by_outcome.get("ok", 0),
            "by_outcome": by_outcome,
            "transport_errors": sum(
                by_outcome.get(k, 0) for k in ("timeout", "network", "upstream_error", "rate_limit")
            ),
            "auth_errors": by_outcome.get("auth", 0),
            "blocked": by_outcome.get("blocked", 0),
        },
        "latency_ms": {
            "population": "successful inference attempts only",
            "sample_count": len(latencies),
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": _percentile(latencies, 95),
            "min": latencies[0] if latencies else None,
            "max": latencies[-1] if latencies else None,
            "note": (
                "Not enough successful attempts to report latency."
                if not latencies else
                f"Computed from {len(latencies)} measured successful call(s), client-side."
            ),
        },
        "results": {
            "runs": len(runs),
            "passed": passed,
            "failed": failed,
            "errored_not_scored": errored,
            "pass_rate": (round(passed / (passed + failed), 4) if (passed + failed) else None),
            "pass_rate_definition": "passed / (passed + failed); errors excluded",
        },
        "models_seen": sorted({t.model_id for t in traces if t.model_id}),
        "data_source": "computed from inference_traces and test_runs rows; no synthetic data",
    }


def recent_traces(db: Session, *, project_id: uuid.UUID, run_id: uuid.UUID | None = None,
                  limit: int = 50, offset: int = 0) -> dict[str, Any]:
    q = select(InferenceTrace).where(InferenceTrace.project_id == project_id)
    if run_id is not None:
        q = q.where(InferenceTrace.run_case_id.in_(select(RunCase.id).where(RunCase.run_id == run_id)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(db.scalars(
        q.order_by(InferenceTrace.created_at.desc()).limit(min(limit, 200)).offset(offset)
    ).all())
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "trace_id": str(t.id),
                "run_case_id": str(t.run_case_id),
                "attempt": t.attempt,
                "outcome": t.outcome,
                "upstream_status": t.upstream_status,
                "latency_ms": t.latency_ms,
                "model_id": t.model_id,
                "endpoint": t.endpoint,
                "error_message": t.error_message,
                "recorded_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
    }


def by_language(db: Session, *, project_id: uuid.UUID,
                run_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Quality and latency grouped by the language each case declared.

    An application can be healthy in English and degrade in Hausa or Yoruba
    while the aggregate looks fine, so the aggregate alone is not enough for a
    multilingual product. Computed from persisted run cases and their traces.

    The same two rules as everywhere else: errors are counted separately and
    excluded from the pass rate, and latency is measured over successful
    attempts only.
    """
    cases_q = (
        select(RunCase)
        .join(TestRun, RunCase.run_id == TestRun.id)
        .where(TestRun.project_id == project_id)
    )
    if run_id is not None:
        cases_q = cases_q.where(RunCase.run_id == run_id)
    cases = list(db.scalars(cases_q).all())

    buckets: dict[str, dict[str, Any]] = {}
    for rc in cases:
        lang = ((rc.case_snapshot or {}).get("language") or "unspecified").lower()
        b = buckets.setdefault(lang, {
            "language": lang, "cases": 0, "passed": 0, "failed": 0,
            "errors": 0, "_latencies": [],
        })
        b["cases"] += 1
        if rc.state == "passed":
            b["passed"] += 1
        elif rc.state == "failed":
            b["failed"] += 1
        elif rc.state == "error":
            b["errors"] += 1
        for tr in rc.traces:
            if tr.outcome == "ok" and tr.latency_ms is not None:
                b["_latencies"].append(tr.latency_ms)

    languages = []
    for b in buckets.values():
        lat = sorted(b.pop("_latencies"))
        scored = b["passed"] + b["failed"]
        languages.append({
            **b,
            "scored_cases": scored,
            "pass_rate": round(b["passed"] / scored, 4) if scored else None,
            "latency_ms": {
                "sample_count": len(lat),
                "median": int(statistics.median(lat)) if lat else None,
                "p95": _percentile(lat, 0.95),
            },
        })
    languages.sort(key=lambda x: (-x["cases"], x["language"]))

    return {
        "scope": {"project_id": str(project_id), "run_id": str(run_id) if run_id else None},
        "languages": languages,
        "pass_rate_definition": "passed / (passed + failed); errored cases excluded",
        "latency_population": "successful inference attempts only",
        "data_source": "computed from run_cases and inference_traces rows; no synthetic data",
        "note": (
            "Language is the value each test case declared, not detected from "
            "the response. A low count in one language means few cases were "
            "written for it, not that the application handles it well."
        ),
    }
