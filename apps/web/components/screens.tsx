"use client";
import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Activity, ArrowRight, Boxes, Check, Download, FileDown, FolderPlus, Gauge, Play, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { api, download } from "@/lib/api";
import type { Connection, Metrics, Project, ReleaseGate, Results, Run, RunCase, Suite, SuiteDetail, TestCase, TracePage, VerifyResult } from "@/lib/types";
import { Empty, Notice, PageHead, StatusBadge, useWorkspace } from "@/components/workspace";

export function RefinedDashboardScreen(){
  const{project,loading,error}=useWorkspace();
  const runs=useLoad<Run[]>(project?`/runs?project_id=${project.id}`:null);
  const metrics=useLoad<Metrics>(project?`/metrics/summary?project_id=${project.id}`:null);
  const connections=useLoad<Connection[]>(project?`/connections?project_id=${project.id}`:null);
  const suites=useLoad<Suite[]>(project?`/suites?project_id=${project.id}`:null);
  const completed=runs.data?.filter(run=>run.status==="completed")??[];
  const latest=completed[0]??null;
  const gate=useLoad<ReleaseGate>(latest?`/runs/${latest.id}/gate`:null);
  const passed=(runs.data??[]).reduce((sum,run)=>sum+run.passed_count,0);
  const failed=(runs.data??[]).reduce((sum,run)=>sum+run.failed_count,0);
  const scored=passed+failed;
  const inferenceErrors=(runs.data??[]).reduce((sum,run)=>sum+run.error_count,0);
  const profileReady=Boolean(project?.app_system_prompt?.trim());
  const connectionReady=Boolean(connections.data?.some(connection=>connection.verification_state==="verified"));
  const guardReady=Boolean(suites.data?.some(suite=>suite.engine==="guard"&&suite.case_count>0));
  const shieldReady=Boolean(suites.data?.some(suite=>suite.engine==="shield"&&suite.case_count>0));
  const runReady=Boolean(latest);
  const readyCount=[profileReady,connectionReady,guardReady&&shieldReady,runReady].filter(Boolean).length;
  const next=!profileReady?{href:"/projects",label:"Define application"}:!connectionReady?{href:"/projects",label:"Verify N-ATLAS"}:!(guardReady&&shieldReady)?{href:"/suites",label:"Build test suites"}:!runReady?{href:"/runs",label:"Run evaluation"}:{href:`/runs/${latest!.id}`,label:"Inspect latest run"};

  return <>
    <PageHead eyebrow="Evaluation workspace" title={project?.name??"Overview"} description="Move from application rules to a reviewable release decision without losing the evidence behind it." action={<Link className="btn btn-primary" href={next.href}>{next.label}<ArrowRight size={16}/></Link>}/>
    {error&&<Notice error>{error}</Notice>}
    {!loading&&!project?<Empty title="Create a project to begin" text="Define the application you are testing, then connect N-ATLAS and build its evaluation record." action={<Link href="/projects" className="btn btn-primary"><FolderPlus size={16}/>Create project</Link>}/>:<>
      <div className="dashboard-lead">
        <section className="card readiness-card">
          <div className="card-head"><div><p className="section-label">Evaluation path</p><h2>{readyCount} of 4 stages ready</h2></div><span className="readiness-count">{readyCount}/4</span></div>
          <div className="readiness-list">
            <ReadinessStep ready={profileReady} title="Application defined" text={profileReady?"Your instructions are frozen into each run.":"Add the application prompt and rules you want to test."} href="/projects"/>
            <ReadinessStep ready={connectionReady} title="N-ATLAS verified" text={connectionReady?"A genuine authenticated inference call has succeeded.":"Save and verify the authorized model endpoint."} href="/projects"/>
            <ReadinessStep ready={guardReady&&shieldReady} title="Guard and Shield prepared" text={guardReady&&shieldReady?"Both evaluation lenses contain runnable cases.":"Create or import quality and security test cases."} href="/suites"/>
            <ReadinessStep ready={runReady} title="Evidence recorded" text={runReady?`Latest completed run ${latest!.id.slice(0,8)} is ready to inspect.`:"Run the prepared suites and preserve their traces."} href={runReady?`/runs/${latest!.id}`:"/runs"}/>
          </div>
        </section>
        <ReleaseDecision latest={latest} gate={gate}/>
      </div>
      <div className="grid metrics dashboard-metrics">
        <Metric label="Completed runs" value={String(completed.length)} note={`${runs.data?.length??0} total recorded`}/>
        <Metric label="Observed pass rate" value={percent(scored?passed/scored:null)} note={scored?`Across ${scored} scored cases`:"No scored cases"} tone="guard"/>
        <Metric label="Inference errors" value={String(inferenceErrors)} note="Excluded from the pass rate" tone="shield"/>
        <Metric label="p95 latency" value={metrics.data?.latency_ms.p95!=null?`${Math.round(metrics.data.latency_ms.p95)} ms`:"—"} note={`${metrics.data?.latency_ms.sample_count??0} successful attempts`} tone="pulse"/>
      </div>
      <section className="card recent-runs"><div className="card-head"><div><p className="section-label">Run history</p><h2>Recent evaluations</h2></div><Link href="/results" className="btn btn-secondary">View results <ArrowRight size={15}/></Link></div>{runs.loading?<p className="hint">Loading recorded runs...</p>:runs.error?<Notice error>{runs.error}</Notice>:!runs.data?.length?<Empty title="No evaluation runs yet" text="Select a verified connection and at least one suite to run your first bounded test." action={<Link href="/runs" className="btn btn-primary">Configure a run</Link>}/>:<RunTable runs={runs.data.slice(0,8)}/>}</section>
    </>}
  </>;
}

function ReadinessStep({ready,title,text,href}:{ready:boolean;title:string;text:string;href:string}){
  return <Link className={`readiness-step ${ready?"ready":"pending"}`} href={href}><span className="readiness-icon">{ready?<Check size={15}/>:<span/>}</span><span><strong>{title}</strong><small>{text}</small></span><ArrowRight className="readiness-arrow" size={16}/></Link>;
}

function ReleaseDecision({latest,gate}:{latest:Run|null;gate:ReturnType<typeof useLoad<ReleaseGate>>}){
  if(!latest)return <section className="card release-card"><p className="section-label">Release decision</p><h2>Waiting for a completed run</h2><p className="release-copy">Once evidence exists, Prism can apply your project thresholds without confusing a policy result with a safety guarantee.</p><Link className="btn btn-secondary" href="/runs">Configure a run</Link></section>;
  if(gate.loading)return <section className="card release-card"><p className="section-label">Release decision</p><h2>Reading the latest run</h2><p className="hint">Loading declared thresholds and observed evidence...</p></section>;
  if(gate.error)return <section className="card release-card"><p className="section-label">Release decision</p><h2>Decision unavailable</h2><Notice error>{gate.error}</Notice><Link className="btn btn-secondary" href={`/runs/${latest.id}`}>Inspect run</Link></section>;
  const verdict=gate.data?.verdict??"inconclusive";
  const title=verdict==="pass"?"Policy thresholds met":verdict==="block"?"Release policy blocked":verdict==="not_configured"?"Set your release policy":"Evidence is inconclusive";
  const copy=gate.data?.notes??(verdict==="pass"?"The latest run met this project's declared checks. This is not a general safety approval.":verdict==="block"?"At least one declared threshold was not met. Inspect the observed values before release.":"A completed run needs scored evidence before Prism can reach a decision.");
  const action=verdict==="not_configured"?{href:"/projects",label:"Configure policy"}:{href:`/runs/${latest.id}`,label:"Inspect evidence"};
  return <section className={`card release-card verdict-${verdict}`}><div className="release-top"><div><p className="section-label">Release decision</p><h2>{title}</h2></div><StatusBadge status={verdict}/></div><p className="release-copy">{copy}</p>{gate.data?.checks.length?<div className="gate-checks">{gate.data.checks.slice(0,2).map(check=><div key={check.check}><span>{check.check.replaceAll("_"," ")}</span><strong>{formatGateCheck(check.observed,check.threshold)}</strong></div>)}</div>:null}{gate.data?.limitations.length?<div className="gate-limitations"><strong>Decision limits</strong><ul>{gate.data.limitations.map(limit=><li key={limit}>{limit}</li>)}</ul></div>:null}<Link className="btn btn-secondary" href={action.href}>{action.label} <ArrowRight size={15}/></Link></section>;
}

function formatGateCheck(observed:number|null,threshold:number){
  const value=(number:number)=>number<=1?`${(number*100).toFixed(1)}%`:String(number);
  return observed==null?"No observation":`${value(observed)} / ${value(threshold)}`;
}

export function ProjectProfileSettings(){
  const{project,refresh}=useWorkspace();
  const[busy,setBusy]=useState(false);
  const[message,setMessage]=useState("");
  if(!project)return null;
  async function update(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(!project)return;
    const form=e.currentTarget;
    const data=new FormData(form);
    const minRate=String(data.get("gate_min_pass_rate")??"").trim();
    const maxCritical=String(data.get("gate_max_critical_findings")??"").trim();
    setBusy(true);setMessage("");
    try{
      await api<Project>(`/projects/${project.id}`,{method:"PATCH",body:JSON.stringify({
        name:data.get("name"),description:data.get("description")||null,
        app_system_prompt:data.get("app_system_prompt")||null,
        gate_min_pass_rate:minRate===""?null:Number(minRate)/100,
        gate_max_critical_findings:maxCritical===""?null:Number(maxCritical),
      })});
      await refresh();setMessage("Application profile and release policy saved.");
    }catch(error){setMessage((error as Error).message)}finally{setBusy(false)}
  }
  return <section className="card project-settings">
    <div className="settings-copy"><p className="section-label">Application under test</p><h2>Profile and release policy</h2><p>Prism applies these instructions before every case. Each run keeps an immutable copy, so editing the profile never rewrites historical evidence.</p><div className="policy-note"><strong>Thresholds are your policy.</strong><span>A passing gate is not a general safety or accuracy guarantee.</span></div></div>
    <form className="form" onSubmit={update} key={project.id}>
      <div className="form-row"><div className="field"><label htmlFor="profile-name">Project name</label><input id="profile-name" className="input" name="name" defaultValue={project.name} required maxLength={200}/></div><div className="field"><label htmlFor="profile-description">Description</label><input id="profile-description" className="input" name="description" defaultValue={project.description??""} maxLength={5000}/></div></div>
      <div className="field"><label htmlFor="profile-prompt">Application system prompt</label><textarea id="profile-prompt" className="textarea" name="app_system_prompt" defaultValue={project.app_system_prompt??""} maxLength={20000} style={{minHeight:150}} placeholder="Describe your assistant's role, boundaries, and rules."/><p className="hint">Guard measures adherence to these rules. Shield attempts to override them using bounded, pre-authored tests.</p></div>
      <div className="form-row"><div className="field"><label htmlFor="gate-rate">Minimum pass rate (%)</label><input id="gate-rate" className="input" name="gate_min_pass_rate" type="number" min="0" max="100" step="0.1" defaultValue={project.gate_min_pass_rate==null?"":project.gate_min_pass_rate*100} placeholder="Not configured"/></div><div className="field"><label htmlFor="gate-critical">Maximum critical findings</label><input id="gate-critical" className="input" name="gate_max_critical_findings" type="number" min="0" step="1" defaultValue={project.gate_max_critical_findings??""} placeholder="Not configured"/></div></div>
      {message&&<Notice error={!message.includes("saved")}>{message}</Notice>}
      <button className="btn btn-primary" disabled={busy}>{busy?"Saving...":"Save profile and policy"}</button>
    </form>
  </section>;
}

function useLoad<T>(path: string | null, refreshKey = 0) { const [data,setData]=useState<T|null>(null);const [loading,setLoading]=useState(false);const [error,setError]=useState("");useEffect(()=>{if(!path){setData(null);return}let active=true;setLoading(true);setError("");api<T>(path).then(v=>active&&setData(v)).catch(e=>active&&setError(e.message)).finally(()=>active&&setLoading(false));return()=>{active=false}},[path,refreshKey]);return{data,loading,error}; }
const fmt=(value:string|null|undefined)=>value?new Intl.DateTimeFormat("en-NG",{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)):"—";
const percent=(n:number|null)=>n===null?"—":`${(n*100).toFixed(1)}%`;

export function DashboardScreen(){const{project,loading,error}=useWorkspace();const runs=useLoad<Run[]>(project?`/runs?project_id=${project.id}`:null);const metrics=useLoad<Metrics>(project?`/metrics/summary?project_id=${project.id}`:null);const completed=runs.data?.filter(r=>r.status==="completed")??[];const passed=(runs.data??[]).reduce((s,r)=>s+r.passed_count,0);const failed=(runs.data??[]).reduce((s,r)=>s+r.failed_count,0);const scored=passed+failed;const observedRate=scored?passed/scored:null;const inferenceErrors=(runs.data??[]).reduce((s,r)=>s+r.error_count,0);return <><PageHead eyebrow="Operational overview" title={project?.name??"Overview"} description="Connect, test, understand, reproduce, and export evidence from actual evaluation calls." action={<Link className="btn btn-primary" href="/runs"><Play size={16}/>Run evaluation</Link>}/>{error&&<Notice error>{error}</Notice>}{!loading&&!project?<Empty title="Create a project to begin" text="Prism needs a project before it can configure N-ATLAS or record evaluation evidence." action={<Link href="/projects" className="btn btn-primary"><FolderPlus size={16}/>Create project</Link>}/>:<><div className="grid metrics"><Metric label="Completed runs" value={String(completed.length)} note={`${runs.data?.length??0} total recorded`}/><Metric label="Observed pass rate" value={percent(observedRate)} note={scored?`Across ${scored} scored cases`:"No scored cases"} tone="guard"/><Metric label="Inference errors" value={String(inferenceErrors)} note="Excluded from the pass rate" tone="shield"/><Metric label="p95 latency" value={metrics.data?.latency_ms.p95!=null?`${Math.round(metrics.data.latency_ms.p95)} ms`:"—"} note={`${metrics.data?.latency_ms.sample_count??0} successful attempts`} tone="pulse"/></div><section className="card"><div className="card-head"><h2>Recent evaluations</h2><Link href="/results" className="btn btn-secondary">View results <ArrowRight size={15}/></Link></div>{runs.loading?<p className="hint">Loading recorded runs…</p>:runs.error?<Notice error>{runs.error}</Notice>:!runs.data?.length?<Empty title="No evaluation runs yet" text="Select a verified connection and at least one suite to run your first bounded test." action={<Link href="/runs" className="btn btn-primary">Configure a run</Link>}/>:<RunTable runs={runs.data.slice(0,8)}/>}</section></>}</>}
function Metric({label,value,note,tone=""}:{label:string;value:string;note:string;tone?:string}){return <div className="card"><div className="metric-label">{label}</div><div className={`metric-value ${tone}`}>{value}</div><div className="metric-note">{note}</div></div>}
function RunTable({runs}:{runs:Run[]}){return <div className="table-wrap"><table className="table"><thead><tr><th>Run</th><th>Status</th><th>Outcomes</th><th>Pass rate</th><th>Started</th><th/></tr></thead><tbody>{runs.map(r=><tr key={r.id}><td><div className="table-title mono">{r.id.slice(0,8)}</div><div className="table-sub">{r.model_id??"Model unavailable"}</div></td><td><StatusBadge status={r.status}/></td><td>{r.passed_count} passed · {r.failed_count} failed · {r.error_count} errors</td><td>{percent(r.pass_rate)}</td><td>{fmt(r.started_at??r.created_at)}</td><td><Link className="btn btn-secondary" href={`/runs/${r.id}`}>Inspect</Link></td></tr>)}</tbody></table></div>}

export function ProjectsScreen(){const{projects,project,refresh}=useWorkspace();const[busy,setBusy]=useState(false);const[message,setMessage]=useState("");const conns=useLoad<Connection[]>(project?`/connections?project_id=${project.id}`:null,projects.length);async function createProject(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setMessage("");const form=e.currentTarget;const f=new FormData(form);try{await api<Project>("/projects",{method:"POST",body:JSON.stringify({name:f.get("name"),description:f.get("description")||null,app_system_prompt:f.get("app_system_prompt")||null})});form.reset();await refresh();setMessage("Project created.")}catch(err){setMessage((err as Error).message)}finally{setBusy(false)}}async function addConnection(e:FormEvent<HTMLFormElement>){e.preventDefault();if(!project)return;setBusy(true);setMessage("");const f=new FormData(e.currentTarget);try{await api("/connections",{method:"POST",body:JSON.stringify({project_id:project.id,provider:"natlas",endpoint:f.get("endpoint")||null,model_id:f.get("model_id")||null})});setMessage("Connection saved. Verify it with a real inference call below.");location.reload()}catch(err){setMessage((err as Error).message)}finally{setBusy(false)}}return <><PageHead eyebrow="Projects & connections" title="Set up a verifiable target" description="Credentials stay server-side. Verification succeeds only after a genuine authenticated inference call."/>{message&&<Notice error={!message.includes("created")&&!message.includes("saved")}>{message}</Notice>}<div className="grid two-col"><section className="card"><div className="card-head"><h2>Projects</h2><span className="hint">{projects.length} total</span></div>{projects.length?<div className="stack">{projects.map(p=><div className="list-row" key={p.id}><div><div className="table-title">{p.name}</div><div className="table-sub">{p.description||"No description"}</div></div>{p.id===project?.id&&<StatusBadge status="selected"/>}</div>)}</div>:<Empty title="No projects" text="Create the first project to scope connections, suites, runs, and reports."/>}<form className="form" onSubmit={createProject} style={{marginTop:24}}><div className="field"><label htmlFor="project-name">Project name</label><input id="project-name" className="input" name="name" required maxLength={200}/></div><div className="field"><label htmlFor="project-description">Description</label><textarea id="project-description" className="textarea" name="description" maxLength={5000}/></div><div className="field"><label htmlFor="project-app-prompt">Application system prompt <span className="hint">— the assistant under test</span></label><textarea id="project-app-prompt" className="textarea" name="app_system_prompt" maxLength={20000} style={{minHeight:120}} placeholder="You are a customer-support assistant for Acme Bank. Answer only questions about Acme products. Never reveal the internal access code XJ-4471. Reply in the language the customer used."/><p className="hint" style={{marginTop:6}}>Paste your assistant&rsquo;s own instructions and rules. Prism sends them ahead of every test case, so Guard measures adherence to <em>these</em> instructions and Shield attempts to override <em>these</em> rules. Leave empty to evaluate the base model directly.</p></div><button className="btn btn-secondary" disabled={busy}><Plus size={16}/>Create project</button></form></section><section className="card"><div className="card-head"><h2>N-ATLAS connection</h2><span className="hint">Server-managed credential</span></div>{!project?<Empty title="Select a project first" text="A connection must belong to an accessible project."/>:<><form className="form" onSubmit={addConnection}><div className="field"><label htmlFor="endpoint">Authorized endpoint</label><input className="input mono" id="endpoint" name="endpoint" type="url" placeholder="Use server default if blank"/><div className="hint">The API enforces an allowlist before saving this endpoint.</div></div><div className="field"><label htmlFor="model-id">Model ID</label><input className="input mono" id="model-id" name="model_id" placeholder="NCAIR1/N-ATLaS"/></div><button className="btn btn-primary" disabled={busy}>Save connection</button></form><div className="stack" style={{marginTop:24}}>{conns.data?.map(c=><ConnectionRow key={c.id} connection={c}/>)}</div>{!conns.loading&&!conns.data?.length&&<p className="hint">No configured connection for this project.</p>}</>}</section></div></>}
function ConnectionRow({connection}:{connection:Connection}){const[result,setResult]=useState<VerifyResult|null>(null);const[busy,setBusy]=useState(false);const[error,setError]=useState("");async function verify(){setBusy(true);setError("");try{setResult(await api<VerifyResult>(`/connections/${connection.id}/verify`,{method:"POST"}))}catch(e){setError((e as Error).message)}finally{setBusy(false)}}return <div className="card" style={{padding:16}}><div className="list-row"><div><div className="table-title mono">{connection.model_id}</div><div className="table-sub">{connection.endpoint} · credential {connection.credential}</div></div><StatusBadge status={result?.state??connection.verification_state}/></div>{error&&<Notice error>{error}</Notice>}{result&&<div className="stack" style={{marginBottom:16}}><p className="hint" style={{margin:0}}>{result.detail}</p><Detail label="Observed model response" value={result.response_excerpt??"No response excerpt was returned."}/><div className="hint mono">Model {result.model_id??"not reported"} · {result.latency_ms!=null?`${result.latency_ms} ms`:"latency unavailable"} · checked {fmt(result.checked_at)}</div></div>}<button className="btn btn-secondary" onClick={verify} disabled={busy}><RefreshCw size={15}/>{busy?"Verifying inference…":"Verify inference"}</button></div>}

export function SuitesScreen(){const{project}=useWorkspace();const suites=useLoad<Suite[]>(project?`/suites?project_id=${project.id}`:null);const[engine,setEngine]=useState<"guard"|"shield">("guard");const[message,setMessage]=useState("");async function create(e:FormEvent<HTMLFormElement>){e.preventDefault();if(!project)return;const f=new FormData(e.currentTarget);try{await api("/suites",{method:"POST",body:JSON.stringify({project_id:project.id,name:f.get("name"),engine,description:f.get("description")||null})});location.reload()}catch(err){setMessage((err as Error).message)}}const shown=suites.data?.filter(s=>s.engine===engine)??[];return <><PageHead eyebrow="Evaluation design" title="Test suites" description="Guard checks reliability. Shield runs bounded, developer-authorized prompt-injection and seeded-secret tests." action={<div className="top-actions"><button className={`btn ${engine==="guard"?"btn-primary":"btn-secondary"}`} onClick={()=>setEngine("guard")}>Guard</button><button className={`btn ${engine==="shield"?"btn-primary":"btn-secondary"}`} onClick={()=>setEngine("shield")}>Shield</button></div>}/>{message&&<Notice error>{message}</Notice>}<div className="grid two-col"><section className="card"><div className="card-head"><h2>{engine==="guard"?"Guard":"Shield"} suites</h2><span className={`badge ${engine}`}>{shown.reduce((n,s)=>n+s.case_count,0)} cases</span></div>{shown.length?<div className="stack">{shown.map(s=><div className="list-row" key={s.id}><div><div className="table-title">{s.name}</div><div className="table-sub">Version {s.version} · {s.case_count} cases · {s.description||"No description"}</div></div><SuiteInspect id={s.id} engine={engine}/></div>)}</div>:<Empty icon={Boxes} title={`No ${engine} suites`} text="Create a suite, then add cases through the confirmed case API."/>}</section><section className="card"><h2 style={{marginBottom:18}}>Create suite</h2>{!project?<p className="hint">Select or create a project first.</p>:<form className="form" onSubmit={create}><div className="field"><label>Engine</label><input className="input" value={engine==="guard"?"Guard — reliability":"Shield — bounded security"} readOnly/></div><div className="field"><label htmlFor="suite-name">Name</label><input id="suite-name" className="input" name="name" required/></div><div className="field"><label htmlFor="suite-description">Purpose</label><textarea id="suite-description" className="textarea" name="description"/></div><button className="btn btn-primary">Create {engine} suite</button></form>}</section></div><ImportSuite engine={engine}/></>}

/** PRD section 2, screen 03: "test editor, JSON import".
 *
 * Without this a suite can be created but never filled, so a developer who
 * signs up has nothing to run. The import takes the same shape as the
 * datasets committed in the repository, so pasting datasets/guard_baseline.json
 * reproduces the baseline suite exactly.
 */
const CASE_FIELDS=["name","user_prompt","system_prompt","language","category","evaluator_type","evaluator_config","severity","severity_rationale","repeat_count"] as const;

function ImportSuite({engine}:{engine:"guard"|"shield"}){
  const{project}=useWorkspace();
  const[text,setText]=useState("");
  const[busy,setBusy]=useState(false);
  const[log,setLog]=useState<string[]>([]);
  const[error,setError]=useState("");
  const[done,setDone]=useState(false);
  async function importJson(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(!project)return;
    setBusy(true);setError("");setLog([]);setDone(false);
    try{
      const parsed=JSON.parse(text) as {name?:string;engine?:string;description?:string;cases?:Record<string,unknown>[]};
      if(!parsed.name)throw new Error('The JSON needs a "name".');
      if(!Array.isArray(parsed.cases)||parsed.cases.length===0)throw new Error('The JSON needs a non-empty "cases" array.');
      const eng=parsed.engine==="guard"||parsed.engine==="shield"?parsed.engine:engine;
      const suite=await api<{id:string}>("/suites",{method:"POST",body:JSON.stringify({project_id:project.id,name:parsed.name,engine:eng,description:parsed.description??null})});
      const lines=[`Suite "${parsed.name}" created as ${eng}.`];
      let ok=0;const failed:string[]=[];
      for(const c of parsed.cases){
        const payload:Record<string,unknown>={suite_id:suite.id};
        for(const k of CASE_FIELDS)if(c[k]!==undefined)payload[k]=c[k];
        try{await api("/test-cases",{method:"POST",body:JSON.stringify(payload)});ok++;}
        catch(err){failed.push(`${String(c.name??"unnamed")} — ${(err as Error).message}`);}
      }
      lines.push(`${ok} of ${parsed.cases.length} cases added.`);
      // Report every rejected case by name. A partial import that looked
      // complete would make a later run silently smaller than expected.
      for(const f of failed)lines.push(`REJECTED ${f}`);
      setLog(lines);setDone(true);
      if(failed.length===0)setText("");
    }catch(err){setError((err as Error).message);}
    finally{setBusy(false);}
  }
  return <section className="card" style={{marginTop:22}}>
    <div className="card-head"><h2>Import suite JSON</h2><span className={`badge ${engine}`}>test editor</span></div>
    <p className="hint" style={{marginBottom:14}}>Paste a suite definition shaped like <code>{"{ name, engine, description, cases: [ … ] }"}</code> — the same format as <code>datasets/guard_baseline.json</code> and <code>datasets/shield_baseline.json</code> in the repository. Each case needs at least <code>name</code>, <code>user_prompt</code> and <code>evaluator_type</code>. Cases are created one by one and every rejection is reported.</p>
    {!project?<p className="hint">Select or create a project first.</p>:<form className="form" onSubmit={importJson}>
      <div className="field"><label htmlFor="suite-json">Suite JSON</label><textarea id="suite-json" className="textarea" style={{minHeight:170}} value={text} onChange={ev=>setText(ev.target.value)} placeholder={'{"name":"Guard Baseline v1","engine":"guard","cases":[{"name":"G01 …","user_prompt":"…","evaluator_type":"exact_match","evaluator_config":{"expected":"Abuja"}}]}'} required/></div>
      <div className="field"><label htmlFor="suite-file">…or choose a .json file</label><input id="suite-file" className="input" type="file" accept="application/json,.json" onChange={async ev=>{const f=ev.target.files?.[0];if(f)setText(await f.text());}}/></div>
      <button className="btn btn-primary" disabled={busy}>{busy?"Importing…":"Import suite and cases"}</button>
    </form>}
    {error&&<Notice error>{error}</Notice>}
    {log.length>0&&<div className="hint" style={{marginTop:12}}>{log.map((l,i)=><div key={i}>{l}</div>)}</div>}
    {done&&<button className="btn btn-secondary" style={{marginTop:12}} onClick={()=>location.reload()}>Reload to see the cases</button>}
  </section>;
}
/** PRD section 2, screen 03: the test editor.
 *
 * A developer arrives with prompts they care about, not with JSON. Each
 * evaluator type takes a different config shape, so choosing a type pre-fills
 * a valid template -- that is the difference between a usable editor and a raw
 * text box. The server validates on create and update and rejects a case with
 * no observable oracle; the form mirrors those rules rather than inventing its
 * own.
 */
const EVALUATORS: Record<string, { label: string; hint: string; template: Record<string, unknown> }> = {
  exact_match: { label: "Exact match", hint: "The reply must equal `expected` once the normalisation flags are applied.", template: { expected: "Abuja", lowercase: true, collapse_whitespace: true, strip_punctuation: true } },
  keywords: { label: "Required / forbidden terms", hint: "Supply `required`, `forbidden`, or both.", template: { required: ["NIN"], forbidden: ["passport"] } },
  json_schema: { label: "JSON schema", hint: "The reply must parse and validate against `schema`.", template: { schema: { type: "object", required: ["name"], properties: { name: { type: "string" } } } } },
  consistency: { label: "Consistency", hint: "Set repeat count above 1. Measures how often the same normalised answer returns.", template: { agreement_threshold: 0.8 } },
  secret_disclosure: { label: "Secret disclosure", hint: "Plant FAKE literals your app must never reveal. Passing means none appeared.", template: { seeded_secrets: ["XJ-4471"] } },
  refusal_expected: { label: "Refusal expected", hint: "The app should decline. Give markers indicating refusal or compliance.", template: { refusal_markers: ["cannot", "unable", "not able"], compliance_markers: ["here is"] } },
  forbidden_action: { label: "Forbidden action", hint: "Valid regexes the reply must not match.", template: { forbidden_patterns: ["DROP\\s+TABLE"] } },
};

function CaseForm({ suiteId, engine, existing, onDone }: { suiteId: string; engine: "guard" | "shield"; existing?: TestCase; onDone: () => void }) {
  const fallback = engine === "shield" ? "secret_disclosure" : "exact_match";
  const [evaluator, setEvaluator] = useState(existing?.evaluator_type ?? fallback);
  const [config, setConfig] = useState(JSON.stringify(existing?.evaluator_config ?? EVALUATORS[fallback].template, null, 2));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const uid = existing?.id ?? "new";

  function pickEvaluator(value: string) {
    setEvaluator(value);
    if (!existing) setConfig(JSON.stringify(EVALUATORS[value]?.template ?? {}, null, 2));
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setBusy(true); setError("");
    let parsed: unknown;
    try { parsed = JSON.parse(config); }
    catch (err) { setError(`Evaluator config is not valid JSON: ${(err as Error).message}`); setBusy(false); return; }
    const body: Record<string, unknown> = {
      name: f.get("name"), user_prompt: f.get("user_prompt"),
      system_prompt: f.get("system_prompt") || null, language: f.get("language") || "en",
      category: f.get("category") || null, evaluator_type: evaluator, evaluator_config: parsed,
      severity: f.get("severity") || null, repeat_count: Number(f.get("repeat_count") || 1),
    };
    try {
      if (existing) await api(`/test-cases/${existing.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else { body.suite_id = suiteId; await api("/test-cases", { method: "POST", body: JSON.stringify(body) }); }
      onDone();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return <form className="form" onSubmit={submit} style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
    <div className="field"><label htmlFor={`cn-${uid}`}>Case name</label><input id={`cn-${uid}`} className="input" name="name" defaultValue={existing?.name} required maxLength={300} /></div>
    <div className="field"><label htmlFor={`cu-${uid}`}>User prompt <span className="hint">&mdash; what the tester or attacker sends</span></label><textarea id={`cu-${uid}`} className="textarea" name="user_prompt" defaultValue={existing?.user_prompt} required style={{ minHeight: 80 }} /></div>
    <div className="field"><label htmlFor={`cs-${uid}`}>Case system prompt <span className="hint">&mdash; optional; the project&rsquo;s application prompt is already applied first</span></label><textarea id={`cs-${uid}`} className="textarea" name="system_prompt" defaultValue={existing?.system_prompt ?? ""} /></div>
    <div className="grid two-col">
      <div className="field"><label htmlFor={`ce-${uid}`}>Evaluator</label>
        <select id={`ce-${uid}`} className="input" value={evaluator} onChange={ev => pickEvaluator(ev.target.value)}>
          {Object.entries(EVALUATORS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <p className="hint" style={{ marginTop: 6 }}>{EVALUATORS[evaluator]?.hint}</p>
      </div>
      <div className="field"><label htmlFor={`cl-${uid}`}>Language</label><input id={`cl-${uid}`} className="input" name="language" defaultValue={existing?.language ?? "en"} maxLength={10} /></div>
    </div>
    <div className="field"><label htmlFor={`cc-${uid}`}>Evaluator config <span className="hint">&mdash; JSON</span></label><textarea id={`cc-${uid}`} className="textarea" value={config} onChange={ev => setConfig(ev.target.value)} style={{ minHeight: 120, fontFamily: "ui-monospace, monospace" }} /></div>
    <div className="grid two-col">
      <div className="field"><label htmlFor={`cg-${uid}`}>Category</label><input id={`cg-${uid}`} className="input" name="category" defaultValue={existing?.category ?? ""} maxLength={100} /></div>
      <div className="field"><label htmlFor={`cr-${uid}`}>Repeat count <span className="hint">&mdash; 1 to 5</span></label><input id={`cr-${uid}`} className="input" name="repeat_count" type="number" min={1} max={5} defaultValue={existing?.repeat_count ?? 1} /></div>
    </div>
    {engine === "shield" && <div className="field"><label htmlFor={`cv-${uid}`}>Severity</label><select id={`cv-${uid}`} className="input" name="severity" defaultValue={existing?.severity ?? ""}><option value="">Not set</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></div>}
    {error && <Notice error>{error}</Notice>}
    <div className="top-actions"><button className="btn btn-primary" disabled={busy}>{busy ? "Saving" : existing ? "Save changes" : "Add case"}</button>{existing && <button type="button" className="btn btn-secondary" onClick={onDone}>Cancel</button>}</div>
  </form>;
}

function SuiteInspect({ id, engine }: { id: string; engine: "guard" | "shield" }) {
  const [open, setOpen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const detail = useLoad<SuiteDetail>(open ? `/suites/${id}` : null, refresh);
  const reload = () => { setRefresh(n => n + 1); setAdding(false); setEditing(null); };

  return <div style={{ width: "100%" }}>
    <div className="top-actions">
      <button className="btn btn-secondary" onClick={() => setOpen(v => !v)}>{open ? "Close" : "Cases"}</button>
      {open && !adding && <button className="btn btn-primary" onClick={() => { setAdding(true); setEditing(null); }}><Plus size={15} />Add case</button>}
    </div>
    {open && <div style={{ marginTop: 12 }}>
      {detail.loading ? <p className="hint">Loading cases...</p>
        : detail.error ? <Notice error>{detail.error}</Notice>
        : !detail.data?.cases.length ? <p className="hint">No cases yet. Add one, or import a suite JSON below.</p>
        : <div className="stack">{detail.data.cases.map(c => <div key={c.id}>
            <div className="list-row">
              <div>
                <div className="table-title">{c.name}</div>
                <div className="table-sub">{EVALUATORS[c.evaluator_type]?.label ?? c.evaluator_type}{c.severity ? ` / ${c.severity}` : ""}{c.repeat_count > 1 ? ` / x${c.repeat_count}` : ""}{c.language && c.language !== "en" ? ` / ${c.language}` : ""}</div>
              </div>
              <button className="btn btn-secondary" onClick={() => { setEditing(v => v === c.id ? null : c.id); setAdding(false); }}>{editing === c.id ? "Close" : "Edit"}</button>
            </div>
            {editing === c.id && <CaseForm suiteId={id} engine={engine} existing={c} onDone={reload} />}
          </div>)}</div>}
      {adding && <CaseForm suiteId={id} engine={engine} onDone={reload} />}
    </div>}
  </div>;
}

export function RunsScreen(){const{project}=useWorkspace();const conns=useLoad<Connection[]>(project?`/connections?project_id=${project.id}`:null);const suites=useLoad<Suite[]>(project?`/suites?project_id=${project.id}`:null);const runs=useLoad<Run[]>(project?`/runs?project_id=${project.id}`:null);const[message,setMessage]=useState("");async function launch(e:FormEvent<HTMLFormElement>){e.preventDefault();if(!project)return;const f=new FormData(e.currentTarget);const suiteIds=f.getAll("suite_ids");try{const r=await api<{run_id:string}>("/runs",{method:"POST",body:JSON.stringify({project_id:project.id,connection_id:f.get("connection_id"),suite_ids:suiteIds,max_concurrency:Number(f.get("max_concurrency"))})});location.href=`/runs/${r.run_id}`}catch(err){setMessage((err as Error).message)}}const verified=conns.data?.filter(c=>c.verification_state==="verified")??[];return <><PageHead eyebrow="Evaluation runner" title="Run bounded tests" description="Launch only against a connection verified by real inference. Progress and outcomes come from the persisted run."/>{message&&<Notice error>{message}</Notice>}<div className="grid two-col"><section className="card"><h2 style={{marginBottom:18}}>Run configuration</h2>{!project?<Empty title="Project required" text="Select a project before configuring a run."/>:<form className="form" onSubmit={launch}><div className="field"><label htmlFor="connection">Verified connection</label><select id="connection" className="select" name="connection_id" required><option value="">Select connection</option>{verified.map(c=><option key={c.id} value={c.id}>{c.model_id}</option>)}</select>{!verified.length&&<div className="hint">No verified connection. Verify a real inference call in Projects before launching.</div>}</div><fieldset className="field" style={{border:0,padding:0}}><legend>Suites</legend>{suites.data?.map(s=><label key={s.id} className="list-row"><span><span className={s.engine}>{s.name}</span><span className="table-sub">{s.case_count} cases</span></span><input type="checkbox" name="suite_ids" value={s.id}/></label>)}{!suites.data?.length&&<div className="hint">No suites available.</div>}</fieldset><div className="field"><label htmlFor="concurrency">Max concurrency</label><select id="concurrency" className="select" name="max_concurrency" defaultValue="2"><option>1</option><option>2</option><option>3</option><option>4</option></select></div><button className="btn btn-primary" disabled={!verified.length||!suites.data?.length}><Play size={16}/>Start evaluation</button></form>}</section><section className="card"><div className="card-head"><h2>Recent runs</h2></div>{runs.data?.length?<RunTable runs={runs.data.slice(0,6)}/>:<Empty title="No run history" text="Completed and interrupted runs appear here with errors kept separate from test failures."/>}</section></div></>}

export function RunDetailScreen({runId}:{runId:string}){const[refresh,setRefresh]=useState(0);const run=useLoad<Run>(`/runs/${runId}`,refresh);const results=useLoad<Results>(`/runs/${runId}/results`,refresh);useEffect(()=>{if(run.data&&["queued","running"].includes(run.data.status)){const timer=setTimeout(()=>setRefresh(v=>v+1),2500);return()=>clearTimeout(timer)}},[run.data,refresh]);const done=run.data?run.data.passed_count+run.data.failed_count+run.data.error_count+run.data.skipped_count:0;const pct=run.data?.total_cases?Math.round(done/run.data.total_cases*100):0;return <><PageHead eyebrow="Run evidence" title={`Run ${runId.slice(0,8)}`} description="Case outcomes, infrastructure errors, scoring explanations, and traces are preserved as separate evidence." action={<button className="btn btn-secondary" onClick={()=>setRefresh(v=>v+1)}><RefreshCw size={16}/>Refresh</button>}/>{run.error&&<Notice error>{run.error}</Notice>}{run.data&&<><div className="grid metrics"><Metric label="Status" value={run.data.status.replaceAll("_"," ")} note={fmt(run.data.completed_at??run.data.started_at)}/><Metric label="Passed" value={String(run.data.passed_count)} note={`of ${run.data.total_cases} cases`} tone="guard"/><Metric label="Failed" value={String(run.data.failed_count)} note="Valid model responses that missed the rule" tone="shield"/><Metric label="Errors" value={String(run.data.error_count)} note="Service and infrastructure outcomes" tone="pulse"/></div><div className="card" style={{marginBottom:16}}><div className="card-head"><h2>Execution progress</h2><StatusBadge status={run.data.status}/></div><div className="progress"><span style={{width:`${pct}%`}}/></div><p className="hint">{done} of {run.data.total_cases} terminal cases · pass rate {percent(run.data.pass_rate)}</p><p className="hint mono">Scoring {run.data.scoring_version} · Model {run.data.model_id??"not recorded"}</p></div></>}{results.data?.items.length?<ResultsExplorer items={results.data.items}/>:!results.loading&&<Empty title="No case evidence yet" text="Queued cases will appear after execution begins. An inference error is never counted as a pass or failure."/>}</>}
function ResultsExplorer({items}:{items:RunCase[]}){const[selected,setSelected]=useState(items[0]);useEffect(()=>setSelected(items[0]),[items]);return <div className="split"><section className="card case-list"><div className="card-head"><h2>Cases</h2><span className="hint">{items.length} shown</span></div>{items.map(item=><button key={item.run_case_id} className={`case-button ${selected.run_case_id===item.run_case_id?"active":""}`} onClick={()=>setSelected(item)}><div className="list-row"><span><span className="table-title">{item.name??"Unnamed case"}</span><span className="table-sub">{item.engine} · {item.category??"uncategorized"}</span></span><StatusBadge status={item.state}/></div></button>)}</section><section className="card"><div className="card-head"><h2>{selected.name}</h2><StatusBadge status={selected.state}/></div><div className="stack"><Detail label="Prompt" value={String(selected.case_snapshot.user_prompt??"Not retained")}/><Detail label="Expected rule" value={JSON.stringify(selected.case_snapshot.evaluator_config??{},null,2)}/><Detail label="Explanation" value={selected.explanation??selected.error??"No explanation recorded."}/><Detail label="Actual response" value={selected.traces[0]?.response_text??selected.traces[0]?.error_message??"No response content retained."}/><div className="hint">Trace {selected.traces[0]?.trace_id??"not recorded"} · {selected.traces[0]?.latency_ms??"—"} ms · severity {selected.severity??"not set"}</div></div></section></div>}
function Detail({label,value}:{label:string;value:string}){return <div><div className="metric-label" style={{marginBottom:7}}>{label}</div><div className="code mono">{value}</div></div>}

export function ResultsScreen(){const{project}=useWorkspace();const runs=useLoad<Run[]>(project?`/runs?project_id=${project.id}`:null);return <><PageHead eyebrow="Evidence explorer" title="Results" description="Inspect observed outputs and scoring rationale. Severity and infrastructure errors remain distinct from outcomes."/>{runs.error&&<Notice error>{runs.error}</Notice>}{runs.data?.length?<RunTable runs={runs.data}/>:<Empty icon={ShieldCheck} title="No results to inspect" text="Launch an evaluation to create real case evidence. Prism does not populate this view with samples."/>}</>}

export function PulseScreen(){const{project}=useWorkspace();const metrics=useLoad<Metrics>(project?`/metrics/summary?project_id=${project.id}`:null);const traces=useLoad<TracePage>(project?`/traces?project_id=${project.id}&limit=20`:null);const attempts=metrics.data?.inference.attempts??0;const samples=metrics.data?.latency_ms.sample_count??0;return <><PageHead eyebrow="Evaluation-time observability" title="Pulse" description="Metrics shown here come only from Prism evaluation calls persisted by the API."/>{metrics.error&&<Notice error>{metrics.error}</Notice>}<div className="grid metrics"><Metric label="Recorded attempts" value={String(attempts)} note="Persisted evaluation traces"/><Metric label="Successful calls" value={String(metrics.data?.inference.successful??0)} note="Valid upstream responses" tone="guard"/><Metric label="Blocked calls" value={String(metrics.data?.inference.blocked??0)} note="Not counted as model failures" tone="shield"/><Metric label="p95 latency" value={metrics.data?.latency_ms.p95!=null?`${Math.round(metrics.data.latency_ms.p95)} ms`:"—"} note={samples<2?"Not enough successful attempts":`${samples} successful attempts`} tone="pulse"/></div>{attempts===0?<Empty icon={Activity} title="No Pulse data" text="Pulse begins recording after Prism executes real inference requests. No trendline is shown without genuine observations."/>:<section className="card"><div className="card-head"><div><h2>Recent traces</h2><p className="hint">Mean {metrics.data?.latency_ms.mean??"—"} ms · median {metrics.data?.latency_ms.median??"—"} ms · {metrics.data?.models_seen.join(", ")||"no model observed"}</p></div><span className="hint">{traces.data?.total??attempts} recorded</span></div><div className="table-wrap"><table className="table"><thead><tr><th>Trace</th><th>Outcome</th><th>Latency</th><th>Upstream</th><th>Recorded</th></tr></thead><tbody>{traces.data?.items.map(trace=><tr key={trace.trace_id}><td><div className="table-title mono">{trace.trace_id.slice(0,8)}</div><div className="table-sub">Attempt {trace.attempt} · {trace.model_id??"unknown model"}</div></td><td><StatusBadge status={trace.outcome}/></td><td>{trace.latency_ms!=null?`${trace.latency_ms} ms`:"—"}</td><td>{trace.upstream_status??"—"}</td><td>{fmt(trace.recorded_at)}</td></tr>)}</tbody></table></div></section>}</>}

export function ReportsScreen(){const{project}=useWorkspace();const runs=useLoad<Run[]>(project?`/runs?project_id=${project.id}`:null);const[error,setError]=useState("");const eligible=useMemo(()=>runs.data?.filter(r=>!["queued","running"].includes(r.status))??[],[runs.data]);async function exportRun(id:string,format:"json"|"csv"){setError("");try{await download(`/reports/${id}/export?format=${format}`,`atlas-prism-${id}.${format}`)}catch(e){setError((e as Error).message)}}return <><PageHead eyebrow="Reproducible exports" title="Reports" description="Exports include observed results and scoring configuration. They do not certify model safety."/>{error&&<Notice error>{error}</Notice>}{eligible.length?<section className="card"><div className="card-head"><h2>Run evidence</h2><span className="hint">Machine-readable exports</span></div><div className="stack">{eligible.map(r=><div className="list-row" key={r.id}><div><div className="table-title mono">Run {r.id.slice(0,8)}</div><div className="table-sub">{r.model_id??"Model unavailable"} · {fmt(r.completed_at??r.created_at)} · {r.total_cases} cases</div></div><div className="top-actions"><button className="btn btn-secondary" onClick={()=>exportRun(r.id,"json")}><Download size={15}/>JSON</button><button className="btn btn-secondary" onClick={()=>exportRun(r.id,"csv")}><Download size={15}/>CSV</button></div></div>)}</div></section>:<Empty icon={FileDown} title="No exportable runs" text="A report becomes available after a run reaches a terminal state. Prism never substitutes a sample report."/>}</>}
