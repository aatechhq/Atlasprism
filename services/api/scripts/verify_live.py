"""Live N-ATLAS verification, end to end, with timestamped evidence.

Run this once the inference service is reachable. It proves the integration in
the only way that counts - by driving Prism itself - and writes an evidence
file suitable for the NAIC integration-evidence artifact.

    python -m scripts.verify_live --base-url https://<tunnel-host>

Steps, in order, stopping at the first hard failure:

  1. Reach the inference service directly:  GET /health, GET /v1/models
  2. One direct generation:                 POST /v1/chat/completions
  3. Verify THROUGH Prism:                   POST /api/v1/connections/{id}/verify
  4. Run the baseline suites through Prism:  POST /api/v1/runs  (concurrency 1)
  5. Export the evidence:                    GET  /reports/{id}/export

Nothing here fabricates a result. If a step fails, the evidence file records
the failure and the script exits non-zero. No credential is ever written to the
evidence file - only "configured (****last4)".

Prerequisites: the Prism API running, and NATLAS_BASE_URL / NATLAS_API_KEY /
NATLAS_ALLOWED_HOSTS set in services/api/.env (the API reads them at startup,
so restart it after editing).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PRISM = "http://127.0.0.1:8000"
TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}


def _redact(secret: str | None) -> str:
    if not secret:
        return "not configured"
    s = secret.strip()
    return f"configured (****{s[-4:]})" if len(s) >= 4 else "configured"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _request(url: str, *, method: str = "GET", body=None, headers=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except Exception as exc:  # transport failure
        return None, f"{type(exc).__name__}: {exc}", int((time.perf_counter() - started) * 1000)
    elapsed = int((time.perf_counter() - started) * 1000)
    try:
        return status, json.loads(raw) if raw else None, elapsed
    except ValueError:
        # Not JSON (a CSV export, or an HTML error page). Return it whole and
        # let the caller truncate for display - truncating here once made the
        # evidence file understate a CSV export as 398 bytes.
        return status, raw.decode("utf-8", "replace"), elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", help="Inference service URL, e.g. https://x.trycloudflare.com")
    ap.add_argument("--api-key", help="Inference key. Prefer NATLAS_API_KEY in .env over this flag.")
    ap.add_argument("--prism", default=DEFAULT_PRISM, help=f"Prism API (default {DEFAULT_PRISM})")
    ap.add_argument("--email", help="Prism admin email (default: ADMIN_EMAIL from env)")
    ap.add_argument("--password", help="Prism admin password (default: ADMIN_PASSWORD from env)")
    ap.add_argument("--out", default="docs/integration-evidence",
                    help="Directory for the evidence file")
    ap.add_argument("--skip-run", action="store_true",
                    help="Verify the connection only; do not execute the baseline suites")
    args = ap.parse_args()

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from app.core.config import settings  # noqa: E402  (after sys.path fix)

    base_url = (args.base_url or settings.natlas_base_url or "").rstrip("/")
    api_key = args.api_key or settings.natlas_api_key
    email = args.email or settings.admin_email
    password = args.password or settings.admin_password

    evidence: dict = {
        "artifact": "ATLAS Prism - N-ATLAS live integration evidence",
        "generated_at": _now(),
        "inference_service": {"base_url": base_url, "credential": _redact(api_key)},
        "model_id_requested": settings.natlas_model_id,
        "prism_api": args.prism,
        "steps": [],
        "result": "incomplete",
    }

    def record(name, ok, **detail):
        evidence["steps"].append({"step": name, "ok": bool(ok), "at": _now(), **detail})
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}")
        for k, v in detail.items():
            if v not in (None, "", {}, []):
                text = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                print(f"        {k}: {text[:300]}")

    def finish(ok: bool) -> int:
        evidence["result"] = "verified" if ok else "failed"
        out_dir = pathlib.Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = out_dir / f"natlas-verification-{stamp}.json"
        path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"\nEvidence written to {path}")
        print("RESULT:", evidence["result"].upper())
        return 0 if ok else 1

    print(f"Inference service : {base_url or '(not configured)'}")
    print(f"Credential        : {_redact(api_key)}")
    print(f"Prism API         : {args.prism}\n")

    if not base_url:
        record("preflight", False, error="No base URL. Pass --base-url or set NATLAS_BASE_URL.")
        return finish(False)
    if not api_key:
        record("preflight", False,
               error="No API key. Set NATLAS_API_KEY in services/api/.env. "
                     "Prism reports connections 'blocked' without it - by design.")
        return finish(False)

    auth = {"Authorization": f"Bearer {api_key}"}

    # --- 1. the service itself -------------------------------------------
    status, body, ms = _request(f"{base_url}/health", timeout=120)
    record("inference /health", status == 200, http=status, latency_ms=ms, body=body)
    if status != 200:
        return finish(False)

    status, body, ms = _request(f"{base_url}/v1/models", headers=auth, timeout=120)
    served = None
    if status == 200 and isinstance(body, dict):
        served = (body.get("data") or [{}])[0].get("id")
    record("inference /v1/models", status == 200, http=status, latency_ms=ms,
           served_model=served)
    if status != 200:
        return finish(False)

    # --- 2. one direct generation ----------------------------------------
    status, body, ms = _request(
        f"{base_url}/v1/chat/completions", method="POST", headers=auth, timeout=300,
        body={"model": settings.natlas_model_id,
              "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
              "language": "en", "max_tokens": 32},
    )
    text = body.get("content") if isinstance(body, dict) else None
    record("direct generation", status == 200 and bool(text), http=status, latency_ms=ms,
           reported_model=(body or {}).get("model") if isinstance(body, dict) else None,
           usage=(body or {}).get("usage") if isinstance(body, dict) else None,
           response_excerpt=(text or "")[:280])
    if status != 200 or not text:
        return finish(False)

    # --- 3. verify through Prism -----------------------------------------
    status, tok, ms = _request(f"{args.prism}/api/v1/auth/login", method="POST",
                               body={"email": email, "password": password}, timeout=60)
    if status != 200:
        record("prism login", False, http=status, body=tok,
               hint="Is the Prism API running, and do ADMIN_EMAIL/ADMIN_PASSWORD match the seeded admin?")
        return finish(False)
    record("prism login", True, http=status)
    H = {"Authorization": f"Bearer {tok['access_token']}"}

    status, projects, _ = _request(f"{args.prism}/api/v1/projects", headers=H, timeout=60)
    if status != 200 or not projects:
        record("prism project", False, http=status,
               hint="Run `python -m app.evaluation.seed` first.")
        return finish(False)
    project_id = projects[0]["id"]

    status, conn, _ = _request(f"{args.prism}/api/v1/connections", method="POST", headers=H,
                               body={"project_id": project_id, "endpoint": base_url}, timeout=60)
    if status != 201:
        record("prism connection", False, http=status, body=conn,
               hint="A 400 here usually means the host is not in NATLAS_ALLOWED_HOSTS.")
        return finish(False)
    connection_id = conn["id"]
    record("prism connection", True, connection_id=connection_id,
           endpoint=conn["endpoint"], credential=conn["credential"])

    status, ver, ms = _request(f"{args.prism}/api/v1/connections/{connection_id}/verify",
                               method="POST", headers=H, timeout=300)
    verified = bool(status == 200 and ver and ver.get("verified"))
    record("PRISM -> N-ATLAS VERIFY", verified, http=status, latency_ms=ms,
           state=(ver or {}).get("state"), outcome=(ver or {}).get("outcome"),
           model_id=(ver or {}).get("model_id"),
           reported_latency_ms=(ver or {}).get("latency_ms"),
           detail=(ver or {}).get("detail"),
           response_excerpt=(ver or {}).get("response_excerpt"))
    if not verified:
        return finish(False)
    evidence["integration"] = {
        "verified": True,
        "verified_at": _now(),
        "model_id": (ver or {}).get("model_id"),
        "latency_ms": (ver or {}).get("latency_ms"),
        "upstream_status": (ver or {}).get("upstream_status"),
        "note": "A real authenticated generation made by Prism itself, not a health check.",
    }

    if args.skip_run:
        return finish(True)

    # --- 4. the baseline suites, through Prism ---------------------------
    status, suites, _ = _request(f"{args.prism}/api/v1/suites?project_id={project_id}",
                                 headers=H, timeout=60)
    suite_ids = [s["id"] for s in (suites or [])]
    if not suite_ids:
        record("baseline suites", False, hint="Seed them: python -m app.evaluation.seed")
        return finish(False)
    record("baseline suites", True,
           suites=[f"{s['name']} ({s['engine']}, {s['case_count']} cases)" for s in suites])

    # concurrency 1: a T4 holding an 8B model generates strictly one at a time.
    status, run, _ = _request(f"{args.prism}/api/v1/runs", method="POST", headers=H, timeout=120,
                              body={"project_id": project_id, "connection_id": connection_id,
                                    "suite_ids": suite_ids, "max_concurrency": 1})
    if status != 202:
        record("launch run", False, http=status, body=run)
        return finish(False)
    run_id = run["run_id"]
    total = run["total_cases"]
    record("launch run", True, run_id=run_id, total_cases=total, status=run["status"])

    print(f"\n        executing {total} cases at concurrency 1 "
          f"(~8s per generation on a T4, so allow several minutes)...")
    deadline = time.time() + 3600
    last = None
    while time.time() < deadline:
        status, last, _ = _request(f"{args.prism}/api/v1/runs/{run_id}", headers=H, timeout=60)
        if status != 200:
            record("poll run", False, http=status)
            return finish(False)
        done = last["passed_count"] + last["failed_count"] + last["error_count"] + last["skipped_count"]
        print(f"        {last['status']:20} {done}/{total}  "
              f"passed={last['passed_count']} failed={last['failed_count']} "
              f"errors={last['error_count']}")
        if last["status"] in TERMINAL:
            break
        time.sleep(10)

    record("run finished", last["status"] in {"completed", "partially_completed"},
           status=last["status"], passed=last["passed_count"], failed=last["failed_count"],
           errored_not_scored=last["error_count"], pass_rate=last["pass_rate"],
           pass_rate_definition=last["pass_rate_definition"],
           error_summary=last["error_summary"])
    evidence["run"] = {k: last[k] for k in
                       ("id", "status", "total_cases", "passed_count", "failed_count",
                        "error_count", "pass_rate", "pass_rate_definition",
                        "scoring_version", "model_id", "started_at", "completed_at")}

    # --- 5. Pulse + exports ----------------------------------------------
    status, metrics, _ = _request(
        f"{args.prism}/api/v1/metrics/summary?project_id={project_id}&run_id={run_id}",
        headers=H, timeout=60)
    if status == 200:
        record("pulse metrics", True, inference=metrics["inference"],
               latency_ms=metrics["latency_ms"])
        evidence["pulse"] = metrics

    for fmt in ("json", "csv"):
        status, payload, _ = _request(
            f"{args.prism}/api/v1/reports/{run_id}/export?format={fmt}", headers=H, timeout=180)
        size = len(json.dumps(payload)) if isinstance(payload, (dict, list)) else len(payload or "")
        record(f"export {fmt}", status == 200, http=status, bytes=size)

    ok = last["status"] in {"completed", "partially_completed"} and last["passed_count"] > 0
    return finish(ok)


if __name__ == "__main__":
    raise SystemExit(main())
