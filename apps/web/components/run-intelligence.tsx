"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, GitCompareArrows, RefreshCw, ShieldAlert } from "lucide-react";
import { api } from "@/lib/api";
import type { Findings, ReleaseGate, Run, RunComparison } from "@/lib/types";
import { Empty, Notice, StatusBadge } from "@/components/workspace";

function useLoad<T>(path: string | null, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) { setData(null); setError(""); return; }
    let active = true;
    setLoading(true); setError("");
    api<T>(path).then(value => active && setData(value)).catch(reason => active && setError(reason.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [path, refreshKey]);
  return { data, loading, error };
}

const percent = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const terminal = (status: string) => !["queued", "running"].includes(status);

export function RunDecision({ run }: { run: Run }) {
  const gate = useLoad<ReleaseGate>(terminal(run.status) ? `/runs/${run.id}/gate` : null);
  const findings = useLoad<Findings>(terminal(run.status) ? `/runs/${run.id}/findings` : null);
  return <div className="evidence-grid">
    <GatePanel gate={gate} />
    <FindingsPanel findings={findings} />
  </div>;
}

function GatePanel({ gate }: { gate: ReturnType<typeof useLoad<ReleaseGate>> }) {
  if (gate.loading) return <section className="card evidence-panel"><p className="section-label">Release gate</p><h2>Reading policy evidence</h2><p className="hint">Applying this project&rsquo;s declared thresholds…</p></section>;
  if (gate.error) return <section className="card evidence-panel"><p className="section-label">Release gate</p><h2>Decision unavailable</h2><Notice error>{gate.error}</Notice></section>;
  if (!gate.data) return null;
  const { verdict, checks, observed, limitations, notes } = gate.data;
  const heading = verdict === "pass" ? "Declared policy met" : verdict === "block" ? "Release blocked" : verdict === "not_configured" ? "Policy not configured" : "Evidence inconclusive";
  return <section className={`card evidence-panel verdict-${verdict}`}>
    <div className="card-head"><div><p className="section-label">Release gate</p><h2>{heading}</h2></div><StatusBadge status={verdict}/></div>
    {notes && <p className="evidence-note">{notes}</p>}
    <div className="gate-observed"><div><span>Pass rate</span><strong>{percent(observed.pass_rate)}</strong></div><div><span>Scored cases</span><strong>{observed.scored_cases}</strong></div><div><span>Errors</span><strong>{observed.errors}</strong></div></div>
    {checks.length ? <div className="gate-check-list">{checks.map(check => { const rate = check.check.includes("pass_rate"); return <div key={check.check}><span className={`check-mark ${check.met ? "met" : "missed"}`}>{check.met ? "Met" : "Missed"}</span><div><strong>{check.check.replaceAll("_", " ")}</strong><small>{check.observed == null ? "No observation" : `${rate ? percent(check.observed) : check.observed} observed · ${rate ? percent(check.threshold) : check.threshold} required`}</small></div></div>; })}</div> : <Link className="btn btn-secondary" href="/projects">Set release thresholds <ArrowRight size={15}/></Link>}
    <div className="gate-limitations"><strong>Decision limits</strong><ul>{limitations.map(item => <li key={item}>{item}</li>)}</ul></div>
  </section>;
}

function FindingsPanel({ findings }: { findings: ReturnType<typeof useLoad<Findings>> }) {
  const [open, setOpen] = useState<string | null>(null);
  if (findings.loading) return <section className="card evidence-panel"><p className="section-label">Shield findings</p><h2>Reading bounded tests</h2><p className="hint">Loading redacted finding evidence…</p></section>;
  if (findings.error) return <section className="card evidence-panel"><p className="section-label">Shield findings</p><h2>Findings unavailable</h2><Notice error>{findings.error}</Notice></section>;
  if (!findings.data) return null;
  return <section className="card evidence-panel findings-panel">
    <div className="card-head"><div><p className="section-label">Shield findings</p><h2>{findings.data.total ? `${findings.data.total} actionable ${findings.data.total === 1 ? "finding" : "findings"}` : "No Shield findings"}</h2></div>{findings.data.total > 0 && <ShieldAlert className="finding-icon" size={24}/>}</div>
    <p className="evidence-note">{findings.data.note}</p>
    {findings.data.findings.length ? <div className="finding-list">{findings.data.findings.map(finding => <article key={finding.run_case_id} className="finding-item">
      <button type="button" onClick={() => setOpen(open === finding.run_case_id ? null : finding.run_case_id)} aria-expanded={open === finding.run_case_id}>
        <span><strong>{finding.case}</strong><small>{finding.category ?? "Uncategorised"}</small></span><span className={`badge ${finding.severity ?? "neutral"}`}>{finding.severity ?? "not rated"}</span>
      </button>
      {open === finding.run_case_id && <div className="finding-detail"><div><span>Why this severity</span><p>{finding.severity_rationale ?? "No severity rationale was recorded."}</p></div><div><span>Observed evidence</span><p>{finding.evidence}</p></div><div className="mitigation"><span>Recommended action</span><p>{finding.mitigation ?? "No mitigation was recorded."}</p></div></div>}
    </article>)}</div> : <Empty title="No failed Shield cases" text="This run produced no actionable Shield findings. That result is bounded to the cases executed and is not a security guarantee."/>}
  </section>;
}

export function RunIteration({ run }: { run: Run }) {
  const candidates = useLoad<Run[]>(`/runs?project_id=${run.project_id}`);
  const [baselineId, setBaselineId] = useState("");
  const [comparisonPath, setComparisonPath] = useState<string | null>(null);
  const comparison = useLoad<RunComparison>(comparisonPath);
  const [retestId, setRetestId] = useState("");
  const [retestRefresh, setRetestRefresh] = useState(0);
  const retest = useLoad<Run>(retestId ? `/runs/${retestId}` : null, retestRefresh);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const fromQuery = new URLSearchParams(window.location.search).get("baseline");
    if (fromQuery && fromQuery !== run.id) { setBaselineId(fromQuery); setComparisonPath(`/runs/${run.id}/compare?baseline_run_id=${fromQuery}`); }
  }, [run.id]);
  useEffect(() => {
    if (retest.data && !terminal(retest.data.status)) {
      const timer = setTimeout(() => setRetestRefresh(value => value + 1), 2500);
      return () => clearTimeout(timer);
    }
  }, [retest.data, retestRefresh]);

  const completed = useMemo(() => (candidates.data ?? []).filter(item => item.id !== run.id && terminal(item.status)), [candidates.data, run.id]);
  const canRetest = terminal(run.status) && run.failed_count + run.error_count > 0;
  async function startRetest() {
    setBusy(true); setMessage("");
    try { const created = await api<{ run_id: string }>(`/runs/${run.id}/retest`, { method: "POST" }); setRetestId(created.run_id); setRetestRefresh(value => value + 1); }
    catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="card iteration-panel">
    <div className="iteration-heading"><div><p className="section-label">Iteration evidence</p><h2>Retest and compare</h2><p>Separate repeatable change from sampling noise before calling a case fixed or regressed.</p></div><GitCompareArrows size={26}/></div>
    {message && <Notice error>{message}</Notice>}
    <div className="iteration-controls">
      <div className="retest-action"><strong>Repeat non-passing cases</strong><span>Failures and infrastructure errors are re-run with current case definitions.</span><button className="btn btn-primary" disabled={!canRetest || busy || Boolean(retestId)} onClick={startRetest}><RefreshCw size={15}/>{busy ? "Starting retest…" : "Retest non-passing cases"}</button>{!canRetest && <small>Nothing to retest in this run.</small>}</div>
      <form className="compare-control" onSubmit={event => { event.preventDefault(); if (baselineId) setComparisonPath(`/runs/${run.id}/compare?baseline_run_id=${baselineId}`); }}><label htmlFor="baseline-run">Compare against</label><select id="baseline-run" className="select" value={baselineId} onChange={event => setBaselineId(event.target.value)} required><option value="">Choose an earlier completed run</option>{completed.map(item => <option key={item.id} value={item.id}>Run {item.id.slice(0, 8)} · {percent(item.pass_rate)}</option>)}</select><button className="btn btn-secondary" disabled={!baselineId || comparison.loading}>{comparison.loading ? "Comparing…" : "Compare runs"}</button></form>
    </div>
    {retest.data && <div className="retest-status"><div><span>Retest {retest.data.id.slice(0, 8)}</span><StatusBadge status={retest.data.status}/></div><p>{retest.data.passed_count} passed · {retest.data.failed_count} failed · {retest.data.error_count} errors</p>{terminal(retest.data.status) && <Link className="btn btn-secondary" href={`/runs/${retest.data.id}?baseline=${run.id}`}>Open retest and compare <ArrowRight size={15}/></Link>}</div>}
    {comparison.error && <Notice error>{comparison.error}</Notice>}
    {comparison.data && <ComparisonView comparison={comparison.data}/>}
  </section>;
}

function ComparisonView({ comparison }: { comparison: RunComparison }) {
  const changedContext = comparison.interpretation.model_changed || comparison.interpretation.scoring_changed;
  const populationsDiffer = (comparison.summary.removed ?? 0) > 0 || (comparison.summary.not_in_this_run ?? 0) > 0 || (comparison.summary.added ?? 0) > 0;
  return <div className="comparison-view">
    {changedContext && <Notice><AlertTriangle size={17}/><div><strong>Comparison context changed.</strong><p>{comparison.interpretation.model_changed ? "The recorded model changed. " : ""}{comparison.interpretation.scoring_changed ? "The scoring version changed." : ""}</p></div></Notice>}
    <div className="comparison-summary"><div><span>Baseline</span><strong>{percent(comparison.baseline.pass_rate)}</strong><small>{comparison.baseline.passed} passed · {comparison.baseline.failed} failed · {comparison.baseline.errors} errors</small></div><div className="delta"><span>Pass-rate change</span><strong>{populationsDiffer || comparison.pass_rate_delta == null ? "—" : `${comparison.pass_rate_delta >= 0 ? "+" : ""}${(comparison.pass_rate_delta * 100).toFixed(1)} pp`}</strong><small>{populationsDiffer ? "Different case populations; delta suppressed" : "Same recorded case population"}</small></div><div><span>Current</span><strong>{percent(comparison.current.pass_rate)}</strong><small>{comparison.current.passed} passed · {comparison.current.failed} failed · {comparison.current.errors} errors</small></div></div>
    {comparison.low_confidence_changes > 0 && <div className="confidence-warning"><AlertTriangle size={17}/><span><strong>{comparison.low_confidence_changes} single-sample {comparison.low_confidence_changes === 1 ? "change" : "changes"}.</strong> Increase repeat count before treating a flip as stable.</span></div>}
    <div className="comparison-cases">{comparison.cases.map((item, index) => <article key={`${item.case}-${index}`} className={`comparison-case ${item.verdict}`}><div><strong>{item.case}</strong><small>{item.engine} · {item.severity ?? "severity not set"}</small></div><div className="comparison-verdict"><StatusBadge status={item.verdict === "removed" ? "not_in_this_run" : item.verdict}/>{item.low_confidence && <span className="low-confidence">Low confidence · repeat {Math.max(item.baseline?.repeat_count ?? 1, item.current?.repeat_count ?? 1)}×</span>}</div></article>)}</div>
  </div>;
}
