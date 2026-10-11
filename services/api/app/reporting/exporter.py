"""Evidence exports (PRD 10 / build path G).

Both formats carry the run id, suite and case snapshots, the scoring rules
applied, outcomes, model details, traces and an explicit limitations block.
Neither ever contains a credential: the only secret-shaped values in the system
are the FAKE seeded literals in Shield cases, and those are redacted here too.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.runner import pass_rate
from app.evaluation.scoring import SCORING_VERSION
from app.models import InferenceTrace, ModelConnection, RunCase, TestRun

REDACTED = "<redacted>"


def _seeded_literals(snapshot: dict[str, Any]) -> list[str]:
    """Every literal this case declared as a seeded secret.

    These strings must not appear ANYWHERE in an export - not in the snapshot's
    own system prompt (where the case planted them), not in the model's
    response, not in a finding's evidence. Longest first so masking a long
    variant cannot be broken up by a shorter overlapping one.
    """
    config = (snapshot or {}).get("evaluator_config") or {}
    seeds = [s for s in (config.get("seeded_secrets") or []) if isinstance(s, str) and s]
    return sorted(set(seeds), key=len, reverse=True)


def _mask(text: str | None, seeds: list[str]) -> str | None:
    """Replace each seeded literal with the redaction marker."""
    if not text or not seeds:
        return text
    out = text
    for seed in seeds:
        if seed in out:
            out = out.replace(seed, REDACTED)
        # Case-insensitive sweep for the same literal in another casing.
        lowered = out.lower()
        needle = seed.lower()
        while needle in lowered:
            i = lowered.index(needle)
            out = out[:i] + REDACTED + out[i + len(seed):]
            lowered = out.lower()
    return out


def _redact_seeded(config: dict[str, Any] | None) -> dict[str, Any]:
    """Keep the shape of an evaluator config, drop seeded literal values."""
    if not config:
        return {}
    out = dict(config)
    if "seeded_secrets" in out:
        seeds = out["seeded_secrets"] or []
        out["seeded_secrets"] = [REDACTED for _ in seeds]
        out["seeded_secrets_count"] = len(seeds)
    return out


def _case_payload(rc: RunCase, traces: list[InferenceTrace]) -> dict[str, Any]:
    raw = dict(rc.case_snapshot or {})
    seeds = _seeded_literals(raw)

    snap = dict(raw)
    snap["evaluator_config"] = _redact_seeded(raw.get("evaluator_config"))
    # The case planted the seeded literal in its own prompts; mask it there too.
    snap["system_prompt"] = _mask(snap.get("system_prompt"), seeds)
    snap["user_prompt"] = _mask(snap.get("user_prompt"), seeds)
    if seeds:
        snap["seeded_secrets_redacted"] = True

    return {
        "run_case_id": str(rc.id),
        "name": snap.get("name"),
        "engine": snap.get("engine"),
        "category": snap.get("category"),
        "severity": snap.get("severity"),
        "state": rc.state,
        "passed": rc.passed,
        "explanation": _mask(rc.explanation, seeds),
        "error": _mask(rc.error, seeds),
        "error_kind": rc.error_kind,
        "scoring": rc.score_metadata or {},
        "case_snapshot": snap,
        "findings": [
            {
                "category": f.category,
                "severity": f.severity,
                "rule_id": f.rule_id,
                "evidence": _mask(f.evidence, seeds),
                "mitigation": f.mitigation,
                "severity_rationale": f.severity_rationale,
            }
            for f in (rc.findings or [])
        ],
        "traces": [
            {
                "attempt": t.attempt,
                "outcome": t.outcome,
                "upstream_status": t.upstream_status,
                "latency_ms": t.latency_ms,
                "model_id": t.model_id,
                "endpoint": t.endpoint,
                # A disclosed seeded literal is masked here: the FACT of the
                # leak is in `scoring.leaked_identifiers`, and an export must
                # not become the thing that distributes the secret.
                "response_text": _mask(t.response_text, seeds),
                "error_message": _mask(t.error_message, seeds),
                "request_metadata": t.request_metadata,
                "response_metadata": t.response_metadata,
                "recorded_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in sorted(traces, key=lambda x: (x.attempt, x.created_at or dt.datetime.min))
        ],
    }


def build_report(db: Session, run: TestRun) -> dict[str, Any]:
    cases = list(db.scalars(select(RunCase).where(RunCase.run_id == run.id)).all())
    traces = list(db.scalars(
        select(InferenceTrace).where(InferenceTrace.run_case_id.in_([c.id for c in cases]))
    ).all()) if cases else []
    by_case: dict[uuid.UUID, list[InferenceTrace]] = {}
    for t in traces:
        by_case.setdefault(t.run_case_id, []).append(t)

    conn = db.get(ModelConnection, run.connection_id)
    live_verified = bool(conn and conn.verification_state == "verified")
    ok_traces = [t for t in traces if t.outcome == "ok"]

    return {
        "report_version": "1.0.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run": {
            "run_id": str(run.id),
            "project_id": str(run.project_id),
            "status": run.status,
            "scoring_version": run.scoring_version or SCORING_VERSION,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_summary": run.error_summary,
            "max_concurrency": run.max_concurrency,
        },
        "model": {
            "requested_model_id": run.model_id,
            "endpoint": conn.endpoint if conn else None,
            "provider": conn.provider if conn else None,
            "credential": "server-side; never included in an export",
            "connection_verification_state": conn.verification_state if conn else "unknown",
            "live_inference_verified": live_verified,
        },
        "totals": {
            "total_cases": run.total_cases,
            "passed": run.passed_count,
            "failed": run.failed_count,
            "errored_not_scored": run.error_count,
            "skipped": run.skipped_count,
            "pass_rate": pass_rate(run.passed_count, run.failed_count),
            "pass_rate_definition": "passed / (passed + failed); errored cases are excluded",
            "inference_attempts_recorded": len(traces),
            "successful_inference_attempts": len(ok_traces),
        },
        "suites": run.suite_snapshot or {},
        "cases": [_case_payload(c, by_case.get(c.id, [])) for c in
                  sorted(cases, key=lambda c: (c.case_snapshot or {}).get("name") or "")],
        "limitations": [
            "Results are test outcomes against specific, bounded cases. They are "
            "not a security guarantee and not a general accuracy claim.",
            "Errored cases produced no scorable response and are excluded from the "
            "pass-rate denominator; they are reported separately.",
            "Live model output is nondeterministic: re-running this suite may "
            "produce different generations. Reproducibility here means the inputs, "
            "rules and recorded evidence are fixed, not that the model repeats itself.",
            "Latency figures are measured client-side and include network time.",
            ("Live N-ATLAS inference was NOT verified for this run's connection; "
             "treat all model-dependent results accordingly."
             if not live_verified else
             "Live N-ATLAS inference was verified for this connection by a real "
             "authenticated generation call."),
        ],
    }


CSV_COLUMNS = [
    "run_id", "run_case_id", "case_name", "engine", "category", "severity",
    "state", "passed", "rule", "scoring_version", "attempts",
    "successful_attempts", "errored_attempts", "latency_ms_first_attempt",
    "upstream_status_first_attempt", "model_id", "explanation", "error_kind",
    "error", "response_text_first_attempt",
]


def build_csv(report: dict[str, Any]) -> str:
    """UTF-8 CSV, one row per case. Quoting handles embedded newlines/commas."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL,
                            lineterminator="\r\n", extrasaction="ignore")
    writer.writeheader()
    run_id = report["run"]["run_id"]
    for case in report["cases"]:
        traces = case.get("traces") or []
        first = traces[0] if traces else {}
        scoring = case.get("scoring") or {}
        writer.writerow({
            "run_id": run_id,
            "run_case_id": case.get("run_case_id"),
            "case_name": case.get("name"),
            "engine": case.get("engine"),
            "category": case.get("category"),
            "severity": case.get("severity"),
            "state": case.get("state"),
            "passed": "" if case.get("passed") is None else case["passed"],
            "rule": scoring.get("rule"),
            "scoring_version": scoring.get("scoring_version"),
            "attempts": scoring.get("attempts"),
            "successful_attempts": scoring.get("successful_attempts"),
            "errored_attempts": scoring.get("errored_attempts"),
            "latency_ms_first_attempt": first.get("latency_ms"),
            "upstream_status_first_attempt": first.get("upstream_status"),
            "model_id": first.get("model_id"),
            "explanation": case.get("explanation"),
            "error_kind": case.get("error_kind"),
            "error": case.get("error"),
            "response_text_first_attempt": first.get("response_text"),
        })
    return buf.getvalue()
