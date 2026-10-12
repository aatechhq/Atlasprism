"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Circle } from "lucide-react";
import { api } from "@/lib/api";
import type { Run } from "@/lib/types";
import { StatusBadge } from "@/components/workspace";

export const WORKFLOW = [
  { number: "01", href: "/projects", label: "Configure", short: "Project and model" },
  { number: "02", href: "/suites", label: "Design tests", short: "Guard and Shield" },
  { number: "03", href: "/runs", label: "Run", short: "Execute evaluation" },
  { number: "04", href: "/results", label: "Inspect", short: "Evidence and findings" },
  { number: "05", href: "/reports", label: "Export", short: "Report and gate" },
] as const;

export function useResource<T>(path: string | null, refreshKey = 0) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) { setData(null); setError(""); return; }
    let active = true;
    setLoading(true); setError("");
    api<T>(path).then(value => { if (active) setData(value); }).catch(reason => { if (active) setError((reason as Error).message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [path, refreshKey]);
  return { data, loading, error };
}

export function FlowHeader({ step, title, description, actions, back }: { step?: number; title: string; description: string; actions?: React.ReactNode; back?: { href: string; label: string } }) {
  return <header className="flow-header">
    <div className="flow-heading">
      {back && <Link className="flow-back" href={back.href}><ArrowLeft size={14}/>{back.label}</Link>}
      <div className="flow-kicker">{step ? `Step ${String(step).padStart(2, "0")} / 05` : "Evaluation workspace"}</div>
      <h1>{title}</h1>
      <p>{description}</p>
    </div>
    {actions && <div className="flow-actions">{actions}</div>}
  </header>;
}

export function ContinueBar({ eyebrow = "Next step", title, description, href, action }: { eyebrow?: string; title: string; description: string; href: string; action: string }) {
  return <section className="continue-bar"><div><span>{eyebrow}</span><strong>{title}</strong><p>{description}</p></div><Link className="btn btn-primary" href={href}>{action}<ArrowRight size={15}/></Link></section>;
}

export function Kpi({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) {
  return <div className={`kpi ${tone}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>;
}

export function RunLedger({ runs, compact = false }: { runs: Run[]; compact?: boolean }) {
  return <div className="run-ledger">{runs.map(run => <Link href={`/runs/${run.id}`} key={run.id} className="run-ledger-row">
    <span className="run-id mono">{run.id.slice(0, 8)}</span>
    <span className="run-model"><strong>{run.model_id ?? "Model unavailable"}</strong><small>{formatDate(run.started_at ?? run.created_at)}</small></span>
    {!compact && <span className="run-outcomes"><strong>{run.passed_count} / {run.failed_count} / {run.error_count}</strong><small>pass / fail / error</small></span>}
    <span className="run-rate"><strong>{percent(run.pass_rate)}</strong><small>{run.total_cases} cases</small></span>
    <StatusBadge status={run.status}/>
    <ArrowRight className="run-arrow" size={16}/>
  </Link>)}</div>;
}

export function ReadinessLine({ ready, title, detail, href }: { ready: boolean; title: string; detail: string; href: string }) {
  return <Link href={href} className={`readiness-line ${ready ? "ready" : "pending"}`}><span className="readiness-node">{ready ? <Check size={13}/> : <Circle size={8}/>}</span><span><strong>{title}</strong><small>{detail}</small></span><ArrowRight size={15}/></Link>;
}

export function formatDate(value: string | null | undefined) { return value ? new Intl.DateTimeFormat("en-NG", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Not recorded"; }
export function percent(value: number | null | undefined) { return value == null ? "—" : `${(value * 100).toFixed(1)}%`; }
