"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, ArrowRight, BarChart3, Check, Clipboard, Download, FileDown, Filter, Gauge, Play, Plus, RefreshCw, Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, TerminalSquare, Unplug, XCircle } from "lucide-react";
import { api, download } from "@/lib/api";
import type { Connection, Finding, Findings, LanguageMetrics, Metrics, Project, ReleaseGate, Results, Run, RunCase, Suite, TracePage, VerifyResult } from "@/lib/types";
import { Empty, Notice, StatusBadge, useWorkspace } from "@/components/workspace";
import { EndpointOwnership } from "@/components/endpoint-ownership";
import { RunDecision, RunIteration } from "@/components/run-intelligence";
import { ContinueBar, FlowHeader, formatDate, Kpi, percent, ReadinessLine, RunLedger, useResource } from "@/components/workflow-ui";

export function WorkflowDashboard() {
  const { project, loading, error } = useWorkspace();
  const connections = useResource<Connection[]>(project ? `/connections?project_id=${project.id}` : null);
  const suites = useResource<Suite[]>(project ? `/suites?project_id=${project.id}` : null);
  const runs = useResource<Run[]>(project ? `/runs?project_id=${project.id}` : null);
  const metrics = useResource<Metrics>(project ? `/metrics/summary?project_id=${project.id}` : null);
  const completed = runs.data?.filter(run => !["queued", "running"].includes(run.status)) ?? [];
  const latest = completed[0] ?? null;
  const gate = useResource<ReleaseGate>(latest ? `/runs/${latest.id}/gate` : null);
  const profileReady = Boolean(project?.app_system_prompt?.trim());
  const connectionReady = Boolean(connections.data?.some(item => item.verification_state === "verified"));
  const guardReady = Boolean(suites.data?.some(item => item.engine === "guard" && item.case_count > 0));
  const shieldReady = Boolean(suites.data?.some(item => item.engine === "shield" && item.case_count > 0));
  const next = !profileReady ? { href: "/projects", label: "Finish project setup" } : !connectionReady ? { href: "/projects", label: "Verify a connection" } : !(guardReady && shieldReady) ? { href: "/suites", label: "Prepare test suites" } : !latest ? { href: "/runs", label: "Run first evaluation" } : { href: `/results/${latest.id}`, label: "Inspect latest evidence" };

  return <>
    <FlowHeader title={project?.name ?? "Evaluation workspace"} description="One evidence trail from application rules to an exportable release decision." actions={<Link className="btn btn-primary" href={next.href}>{next.label}<ArrowRight size={16}/></Link>}/>
    {error && <Notice error>{error}</Notice>}
    {!loading && !project ? <Empty title="Create a project to begin" text="A project keeps its model connection, test suites, runs and reports inside one evaluation scope." action={<Link className="btn btn-primary" href="/projects"><Plus size={16}/>Create project</Link>}/> : project && <>
      <section className="command-deck">
        <div className="card evidence-spine-card">
          <div className="section-heading"><div><span>Evaluation spine</span><h2>Move only when the evidence is ready</h2></div><strong>{[profileReady, connectionReady, guardReady && shieldReady, Boolean(latest)].filter(Boolean).length}/4</strong></div>
          <div className="readiness-lines">
            <ReadinessLine ready={profileReady} title="Application scope" detail={profileReady ? "Rules will be frozen into each run." : "Define the assistant and its non-negotiable rules."} href="/projects"/>
            <ReadinessLine ready={connectionReady} title="Verified inference" detail={connectionReady ? "A real generation has succeeded." : "Connect N-ATLAS or a verified endpoint."} href="/projects"/>
            <ReadinessLine ready={guardReady && shieldReady} title="Guard and Shield" detail={guardReady && shieldReady ? "Both evaluation lenses contain runnable cases." : "Prepare quality and bounded security cases."} href="/suites"/>
            <ReadinessLine ready={Boolean(latest)} title="Persisted evidence" detail={latest ? `Latest terminal run ${latest.id.slice(0, 8)}.` : "Execute and preserve the first evaluation."} href={latest ? `/results/${latest.id}` : "/runs"}/>
          </div>
        </div>
        <section className={`card decision-card decision-${gate.data?.verdict ?? "not_configured"}`}>
          <div className="section-heading"><div><span>Latest decision</span><h2>{!latest ? "No release evidence yet" : gate.loading ? "Reading release policy" : verdictTitle(gate.data?.verdict)}</h2></div>{gate.data && <StatusBadge status={gate.data.verdict}/>}</div>
          <p>{!latest ? "Complete the workflow to produce a policy decision backed by case evidence." : gate.data?.notes ?? "The decision applies only to this run and this project's declared thresholds."}</p>
          {gate.data?.checks.length ? <div className="decision-checks">{gate.data.checks.map(check => <div key={check.check}><span>{check.check.replaceAll("_", " ")}</span><strong>{check.met ? "met" : "missed"}</strong></div>)}</div> : null}
          <Link className="text-action" href={latest ? `/results/${latest.id}` : "/projects"}>{latest ? "Open decision evidence" : "Start configuration"}<ArrowRight size={14}/></Link>
        </section>
      </section>
      <div className="kpi-strip">
        <Kpi label="Terminal runs" value={String(completed.length)} note={`${runs.data?.length ?? 0} recorded`}/>
        <Kpi label="Observed pass rate" value={percent(metrics.data?.results.pass_rate)} note={`${(metrics.data?.results.passed ?? 0) + (metrics.data?.results.failed ?? 0)} scored cases`} tone="guard"/>
        <Kpi label="Inference errors" value={String(metrics.data?.results.errored_not_scored ?? 0)} note="Excluded from pass rate" tone="shield"/>
        <Kpi label="p95 latency" value={metrics.data?.latency_ms.p95 == null ? "—" : `${Math.round(metrics.data.latency_ms.p95)} ms`} note={`${metrics.data?.latency_ms.sample_count ?? 0} successful attempts`} tone="pulse"/>
      </div>
      <section className="card ledger-card"><div className="section-heading"><div><span>Run ledger</span><h2>Recent evaluations</h2></div><Link className="text-action" href="/results">All evidence<ArrowRight size={14}/></Link></div>{runs.loading ? <p className="hint">Loading persisted runs…</p> : runs.data?.length ? <RunLedger runs={runs.data.slice(0, 6)}/> : <Empty title="No runs recorded" text="When the model and suites are ready, start a bounded evaluation." action={<Link className="btn btn-primary" href="/runs">Configure run</Link>}/>}</section>
    </>}
  </>;
}

export function ProjectFlowScreen() {
  const { projects, project, loading, setProjectId, refresh } = useWorkspace();
  const [refreshKey, setRefreshKey] = useState(0);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const connections = useResource<Connection[]>(project ? `/connections?project_id=${project.id}` : null, refreshKey);
  const verified = connections.data?.some(item => item.verification_state === "verified") ?? false;
  useEffect(() => { if (!loading && projects.length === 0) setCreating(true); }, [loading, projects.length]);

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const form = event.currentTarget; const data = new FormData(form);
    try {
      const created = await api<Project>("/projects", { method: "POST", body: JSON.stringify({ name: data.get("name"), description: data.get("description") || null, app_system_prompt: data.get("app_system_prompt") || null }) });
      await refresh(); setProjectId(created.id); form.reset(); setCreating(false); setMessage("Project created. Configure its connection next."); setError(false);
    } catch (reason) { setMessage((reason as Error).message); setError(true); }
    finally { setBusy(false); }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!project) return; setBusy(true); setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      await api(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ name: data.get("name"), description: data.get("description") || null, app_system_prompt: data.get("app_system_prompt") || null, gate_min_pass_rate: data.get("gate_min_pass_rate") ? Number(data.get("gate_min_pass_rate")) / 100 : null, gate_max_critical_findings: data.get("gate_max_critical_findings") === "" ? null : Number(data.get("gate_max_critical_findings")) }) });
      await refresh(); setMessage("Project scope and release policy saved."); setError(false);
    } catch (reason) { setMessage((reason as Error).message); setError(true); }
    finally { setBusy(false); }
  }

  async function addNatlas(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!project) return; setBusy(true); setMessage("");
    const data = new FormData(event.currentTarget);
    try {
      await api("/connections", { method: "POST", body: JSON.stringify({ project_id: project.id, provider: "natlas", endpoint: data.get("endpoint") || null, model_id: data.get("model_id") || null }) });
      setRefreshKey(value => value + 1); setMessage("Connection saved. Run a real inference verification before continuing."); setError(false);
    } catch (reason) { setMessage((reason as Error).message); setError(true); }
    finally { setBusy(false); }
  }

  return <>
    <FlowHeader step={1} title="Configure the evaluation scope" description="Choose one project, define the application under test, then prove that its model connection works." actions={<button className="btn btn-secondary" onClick={() => setCreating(value => !value)}><Plus size={15}/>{creating ? "Close create form" : "New project"}</button>}/>
    {message && <Notice error={error}>{message}</Notice>}
    <div className="project-console">
      <aside className="project-index card"><div className="section-heading"><div><span>Projects</span><h2>Evaluation scopes</h2></div><strong>{projects.length}</strong></div>{projects.length ? <div className="project-switch-list">{projects.map((item, index) => <button key={item.id} type="button" className={item.id === project?.id ? "active" : ""} onClick={() => setProjectId(item.id)}><span>{String(index + 1).padStart(2, "0")}</span><span><strong>{item.name}</strong><small>{item.description || "No description"}</small></span>{item.id === project?.id && <Check size={15}/>}</button>)}</div> : <p className="hint">No project exists yet.</p>}</aside>
      <div className="project-workspace">
        {creating && <section className="card project-create-panel"><div className="section-heading"><div><span>New scope</span><h2>Create a project</h2></div><XCircle size={19}/></div><form className="form" onSubmit={createProject}><div className="form-row"><div className="field"><label htmlFor="new-project-name">Project name</label><input className="input" id="new-project-name" name="name" required maxLength={200}/></div><div className="field"><label htmlFor="new-project-description">Purpose</label><input className="input" id="new-project-description" name="description" maxLength={5000}/></div></div><div className="field"><label htmlFor="new-project-prompt">Application instructions</label><textarea className="textarea" id="new-project-prompt" name="app_system_prompt" maxLength={20000} placeholder="Describe the assistant's role, boundaries and rules."/><p className="hint">These instructions are frozen into every run and become part of its evidence.</p></div><button className="btn btn-primary" disabled={busy}>{busy ? "Creating…" : "Create project"}</button></form></section>}
        {!project ? <Empty title="Choose or create a project" text="The selected project controls every connection, suite, run and export shown in Prism."/> : <>
          <section className="card setup-panel"><div className="setup-panel-head"><span className="setup-number">01</span><div><h2>Application and policy</h2><p>State what is being evaluated and what must be true before release.</p></div><StatusBadge status={project.app_system_prompt ? "configured" : "incomplete"}/></div><form className="form" key={project.id} onSubmit={saveProfile}><div className="form-row"><div className="field"><label htmlFor="profile-name">Project name</label><input className="input" id="profile-name" name="name" defaultValue={project.name} required/></div><div className="field"><label htmlFor="profile-description">Purpose</label><input className="input" id="profile-description" name="description" defaultValue={project.description ?? ""}/></div></div><div className="field"><label htmlFor="profile-prompt">Application system prompt</label><textarea className="textarea scope-prompt" id="profile-prompt" name="app_system_prompt" defaultValue={project.app_system_prompt ?? ""} placeholder="Define the assistant's role and non-negotiable rules."/><p className="hint">Guard measures adherence to these rules. Shield attempts bounded overrides using pre-authored cases.</p></div><div className="form-row"><div className="field"><label htmlFor="gate-rate">Minimum pass rate (%)</label><input className="input" id="gate-rate" name="gate_min_pass_rate" type="number" min="0" max="100" step="0.1" defaultValue={project.gate_min_pass_rate == null ? "" : project.gate_min_pass_rate * 100}/></div><div className="field"><label htmlFor="gate-critical">Maximum critical findings</label><input className="input" id="gate-critical" name="gate_max_critical_findings" type="number" min="0" defaultValue={project.gate_max_critical_findings ?? ""}/></div></div><button className="btn btn-secondary" disabled={busy}>Save scope and policy</button></form></section>
          <section className="card setup-panel"><div className="setup-panel-head"><span className="setup-number">02</span><div><h2>Model connection</h2><p>Save an authorized endpoint, then prove it with a real generation.</p></div><StatusBadge status={verified ? "verified" : connections.data?.length ? "unverified" : "not configured"}/></div><form className="connection-inline" onSubmit={addNatlas}><div className="field"><label htmlFor="natlas-endpoint">N-ATLAS endpoint</label><input className="input mono" id="natlas-endpoint" name="endpoint" type="url" placeholder="Use server-managed default if blank"/></div><div className="field"><label htmlFor="natlas-model">Model ID</label><input className="input mono" id="natlas-model" name="model_id" placeholder="NCAIR1/N-ATLaS"/></div><button className="btn btn-secondary" disabled={busy}>Save connection</button></form>{connections.error && <Notice error>{connections.error}</Notice>}<div className="connection-ledger">{connections.data?.map(item => <ConnectionRecord key={item.id} connection={item} onVerified={() => setRefreshKey(value => value + 1)}/>)}</div>{!connections.loading && !connections.data?.length && <p className="inline-reason">No connection saved. Evaluations remain locked until a real inference verification succeeds.</p>}</section>
          <details className="owned-endpoint-disclosure"><summary>Connect a developer-owned OpenAI-compatible endpoint</summary><EndpointOwnership project={project}/></details>
        </>}
      </div>
    </div>
    {project && <ContinueBar title={verified ? "Design the test suites" : "Verify inference before continuing"} description={verified ? "The model is ready. Define the Guard and Shield cases that will produce evidence." : "A saved URL is not proof of integration. Run the genuine inference check above."} href={verified ? "/suites" : "/projects"} action={verified ? "Continue to suites" : "Connection required"}/>} 
  </>;
}

function ConnectionRecord({ connection, onVerified }: { connection: Connection; onVerified: () => void }) {
  const [result, setResult] = useState<VerifyResult | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function verify() { setBusy(true); setError(""); try { const value = await api<VerifyResult>(`/connections/${connection.id}/verify`, { method: "POST" }); setResult(value); onVerified(); } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); } }
  const state = result?.state ?? connection.verification_state;
  return <article className="connection-record"><div><span className="connection-provider">{connection.provider.replaceAll("_", " ")}</span><strong>{connection.model_id}</strong><small className="mono">{connection.endpoint}</small></div><StatusBadge status={state}/>{result && <div className="verification-proof"><strong>Observed response</strong><p>{result.response_excerpt ?? "No response excerpt returned."}</p><small>{result.detail} · {result.latency_ms ?? "—"} ms</small></div>}{error && <Notice error>{error}</Notice>}<button className="btn btn-secondary" onClick={verify} disabled={busy}><RefreshCw size={14}/>{busy ? "Verifying real inference…" : state === "verified" ? "Verify again" : "Verify inference"}</button></article>;
}

export function RunnerScreen() {
  const { project } = useWorkspace(); const router = useRouter();
  const connections = useResource<Connection[]>(project ? `/connections?project_id=${project.id}` : null);
  const suites = useResource<Suite[]>(project ? `/suites?project_id=${project.id}` : null);
  const runs = useResource<Run[]>(project ? `/runs?project_id=${project.id}` : null);
  const verified = connections.data?.filter(item => item.verification_state === "verified") ?? [];
  const [connectionId, setConnectionId] = useState(""); const [selected, setSelected] = useState<string[]>([]); const [concurrency, setConcurrency] = useState(1); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  useEffect(() => { if (!connectionId && verified[0]) setConnectionId(verified[0].id); }, [verified, connectionId]);
  useEffect(() => { const id = new URLSearchParams(window.location.search).get("suite"); if (id) setSelected([id]); }, []);
  const chosen = suites.data?.filter(item => selected.includes(item.id)) ?? [];
  const caseCount = chosen.reduce((sum, item) => sum + item.case_count, 0);
  const reason = !project ? "Select a project first." : !verified.length ? "Verify a model connection first." : !suites.data?.length ? "Create at least one suite." : !selected.length ? "Select one or more suites." : caseCount === 0 ? "Selected suites contain no cases." : "";

  async function launch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!project || reason || busy) return; setBusy(true); setMessage("");
    try { const run = await api<{ run_id: string }>("/runs", { method: "POST", body: JSON.stringify({ project_id: project.id, connection_id: connectionId, suite_ids: selected, max_concurrency: concurrency }) }); router.push(`/runs/${run.run_id}`); }
    catch (failure) { setMessage((failure as Error).message); setBusy(false); }
  }

  return <>
    <FlowHeader step={3} title="Run the evaluation" description="Confirm the target and test population, then create one persisted run. Every selected case makes real inference calls."/>
    {message && <Notice error>{message}</Notice>}
    <form className="runner-console" onSubmit={launch}>
      <section className="card runner-config"><div className="setup-panel-head"><span className="setup-number">01</span><div><h2>Verified target</h2><p>Only connections proven by real inference are available.</p></div></div>{verified.length ? <div className="choice-list">{verified.map(item => <label key={item.id} className={connectionId === item.id ? "selected" : ""}><input type="radio" name="connection" value={item.id} checked={connectionId === item.id} onChange={() => setConnectionId(item.id)}/><span><strong>{item.model_id}</strong><small className="mono">{item.endpoint}</small></span><StatusBadge status="verified"/></label>)}</div> : <Empty icon={Unplug} title="No verified connection" text="Return to Configure and run a genuine inference verification." action={<Link className="btn btn-secondary" href="/projects">Configure connection</Link>}/>}</section>
      <section className="card runner-suites"><div className="setup-panel-head"><span className="setup-number">02</span><div><h2>Test population</h2><p>Select Guard and Shield suites. Empty suites cannot run.</p></div><span className="selection-count">{caseCount} cases</span></div>{suites.data?.length ? <div className="suite-choice-grid">{suites.data.map(item => <label key={item.id} className={`${selected.includes(item.id) ? "selected" : ""} ${item.case_count === 0 ? "disabled" : ""}`}><input type="checkbox" value={item.id} checked={selected.includes(item.id)} disabled={item.case_count === 0} onChange={event => setSelected(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))}/><span className={`suite-engine ${item.engine}`}>{item.engine}</span><strong>{item.name}</strong><small>{item.case_count} cases · v{item.version}</small></label>)}</div> : <Empty title="No suites available" text="Create Guard or Shield cases before launching an evaluation." action={<Link className="btn btn-secondary" href="/suites">Design suites</Link>}/>}</section>
      <aside className="card launch-summary"><div className="setup-panel-head"><span className="setup-number">03</span><div><h2>Launch summary</h2><p>Review the cost-bearing action.</p></div></div><dl><div><dt>Project</dt><dd>{project?.name ?? "Not selected"}</dd></div><div><dt>Connection</dt><dd>{verified.find(item => item.id === connectionId)?.model_id ?? "Not selected"}</dd></div><div><dt>Suites</dt><dd>{selected.length}</dd></div><div><dt>Model calls</dt><dd>{caseCount} minimum</dd></div></dl><div className="field"><label htmlFor="run-concurrency">Bounded concurrency</label><select id="run-concurrency" className="select" value={concurrency} onChange={event => setConcurrency(Number(event.target.value))}><option value={1}>1 · safest</option><option value={2}>2</option><option value={3}>3</option><option value={4}>4</option></select></div><button className="btn btn-primary launch-button" disabled={Boolean(reason) || busy}><Play size={16}/>{busy ? "Creating run…" : "Start evaluation"}</button>{reason && <p className="disabled-reason">{reason}</p>}<p className="run-cost-note">Prism records real model responses, latency and scoring evidence. Starting twice creates two runs.</p></aside>
    </form>
    {runs.data?.length ? <section className="card ledger-card"><div className="section-heading"><div><span>Run ledger</span><h2>Recent activity</h2></div></div><RunLedger runs={runs.data.slice(0, 5)}/></section> : null}
  </>;
}

export function RunMonitorScreen({ runId }: { runId: string }) {
  const [refresh, setRefresh] = useState(0); const run = useResource<Run>(`/runs/${runId}`, refresh);
  const [misses, setMisses] = useState(0);
  // useResource keeps the last good value when a request fails, so progress
  // already on screen stays on screen.
  const terminal = Boolean(run.data && !["queued", "running"].includes(run.data.status));
  // Poll until the run reaches a terminal state, scheduling the next attempt
  // only once the previous one settles -- so a slow API is waited for rather
  // than piled onto. Crucially this does NOT stop on failure: the old version
  // keyed off run.data, so a run whose every poll timed out never advanced and
  // the page sat behind an error until someone pressed Refresh by hand.
  useEffect(() => {
    if (terminal || run.loading) return;
    const timer = window.setTimeout(() => setRefresh(value => value + 1), 5000);
    return () => window.clearTimeout(timer);
  }, [terminal, run.loading, refresh]);
  // Count consecutive failures so a transient miss reads as "still working"
  // and only a sustained outage is reported as a problem.
  useEffect(() => {
    if (run.loading) return;
    setMisses(previous => (run.error ? previous + 1 : 0));
  }, [run.loading, run.error, refresh]);
  const waiting = !terminal && misses > 0;
  const done = run.data ? run.data.passed_count + run.data.failed_count + run.data.error_count + run.data.skipped_count : 0;
  const progress = run.data?.total_cases ? Math.round(done / run.data.total_cases * 100) : 0;
  return <><FlowHeader step={3} back={{ href: "/runs", label: "Run ledger" }} title={`Run ${runId.slice(0, 8)}`} description={terminal ? "Execution is complete. Continue to the evidence explorer for case-level reasoning." : "Prism is persisting each inference attempt and scoring outcome as it completes."} actions={<button className="btn btn-secondary" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15}/>Refresh</button>}/>{waiting
    ? <Notice>{misses < 4
        ? "Evaluation running. The API is busy generating, so this view is retrying in the background — nothing is lost and you do not need to refresh."
        : `Still evaluating. ${misses} status checks in a row have not come back yet; the run itself continues on the server. This page keeps retrying.`}</Notice>
    : run.error && <Notice error>{run.error}</Notice>}{run.loading && !run.data ? <div className="card loading-panel">Reading run state…</div> : run.data && <>
    <section className="card run-monitor"><div className="run-monitor-top"><div><span>Execution status</span><h2>{terminal ? "Evaluation reached a terminal state" : "Evaluation in progress"}</h2></div><StatusBadge status={run.data.status}/></div><div className="progress large"><span style={{ width: `${progress}%` }}/></div><div className="run-progress-copy"><strong>{done} / {run.data.total_cases} terminal cases</strong><span>{progress}%</span></div><div className="kpi-strip compact"><Kpi label="Passed" value={String(run.data.passed_count)} note="Met evaluator rule" tone="guard"/><Kpi label="Failed" value={String(run.data.failed_count)} note="Missed evaluator rule" tone="shield"/><Kpi label="Errors" value={String(run.data.error_count)} note="Not scored" tone="pulse"/><Kpi label="Pass rate" value={percent(run.data.pass_rate)} note={run.data.pass_rate_definition}/></div><div className="run-metadata"><span>Model <strong>{run.data.model_id ?? "not recorded"}</strong></span><span>Scoring <strong>{run.data.scoring_version}</strong></span><span>Started <strong>{formatDate(run.data.started_at ?? run.data.created_at)}</strong></span></div></section>
    {terminal ? <ContinueBar eyebrow="Execution complete" title="Inspect the evidence" description="Review every prompt, response, evaluator rule, explanation and finding before exporting." href={`/results/${runId}`} action="Open results explorer"/> : <section className="live-run-note"><Activity size={17}/><div><strong>{run.loading ? "Checking run status…" : "Updating automatically every few seconds"}</strong><p>Safe to leave this page — the backend continues the persisted run, and returning through the run ledger picks it up where it is. The Refresh button is there if you want an immediate check, but it is not required.</p></div></section>}
  </>}</>;
}

export function ResultsIndexScreen() {
  const { project } = useWorkspace(); const runs = useResource<Run[]>(project ? `/runs?project_id=${project.id}` : null);
  const terminal = runs.data?.filter(item => !["queued", "running"].includes(item.status)) ?? [];
  return <><FlowHeader step={4} title="Inspect evaluation evidence" description="Choose a completed run. Results preserve model output, scoring rationale and infrastructure errors as separate facts." actions={<Link className="btn btn-secondary" href="/runs"><Play size={15}/>New evaluation</Link>}/>{runs.error && <Notice error>{runs.error}</Notice>}<section className="card evidence-index"><div className="section-heading"><div><span>Evidence ledger</span><h2>Terminal runs</h2></div><strong>{terminal.length}</strong></div>{terminal.length ? <div className="evidence-run-grid">{terminal.map(run => <Link href={`/results/${run.id}`} key={run.id}><div><span className="mono">{run.id.slice(0, 8)}</span><StatusBadge status={run.status}/></div><h3>{run.model_id ?? "Model unavailable"}</h3><dl><div><dt>Pass rate</dt><dd>{percent(run.pass_rate)}</dd></div><div><dt>Cases</dt><dd>{run.total_cases}</dd></div><div><dt>Errors</dt><dd>{run.error_count}</dd></div></dl><small>{formatDate(run.completed_at ?? run.created_at)}</small><span className="text-action">Inspect evidence<ArrowRight size={14}/></span></Link>)}</div> : <Empty icon={ShieldCheck} title="No evidence yet" text="Complete an evaluation run before opening the results explorer." action={<Link className="btn btn-primary" href="/runs">Configure run</Link>}/>}</section></>;
}

export function EvidenceScreen({ runId }: { runId: string }) {
  const run = useResource<Run>(`/runs/${runId}`); const results = useResource<Results>(`/runs/${runId}/results`); const findings = useResource<Findings>(`/runs/${runId}/findings`);
  const [engine, setEngine] = useState("all"); const [status, setStatus] = useState("all"); const [query, setQuery] = useState(""); const [selectedId, setSelectedId] = useState("");
  const items = useMemo(() => (results.data?.items ?? []).filter(item => (engine === "all" || item.engine === engine) && (status === "all" || item.state === status) && (!query || (item.name ?? "").toLowerCase().includes(query.toLowerCase()))), [results.data, engine, status, query]);
  useEffect(() => { if (!items.some(item => item.run_case_id === selectedId)) setSelectedId(items[0]?.run_case_id ?? ""); }, [items, selectedId]);
  const selected = items.find(item => item.run_case_id === selectedId) ?? null;
  const finding = findings.data?.findings.find(item => item.run_case_id === selected?.run_case_id) ?? null;
  return <><FlowHeader step={4} back={{ href: "/results", label: "Evidence ledger" }} title={`Evidence ${runId.slice(0, 8)}`} description="Trace each outcome from the frozen test case to the observed response and evaluator explanation." actions={<><Link className="btn btn-secondary" href={`/reports/${runId}`}><FileDown size={15}/>Report</Link><Link className="btn btn-primary" href="/runs"><Play size={15}/>New run</Link></>}/>{run.error && <Notice error>{run.error}</Notice>}{run.data && <><div className="kpi-strip compact evidence-kpis"><Kpi label="Pass rate" value={percent(run.data.pass_rate)} note={`${run.data.passed_count + run.data.failed_count} scored`}/><Kpi label="Passed" value={String(run.data.passed_count)} note="Met rule" tone="guard"/><Kpi label="Failed" value={String(run.data.failed_count)} note="Missed rule" tone="shield"/><Kpi label="Errors" value={String(run.data.error_count)} note="Excluded from rate" tone="pulse"/></div><RunDecision run={run.data}/><RunIteration run={run.data}/></>}
    <section className="evidence-toolbar"><div className="search-field"><Search size={15}/><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Find a case" aria-label="Find a case"/></div><label><Filter size={14}/><select value={engine} onChange={event => setEngine(event.target.value)} aria-label="Filter by engine"><option value="all">All engines</option><option value="guard">Guard</option><option value="shield">Shield</option></select></label><label><SlidersHorizontal size={14}/><select value={status} onChange={event => setStatus(event.target.value)} aria-label="Filter by outcome"><option value="all">All outcomes</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="error">Errors</option><option value="skipped">Skipped</option></select></label><span>{items.length} cases</span></section>
    {results.error && <Notice error>{results.error}</Notice>}
    {items.length ? <div className="evidence-explorer"><aside className="case-index">{items.map(item => <button key={item.run_case_id} className={item.run_case_id === selectedId ? "active" : ""} onClick={() => setSelectedId(item.run_case_id)}><span className={`engine-dot ${item.engine}`}/><span><strong>{item.name ?? "Unnamed case"}</strong><small>{item.category ?? "uncategorized"} · {item.engine}</small></span><StatusBadge status={item.state}/></button>)}</aside>{selected && <EvidenceDetail item={selected} finding={finding}/>}</div> : !results.loading && <Empty title="No cases match these filters" text="Clear a filter to return to the recorded case population."/>}
    <ContinueBar title="Package this run for review" description="The report keeps the run identity, model label, scoring version, outcomes and declared limitations together." href={`/reports/${runId}`} action="Prepare report"/>
  </>;
}

function EvidenceDetail({ item, finding }: { item: RunCase; finding: Finding | null }) {
  const trace = item.traces[0]; const [copied, setCopied] = useState(false);
  async function copyTrace() { if (!trace?.trace_id) return; await navigator.clipboard.writeText(trace.trace_id); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }
  return <article className="evidence-detail"><header><div><span>Case evidence</span><h2>{item.name ?? "Unnamed case"}</h2><p>{item.engine} · {item.category ?? "uncategorized"} · severity {item.severity ?? "not set"}</p></div><StatusBadge status={item.state}/></header>{finding && <section className="finding-callout"><span>Actionable finding</span><strong>{finding.evidence}</strong>{finding.mitigation && <p>{finding.mitigation}</p>}</section>}<div className="evidence-block"><span>Application instructions at execution</span><pre>{String(item.case_snapshot.app_system_prompt ?? "No application system prompt configured.")}</pre></div><div className="evidence-columns"><div className="evidence-block"><span>Test prompt</span><pre>{String(item.case_snapshot.user_prompt ?? "Not retained")}</pre></div><div className="evidence-block"><span>Evaluator rule</span><pre>{JSON.stringify(item.case_snapshot.evaluator_config ?? {}, null, 2)}</pre></div></div><div className="evidence-block response"><span>Observed model response</span><pre>{trace?.response_text ?? trace?.error_message ?? "No response content retained."}</pre></div><div className="evidence-block explanation"><span>Scoring explanation</span><p>{item.explanation ?? item.error ?? "No explanation recorded."}</p></div><footer><button type="button" onClick={copyTrace} disabled={!trace?.trace_id}><Clipboard size={13}/>{copied ? "Copied" : trace?.trace_id?.slice(0, 12) ?? "No trace"}</button><span>{trace?.latency_ms ?? "—"} ms</span><span>HTTP {trace?.upstream_status ?? "—"}</span><span>{formatDate(trace?.recorded_at)}</span></footer></article>;
}

export function PulseWorkspaceScreen() {
  const { project } = useWorkspace(); const metrics = useResource<Metrics>(project ? `/metrics/summary?project_id=${project.id}` : null); const languages = useResource<LanguageMetrics>(project ? `/metrics/languages?project_id=${project.id}` : null); const traces = useResource<TracePage>(project ? `/traces?project_id=${project.id}&limit=20` : null);
  const attempts = metrics.data?.inference.attempts ?? 0; const samples = metrics.data?.latency_ms.sample_count ?? 0;
  return <><FlowHeader title="Pulse observability" description="Performance evidence from Prism evaluation calls. This is not production traffic monitoring." actions={<Link className="btn btn-secondary" href="/runs"><Play size={15}/>Run evaluation</Link>}/><section className="scope-banner"><Activity size={18}/><div><strong>Evaluation-time measurements</strong><p>Every value below comes from persisted Prism traces for the selected project. No synthetic traffic or unsupported live-monitoring claim is included.</p></div></section>{metrics.error && <Notice error>{metrics.error}</Notice>}<div className="kpi-strip"><Kpi label="Recorded attempts" value={String(attempts)} note="Persisted traces"/><Kpi label="Successful calls" value={String(metrics.data?.inference.successful ?? 0)} note="Valid responses" tone="guard"/><Kpi label="Blocked calls" value={String(metrics.data?.inference.blocked ?? 0)} note="Not model failures" tone="shield"/><Kpi label="p95 latency" value={metrics.data?.latency_ms.p95 == null ? "—" : `${Math.round(metrics.data.latency_ms.p95)} ms`} note={samples < 2 ? `${samples} successful sample` : `${samples} successful samples`} tone="pulse"/></div><div className="pulse-grid"><section className="card latency-panel"><div className="section-heading"><div><span>Latency population</span><h2>Successful inference calls</h2></div><Gauge size={20}/></div><div className="latency-stats"><div><span>Mean</span><strong>{metricMs(metrics.data?.latency_ms.mean)}</strong></div><div><span>Median</span><strong>{metricMs(metrics.data?.latency_ms.median)}</strong></div><div><span>P95</span><strong>{metricMs(metrics.data?.latency_ms.p95)}</strong></div><div><span>Range</span><strong>{metrics.data?.latency_ms.min == null ? "—" : `${Math.round(metrics.data.latency_ms.min)}–${Math.round(metrics.data.latency_ms.max ?? 0)} ms`}</strong></div></div><p>{metrics.data?.latency_ms.note ?? "No latency population recorded."}</p></section><LanguagePanel data={languages.data}/></div>{attempts === 0 ? <Empty icon={Activity} title="No Pulse data" text="Pulse begins after Prism executes genuine inference requests."/> : <section className="card trace-ledger"><div className="section-heading"><div><span>Trace ledger</span><h2>Recent inference attempts</h2></div><strong>{traces.data?.total ?? attempts}</strong></div><div className="table-wrap"><table className="table"><thead><tr><th>Trace</th><th>Outcome</th><th>Latency</th><th>HTTP</th><th>Recorded</th></tr></thead><tbody>{traces.data?.items.map(trace => <tr key={trace.trace_id}><td><strong className="mono">{trace.trace_id.slice(0, 10)}</strong><small>{trace.model_id ?? "unknown model"}</small></td><td><StatusBadge status={trace.outcome}/></td><td>{trace.latency_ms == null ? "—" : `${trace.latency_ms} ms`}</td><td>{trace.upstream_status ?? "—"}</td><td>{formatDate(trace.recorded_at)}</td></tr>)}</tbody></table></div></section>}</>;
}

function LanguagePanel({ data }: { data: LanguageMetrics | null }) { return <section className="card language-panel"><div className="section-heading"><div><span>Declared language</span><h2>Coverage and outcomes</h2></div><BarChart3 size={20}/></div>{data?.languages.length ? <div className="language-rows">{data.languages.map(item => <div key={item.language}><strong>{item.language.toUpperCase()}</strong><span>{item.cases} cases</span><span>{percent(item.pass_rate)}</span><span>{item.latency_ms.p95 == null ? "—" : `${Math.round(item.latency_ms.p95)} ms p95`}</span></div>)}</div> : <p>No cases with declared language evidence have run yet.</p>}{data?.note && <small>{data.note}</small>}</section>; }

export function ReportWorkspaceScreen({ selectedRunId }: { selectedRunId?: string }) {
  const { project } = useWorkspace();
  const runs = useResource<Run[]>(project && !selectedRunId ? `/runs?project_id=${project.id}` : null);
  const selectedRun = useResource<Run>(selectedRunId ? `/runs/${selectedRunId}` : null);
  const selected = selectedRun.data;
  const gate = useResource<ReleaseGate>(selectedRunId ? `/runs/${selectedRunId}/gate` : null);
  const [error, setError] = useState("");
  const terminal = runs.data?.filter(item => !["queued", "running"].includes(item.status)) ?? [];
  async function exportRun(format: "json" | "csv") { if (!selectedRunId) return; setError(""); try { await download(`/reports/${selectedRunId}/export?format=${format}`, `atlas-prism-${selectedRunId}.${format}`); } catch (reason) { setError((reason as Error).message); } }
  return <><FlowHeader step={5} back={selectedRunId ? { href: "/reports", label: "Report ledger" } : undefined} title={selectedRunId ? `Report ${selectedRunId.slice(0, 8)}` : "Export evaluation evidence"} description="Package persisted results and scoring context for technical review. Exports do not certify model safety." actions={selectedRunId ? <><button className="btn btn-secondary" onClick={() => exportRun("csv")}><Download size={15}/>CSV</button><button className="btn btn-primary" onClick={() => exportRun("json")}><Download size={15}/>JSON report</button></> : undefined}/>{error && <Notice error>{error}</Notice>}{selectedRunId ? selected ? <div className="report-layout"><section className="card report-preview"><div className="report-title"><div><span>ATLAS Prism evaluation record</span><h2>{project?.name}</h2><p className="mono">Run {selected.id}</p></div><StatusBadge status={selected.status}/></div><div className="report-facts"><div><span>Model label</span><strong>{selected.model_id ?? "Not recorded"}</strong></div><div><span>Scoring version</span><strong>{selected.scoring_version}</strong></div><div><span>Completed</span><strong>{formatDate(selected.completed_at ?? selected.created_at)}</strong></div><div><span>Case population</span><strong>{selected.total_cases}</strong></div></div><div className="report-outcome"><div><span>Observed pass rate</span><strong>{percent(selected.pass_rate)}</strong><small>{selected.pass_rate_definition}</small></div><dl><div><dt>Passed</dt><dd>{selected.passed_count}</dd></div><div><dt>Failed</dt><dd>{selected.failed_count}</dd></div><div><dt>Errors</dt><dd>{selected.error_count}</dd></div><div><dt>Skipped</dt><dd>{selected.skipped_count}</dd></div></dl></div><section className="report-disclosure"><strong>Evidence boundary</strong><p>Exports contain observed outputs and scoring configuration from this persisted run. Credentials are excluded. A passing result applies only to the executed cases and is not a general safety guarantee.</p></section></section><aside className="card report-decision"><div className="section-heading"><div><span>Release gate</span><h2>{verdictTitle(gate.data?.verdict)}</h2></div>{gate.data && <StatusBadge status={gate.data.verdict}/>}</div>{gate.data?.checks.map(check => <div className="report-check" key={check.check}><span>{check.check.replaceAll("_", " ")}</span><strong>{check.met ? "Met" : "Missed"}</strong><small>{check.detail}</small></div>)}{gate.data?.limitations.length ? <div className="report-limits"><strong>Limitations</strong><ul>{gate.data.limitations.map(item => <li key={item}>{item}</li>)}</ul></div> : null}<Link className="text-action" href={`/results/${selectedRunId}`}>Return to case evidence<ArrowRight size={14}/></Link></aside></div> : <Empty title="Run not found" text="This run is not available in the selected project." action={<Link className="btn btn-secondary" href="/reports">Choose another run</Link>}/> : <><section className="card report-index"><div className="section-heading"><div><span>Report ledger</span><h2>Choose a terminal run</h2></div><strong>{terminal.length}</strong></div>{terminal.length ? <div className="report-rows">{terminal.map(run => <Link href={`/reports/${run.id}`} key={run.id}><span className="mono">{run.id.slice(0, 8)}</span><span><strong>{run.model_id ?? "Model unavailable"}</strong><small>{formatDate(run.completed_at ?? run.created_at)}</small></span><span><strong>{percent(run.pass_rate)}</strong><small>{run.total_cases} cases · {run.error_count} errors</small></span><StatusBadge status={run.status}/><ArrowRight size={15}/></Link>)}</div> : <Empty icon={FileDown} title="No exportable runs" text="A report becomes available when a run reaches a terminal state." action={<Link className="btn btn-primary" href="/runs">Run evaluation</Link>}/>}</section><PipelineGuide projectId={project?.id ?? null}/></>}
  </>;
}

function PipelineGuide({ projectId }: { projectId: string | null }) { return <section className="card pipeline-guide"><div><TerminalSquare size={20}/><span>CI release gate</span><h2>Run the same policy outside the UI</h2><p>The CLI returns a non-zero exit code for blocked, unconfigured or inconclusive gates. Archive the report even when release stops.</p></div><pre className="code mono">{`python tools/prism-cli/prism.py run \\\n  --project ${projectId ?? "<project-id>"} \\\n  --connection <connection-id> \\\n  --suite <suite-id> --concurrency 1 --gate`}</pre></section>; }

function verdictTitle(verdict: ReleaseGate["verdict"] | undefined) { if (!verdict) return "Policy not read"; return ({ pass: "Policy thresholds met", block: "Release blocked", not_configured: "Policy not configured", inconclusive: "Decision inconclusive" } as const)[verdict]; }
function metricMs(value: number | null | undefined) { return value == null ? "—" : `${Math.round(value)} ms`; }
