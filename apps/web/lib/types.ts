export type Project = { id: string; name: string; description: string | null; app_system_prompt: string | null; gate_min_pass_rate: number | null; gate_max_critical_findings: number | null; owner_id: string; created_at: string };
export type Connection = { id: string; project_id: string; provider: string; endpoint: string; model_id: string; verification_state: string; verification_detail: string | null; verified_at: string | null; created_at: string; credential: string };
export type VerifyResult = { connection_id: string; verified: boolean; state: string; detail: string; outcome: string; model_id: string | null; latency_ms: number | null; upstream_status: number | null; response_excerpt: string | null; checked_at: string };
export type Suite = { id: string; project_id: string; name: string; engine: "guard" | "shield"; version: number; description: string | null; created_at: string; case_count: number };
export type TestCase = { id: string; suite_id: string; name: string; user_prompt: string; system_prompt: string | null; language: string; category: string | null; evaluator_type: string; evaluator_config: Record<string, unknown>; severity: string | null; severity_rationale: string | null; repeat_count: number; version: number };
export type SuiteDetail = Suite & { cases: TestCase[] };
export type Run = { id: string; project_id: string; connection_id: string; status: string; scoring_version: string; model_id: string | null; total_cases: number; passed_count: number; failed_count: number; error_count: number; skipped_count: number; error_summary: string | null; created_at: string; started_at: string | null; completed_at: string | null; pass_rate: number | null; pass_rate_definition: string };
export type Trace = { trace_id: string; attempt: number; outcome: string; upstream_status: number | null; latency_ms: number | null; model_id: string | null; response_text: string | null; error_message: string | null; recorded_at: string | null };
export type RunCase = { run_case_id: string; name: string | null; engine: string | null; category: string | null; severity: string | null; state: string; passed: boolean | null; explanation: string | null; error: string | null; error_kind: string | null; score_metadata: Record<string, unknown>; case_snapshot: Record<string, unknown>; traces: Trace[] };
export type Results = { run_id: string; total: number; limit: number; offset: number; items: RunCase[] };
export type Metrics = {
  scope: { project_id: string; run_id: string | null };
  inference: { attempts: number; successful: number; by_outcome: Record<string, number>; transport_errors: number; auth_errors: number; blocked: number };
  latency_ms: { population: string; sample_count: number; mean: number | null; median: number | null; p95: number | null; min: number | null; max: number | null; note: string };
  results: { runs: number; passed: number; failed: number; errored_not_scored: number; pass_rate: number | null; pass_rate_definition: string };
  models_seen: string[];
  data_source: string;
};
export type ObservabilityTrace = { trace_id: string; run_case_id: string; attempt: number; outcome: string; upstream_status: number | null; latency_ms: number | null; model_id: string | null; endpoint: string; error_message: string | null; recorded_at: string | null };
export type TracePage = { total: number; limit: number; offset: number; items: ObservabilityTrace[] };
export type ReleaseGate = {
  verdict: "pass" | "block" | "not_configured" | "inconclusive";
  run_status: string;
  checks: { check: string; threshold: number; observed: number | null; met: boolean; detail: string | null }[];
  observed: { pass_rate: number | null; passed: number; failed: number; errors: number; scored_cases: number; findings_by_severity: Record<string, number>; pass_rate_definition: string };
  limitations: string[];
  notes: string | null;
};
