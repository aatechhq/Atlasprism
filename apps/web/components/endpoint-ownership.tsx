"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { CheckCircle2, Copy, Globe2, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { HostVerification, HostVerificationInstructions, Project } from "@/lib/types";
import { Empty, Notice, StatusBadge } from "@/components/workspace";

export function EndpointOwnership({ project }: { project: Project | null }) {
  const [records, setRecords] = useState<HostVerification[]>([]);
  const [selected, setSelected] = useState<HostVerification | null>(null);
  const [instructions, setInstructions] = useState<HostVerificationInstructions | null>(null);
  const [method, setMethod] = useState<"dns_txt" | "https_file">("dns_txt");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);

  const loadRecords = useCallback(async () => {
    if (!project) { setRecords([]); setSelected(null); setInstructions(null); return; }
    try {
      const data = await api<HostVerification[]>(`/verifications?project_id=${project.id}`);
      setRecords(data);
      setSelected(current => data.find(item => item.id === current?.id) ?? data[0] ?? null);
    } catch (error) { setMessage((error as Error).message); setIsError(true); }
  }, [project]);

  useEffect(() => { void loadRecords(); }, [loadRecords]);
  useEffect(() => {
    if (!selected) { setInstructions(null); return; }
    void api<HostVerificationInstructions>(`/verifications/${selected.id}/instructions`)
      .then(setInstructions)
      .catch(error => { setMessage((error as Error).message); setIsError(true); });
  }, [selected?.id]);

  function report(text: string, error = false) { setMessage(text); setIsError(error); }

  async function begin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!project) return;
    setBusy(true); report("");
    const form = event.currentTarget; const data = new FormData(form);
    try {
      const record = await api<HostVerification>("/verifications", { method: "POST", body: JSON.stringify({ project_id: project.id, host: data.get("host") }) });
      form.reset(); setSelected(record); await loadRecords(); report("Verification instructions are ready. Publish either method below, then run the check.");
    } catch (error) { report((error as Error).message, true); }
    finally { setBusy(false); }
  }

  async function check() {
    if (!selected) return; setBusy(true); report("");
    try {
      const record = await api<HostVerification>(`/verifications/${selected.id}/check?method=${method}`, { method: "POST" });
      setSelected(record); await loadRecords(); report(`${record.host} is verified for this project.`);
    } catch (error) { report((error as Error).message, true); await loadRecords(); }
    finally { setBusy(false); }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!project || !selected?.verified_at) return;
    setBusy(true); report(""); const data = new FormData(event.currentTarget);
    try {
      await api("/connections", { method: "POST", body: JSON.stringify({ project_id: project.id, provider: "openai_compatible", endpoint: data.get("endpoint"), model_id: data.get("model_id") || null }) });
      report("Application endpoint connected. Verify it with a real inference call in the connection list above.");
      window.location.reload();
    } catch (error) { report((error as Error).message, true); }
    finally { setBusy(false); }
  }

  async function copy(value: string) { await navigator.clipboard.writeText(value); report("Copied to clipboard."); }

  return <section className="card endpoint-ownership">
    <div className="card-head"><div><p className="section-label">Developer-owned application</p><h2>Connect your own endpoint</h2></div><Globe2 size={21}/></div>
    <p className="endpoint-intro">Prism can test the assistant you actually ship, including its retrieval, tools and guardrails. Ownership proof is required before Shield can send adversarial traffic.</p>
    {message && <Notice error={isError}>{message}</Notice>}
    {!project ? <Empty title="Select a project first" text="Ownership proof and the resulting connection belong to one project."/> : <div className="ownership-flow">
      <div className="ownership-step"><span>01</span><div><strong>Claim the hostname</strong><p>Use a bare public hostname. Verification proves control; it does not certify that the endpoint is safe.</p></div></div>
      <form className="ownership-inline" onSubmit={begin}><input className="input mono" name="host" required placeholder="api.example.com" aria-label="Endpoint hostname"/><button className="btn btn-secondary" disabled={busy}>Start verification</button></form>
      {records.length > 0 && <div className="verification-list">{records.map(record => <button type="button" key={record.id} className={record.id === selected?.id ? "active" : ""} onClick={() => setSelected(record)}><span><strong>{record.host}</strong><small>{record.verified_at ? `Verified by ${record.method?.replace("_", " ")}` : record.last_error || "Waiting for proof"}</small></span><StatusBadge status={record.verified_at ? "verified" : "unverified"}/></button>)}</div>}
      {selected && instructions && <>
        <div className="ownership-step"><span>02</span><div><strong>Publish one proof</strong><p>Choose DNS or a no-redirect HTTPS file. Prism checks the live public value.</p></div></div>
        <div className="proof-tabs" role="tablist" aria-label="Verification method"><button type="button" className={method === "dns_txt" ? "active" : ""} onClick={() => setMethod("dns_txt")}>DNS TXT</button><button type="button" className={method === "https_file" ? "active" : ""} onClick={() => setMethod("https_file")}>HTTPS file</button></div>
        {method === "dns_txt" ? <div className="proof-card"><Proof label="Record name" value={instructions.methods.dns_txt.record_name} onCopy={copy}/><Proof label="Record value" value={instructions.methods.dns_txt.record_value} onCopy={copy}/><p>{instructions.methods.dns_txt.note}</p></div> : <div className="proof-card"><Proof label="File URL" value={instructions.methods.https_file.url} onCopy={copy}/><Proof label="File contents" value={instructions.methods.https_file.contents} onCopy={copy}/><p>{instructions.methods.https_file.note}</p></div>}
        <button className="btn btn-secondary" type="button" onClick={check} disabled={busy || Boolean(selected.verified_at)}>{selected.verified_at ? <><CheckCircle2 size={16}/>Ownership verified</> : <><RefreshCw size={15}/>Check published proof</>}</button>
        {selected.verified_at && <><div className="ownership-step"><span>03</span><div><strong>Connect the application</strong><p>Give the HTTPS base URL. Prism calls <code>/v1/chat/completions</code> and refuses redirects, private addresses and unsafe DNS results.</p></div></div><form className="form endpoint-connect-form" onSubmit={connect}><div className="field"><label htmlFor="owned-endpoint">HTTPS base URL</label><input className="input mono" id="owned-endpoint" name="endpoint" type="url" required defaultValue={`https://${selected.host}`}/></div><div className="field"><label htmlFor="owned-model">Model label <span className="hint">— reported, not independently proven</span></label><input className="input mono" id="owned-model" name="model_id" placeholder="application-under-test"/></div><button className="btn btn-primary" disabled={busy}><ShieldCheck size={16}/>Connect verified endpoint</button></form></>}
      </>}
    </div>}
  </section>;
}

function Proof({ label, value, onCopy }: { label: string; value: string; onCopy: (value: string) => Promise<void> }) {
  return <div className="proof-row"><span>{label}</span><code>{value}</code><button type="button" onClick={() => void onCopy(value)} aria-label={`Copy ${label}`}><Copy size={14}/></button></div>;
}
