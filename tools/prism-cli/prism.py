#!/usr/bin/env python3
"""prism -- ATLAS Prism command line interface.

Puts an evaluation gate inside a release pipeline, which is the difference
between a website someone visits and infrastructure a team depends on.

    prism run   --project <id> --connection <id> --suite <id> [--suite <id>]
    prism gate  --run <id>
    prism compare --run <id> --baseline <id>
    prism export --run <id> --format json --out report.json
    prism verify --connection <id>
    prism projects | suites --project <id> | runs --project <id>

EXIT CODES -- the CI contract. `prism gate` is the command a pipeline runs:

    0   pass            thresholds met; the release may proceed
    1   block           a declared threshold was not met
    2   not_configured  no thresholds set, so no decision was made
    3   inconclusive    the run produced no scored evidence
    4   usage/transport error

`not_configured` is deliberately NOT 0. A pipeline that silently passes because
nobody set a threshold is worse than one that fails loudly.

Standard library only: no install step, and nothing to audit but this file.

AUTHENTICATION
    --token / $PRISM_TOKEN      any deployment (Neon Auth or local)
    --email / --password        local-mode deployments only (AUTH_MODE=local)

    A deployed Prism using Neon Auth will not accept an email/password login
    token for protected routes; pass --token there.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

__version__ = "0.5.0"

EXIT_PASS, EXIT_BLOCK, EXIT_NOT_CONFIGURED, EXIT_INCONCLUSIVE, EXIT_ERROR = 0, 1, 2, 3, 4
TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}


class ApiError(Exception):
    def __init__(self, status: int, body) -> None:
        self.status, self.body = status, body
        msg = body
        if isinstance(body, dict):
            d = body.get("detail")
            msg = d.get("message") if isinstance(d, dict) else d
        super().__init__(f"HTTP {status}: {msg}")


class Client:
    def __init__(self, base: str, token: str | None) -> None:
        self.base = base.rstrip("/")
        if not self.base.endswith("/api/v1"):
            self.base += "/api/v1"
        self.token = token

    def __call__(self, path: str, method: str = "GET", body=None, timeout: int = 300, raw: bool = False):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": f"prism-cli/{__version__}"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
                if raw:
                    return payload
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                raise ApiError(e.code, json.loads(payload))
            except json.JSONDecodeError:
                raise ApiError(e.code, payload[:300].decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            raise ApiError(0, f"cannot reach {url}: {e.reason}")


def login(base: str, email: str, password: str) -> str:
    tok = Client(base, None)("/auth/login", "POST", {"email": email, "password": password}, 60)
    return tok["access_token"]


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


# --------------------------------------------------------------------------- commands

def cmd_projects(api: Client, a) -> int:
    for p in api("/projects"):
        profile = "app profile set" if p.get("app_system_prompt") else "no app profile"
        print(f"{p['id']}  {p['name']}  [{profile}]")
    return EXIT_PASS


def cmd_suites(api: Client, a) -> int:
    for s in api(f"/suites?project_id={a.project}"):
        print(f"{s['id']}  {s['engine']:6}  {s['case_count']:3} cases  {s['name']}")
    return EXIT_PASS


def cmd_runs(api: Client, a) -> int:
    for r in api(f"/runs?project_id={a.project}")[: a.limit]:
        print(f"{r['id']}  {r['status']:20} {r['passed_count']:3}P {r['failed_count']:3}F "
              f"{r['error_count']:3}E  rate={pct(r.get('pass_rate'))}")
    return EXIT_PASS


def cmd_verify(api: Client, a) -> int:
    v = api(f"/connections/{a.connection}/verify", "POST", None, 300)
    ok = bool(v.get("verified"))
    print(f"{'VERIFIED' if ok else 'NOT VERIFIED'}  outcome={v.get('outcome')} "
          f"model={v.get('model_id')} latency={v.get('latency_ms')}ms "
          f"upstream={v.get('upstream_status')}")
    if v.get("detail"):
        print(f"  {v['detail']}")
    return EXIT_PASS if ok else EXIT_BLOCK


def _await_run(api: Client, run_id: str, poll: int, quiet: bool) -> dict:
    last = None
    while True:
        last = api(f"/runs/{run_id}", timeout=60)
        if not quiet:
            print(f"  {last['status']:20} {last['passed_count']}P {last['failed_count']}F "
                  f"{last['error_count']}E", file=sys.stderr)
        if last["status"] in TERMINAL:
            return last
        time.sleep(poll)


def cmd_run(api: Client, a) -> int:
    created = api("/runs", "POST", {
        "project_id": a.project, "connection_id": a.connection,
        "suite_ids": a.suite, "max_concurrency": a.concurrency,
    }, 120)
    run_id = created["run_id"]
    print(f"run {run_id} ({created['total_cases']} cases)", file=sys.stderr)
    if a.no_wait:
        print(run_id)
        return EXIT_PASS
    run = _await_run(api, run_id, a.poll, a.quiet)
    print(f"\n{run['status']}: {run['passed_count']} passed, {run['failed_count']} failed, "
          f"{run['error_count']} errors, pass rate {pct(run.get('pass_rate'))}")
    print(run_id)
    if a.gate:
        print()
        return _print_gate(api(f"/runs/{run_id}/gate"))
    return EXIT_PASS


def _print_gate(g: dict) -> int:
    verdict = g.get("verdict")
    print(f"GATE: {str(verdict).upper()}")
    for c in g.get("checks", []):
        mark = "ok  " if c["met"] else "FAIL"
        print(f"  [{mark}] {c['check']}: observed {c['observed']} against threshold {c['threshold']}")
        if c.get("detail"):
            print(f"         {c['detail']}")
    obs = g.get("observed", {})
    if obs.get("errors"):
        print(f"  note: {obs['errors']} case(s) errored and are excluded from the pass rate, "
              f"so this evidence is incomplete")
    if g.get("notes"):
        print(f"  {g['notes']}")
    return {"pass": EXIT_PASS, "block": EXIT_BLOCK,
            "not_configured": EXIT_NOT_CONFIGURED}.get(verdict, EXIT_INCONCLUSIVE)


def cmd_gate(api: Client, a) -> int:
    return _print_gate(api(f"/runs/{a.run}/gate"))


def cmd_compare(api: Client, a) -> int:
    c = api(f"/runs/{a.run}/compare?baseline_run_id={a.baseline}")
    s = c["summary"]
    print(f"regressed {s['regressed']}  fixed {s['fixed']}  still_passing {s['still_passing']}  "
          f"still_failing {s['still_failing']}  inconclusive {s['inconclusive']}")
    if s.get("not_in_this_run"):
        print(f"  {s['not_in_this_run']} case(s) were not part of this run (not deleted)")
    if c.get("pass_rate_delta") is not None:
        print(f"pass rate delta: {c['pass_rate_delta']:+.4f}")
    elif c.get("pass_rate_delta_note"):
        print(f"pass rate delta: not reported -- {c['pass_rate_delta_note']}")
    if c.get("low_confidence_changes"):
        print(f"WARNING: {c['low_confidence_changes']} change(s) measured from a single "
              f"generation on each side. Generation is sampled; raise repeat_count "
              f"before treating these as real.")
    interp = c.get("interpretation", {})
    if interp.get("model_changed"):
        print("WARNING: the two runs used different model ids; they are not strictly comparable.")
    if interp.get("scoring_changed"):
        print("WARNING: the two runs used different scoring versions.")
    for case in c["cases"]:
        if case["verdict"] in ("regressed", "fixed"):
            flag = " [low confidence]" if case["low_confidence"] else ""
            print(f"  {case['verdict']:10} {case['case']}{flag}")
    # A regression is the thing a pipeline should stop for.
    return EXIT_BLOCK if s["regressed"] else EXIT_PASS


def cmd_findings(api: Client, a) -> int:
    f = api(f"/runs/{a.run}/findings")
    print(f"{f['total']} finding(s): {json.dumps(f['by_severity'])}")
    for x in f["findings"]:
        print(f"\n  [{x['severity']}] {x['case']}  ({x['category']}, rule {x['rule_id']})")
        if x.get("severity_rationale"):
            print(f"    why: {x['severity_rationale']}")
        if x.get("mitigation"):
            print(f"    fix: {x['mitigation']}")
    return EXIT_BLOCK if f["total"] else EXIT_PASS


def cmd_export(api: Client, a) -> int:
    blob = api(f"/reports/{a.run}/export?format={a.format}", timeout=300, raw=True)
    if a.out:
        with open(a.out, "wb") as fh:
            fh.write(blob)
        print(f"wrote {a.out} ({len(blob):,} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(blob.decode("utf-8", "replace"))
    return EXIT_PASS


# --------------------------------------------------------------------------- entry

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="prism", description="ATLAS Prism CLI -- evaluate AI applications from a pipeline.",
        epilog="Exit codes: 0 pass, 1 block, 2 not_configured, 3 inconclusive, 4 error.")
    p.add_argument("--api", default=os.environ.get("PRISM_API", "https://atlas-prism-api.fly.dev"),
                   help="API base URL (env PRISM_API)")
    p.add_argument("--token", default=os.environ.get("PRISM_TOKEN"), help="bearer token (env PRISM_TOKEN)")
    p.add_argument("--email", default=os.environ.get("PRISM_EMAIL"), help="local-mode login")
    p.add_argument("--password", default=os.environ.get("PRISM_PASSWORD"), help="local-mode login")
    p.add_argument("--version", action="version", version=f"prism {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("projects", help="list projects").set_defaults(fn=cmd_projects)

    s = sub.add_parser("suites", help="list suites in a project"); s.set_defaults(fn=cmd_suites)
    s.add_argument("--project", required=True)

    s = sub.add_parser("runs", help="list recent runs"); s.set_defaults(fn=cmd_runs)
    s.add_argument("--project", required=True)
    s.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("verify", help="prove live model access"); s.set_defaults(fn=cmd_verify)
    s.add_argument("--connection", required=True)

    s = sub.add_parser("run", help="execute suites and wait"); s.set_defaults(fn=cmd_run)
    s.add_argument("--project", required=True)
    s.add_argument("--connection", required=True)
    s.add_argument("--suite", action="append", required=True, help="repeatable")
    s.add_argument("--concurrency", type=int, default=1)
    s.add_argument("--poll", type=int, default=10)
    s.add_argument("--no-wait", action="store_true")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--gate", action="store_true", help="evaluate the release gate when it finishes")

    s = sub.add_parser("gate", help="release decision for a run"); s.set_defaults(fn=cmd_gate)
    s.add_argument("--run", required=True)

    s = sub.add_parser("compare", help="diff a run against a baseline"); s.set_defaults(fn=cmd_compare)
    s.add_argument("--run", required=True)
    s.add_argument("--baseline", required=True)

    s = sub.add_parser("findings", help="security findings for a run"); s.set_defaults(fn=cmd_findings)
    s.add_argument("--run", required=True)

    s = sub.add_parser("export", help="download evidence"); s.set_defaults(fn=cmd_export)
    s.add_argument("--run", required=True)
    s.add_argument("--format", choices=["json", "csv"], default="json")
    s.add_argument("--out")

    a = p.parse_args(argv)

    token = a.token
    try:
        if not token and a.email and a.password:
            token = login(a.api, a.email, a.password)
        if not token:
            print("error: no credentials. Pass --token (or $PRISM_TOKEN), or --email/--password "
                  "for a local-mode deployment.", file=sys.stderr)
            return EXIT_ERROR
        return a.fn(Client(a.api, token), a)
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
