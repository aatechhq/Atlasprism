"use client";

import { FormEvent, useEffect, useState } from "react";
import { Boxes, Building2, Database, Plus, Users } from "lucide-react";
import { api } from "@/lib/api";
import type { Dataset, Organization, OrganizationMember, Suite } from "@/lib/types";
import { Empty, Notice, PageHead, StatusBadge, useWorkspace } from "@/components/workspace";

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

function readCases(value: FormDataEntryValue | null) {
  const parsed: unknown = JSON.parse(String(value ?? "[]"));
  if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("Paste a JSON array containing at least one test case.");
  return parsed;
}

export function LibraryScreen() {
  const { project } = useWorkspace();
  const [refresh, setRefresh] = useState(0);
  const datasets = useLoad<Dataset[]>("/datasets", refresh);
  const organizations = useLoad<Organization[]>("/organizations", refresh);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const selectedDataset = datasets.data?.find(item => item.id === selectedDatasetId) ?? datasets.data?.[0] ?? null;
  const selectedOrg = organizations.data?.find(item => item.id === selectedOrgId) ?? organizations.data?.[0] ?? null;
  useEffect(() => { if (!selectedDatasetId && datasets.data?.[0]) setSelectedDatasetId(datasets.data[0].id); }, [datasets.data, selectedDatasetId]);
  useEffect(() => { if (!selectedOrgId && organizations.data?.[0]) setSelectedOrgId(organizations.data[0].id); }, [organizations.data, selectedOrgId]);

  return <>
    <PageHead eyebrow="Reusable assurance infrastructure" title="Library & team" description="Version test libraries once, instantiate them into projects, and give collaborators only the access their role needs."/>
    <div className="library-lead">
      <section className="card library-principle"><Database size={24}/><div><p className="section-label">Dataset versions</p><h2>Reuse without rewriting history</h2><p>Every update creates a new immutable version. Suites record which version they came from.</p></div></section>
      <section className="card library-principle"><Users size={24}/><div><p className="section-label">Project access</p><h2>Share by role, not by credential</h2><p>Owners and admins manage access; members can work; viewers stay read-only.</p></div></section>
    </div>
    {(datasets.error || organizations.error) && <Notice error>{datasets.error || organizations.error}</Notice>}
    <DatasetWorkspace datasets={datasets.data ?? []} selected={selectedDataset} selectedId={selectedDatasetId} onSelect={setSelectedDatasetId} organizations={organizations.data ?? []} projectId={project?.id ?? null} onChanged={() => setRefresh(value => value + 1)}/>
    <TeamWorkspace organizations={organizations.data ?? []} selected={selectedOrg} selectedId={selectedOrgId} onSelect={setSelectedOrgId} projectId={project?.id ?? null} onChanged={() => setRefresh(value => value + 1)}/>
  </>;
}

function DatasetWorkspace({ datasets, selected, selectedId, onSelect, organizations, projectId, onChanged }: { datasets: Dataset[]; selected: Dataset | null; selectedId: string; onSelect: (id: string) => void; organizations: Organization[]; projectId: string | null; onChanged: () => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    const form = event.currentTarget; const data = new FormData(form);
    try { await api<Dataset>("/datasets", { method: "POST", body: JSON.stringify({ name: data.get("name"), engine: data.get("engine"), description: data.get("description") || null, organization_id: data.get("organization_id") || null, cases: readCases(data.get("cases")) }) }); form.reset(); setMessage("Dataset created with version 1."); onChanged(); }
    catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  async function addVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; setBusy(true); setMessage("");
    const form = event.currentTarget; const data = new FormData(form);
    try { await api(`/datasets/${selected.id}/versions`, { method: "POST", body: JSON.stringify({ cases: readCases(data.get("cases")), notes: data.get("notes") || null }) }); form.reset(); setMessage("A new immutable dataset version was created."); onChanged(); }
    catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  async function instantiate() {
    if (!selected || !projectId) return; setBusy(true); setMessage("");
    try { const suite = await api<Suite>(`/datasets/${selected.id}/instantiate`, { method: "POST", body: JSON.stringify({ project_id: projectId, version: selected.latest_version }) }); setMessage(`Created suite “${suite.name}” from version ${selected.latest_version}.`); }
    catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="library-section">
    <div className="library-section-head"><div><p className="section-label">Versioned test assets</p><h2>Dataset library</h2><p>Keep proven Guard and Shield cases independent of a single project.</p></div><span className="library-count">{datasets.length} {datasets.length === 1 ? "dataset" : "datasets"}</span></div>
    {message && <Notice error={!/created/.test(message)}>{message}</Notice>}
    <div className="library-workspace">
      <section className="card library-index">{datasets.length ? <>{datasets.map(item => <button type="button" key={item.id} onClick={() => onSelect(item.id)} className={`library-index-row ${item.id === selectedId ? "active" : ""}`}><span className={`engine-mark ${item.engine}`}><Boxes size={16}/></span><span><strong>{item.name}</strong><small>{item.engine} · v{item.latest_version ?? "—"} · {item.versions.at(-1)?.case_count ?? 0} cases</small></span></button>)}</> : <Empty icon={Database} title="No reusable datasets" text="Create a versioned library from real test cases. Prism will not insert sample evidence."/>}</section>
      <section className="card library-detail">{selected ? <><div className="card-head"><div><p className="section-label">Selected dataset</p><h2>{selected.name}</h2></div><StatusBadge status={selected.engine}/></div><p className="evidence-note">{selected.description ?? "No description provided."}</p><div className="version-ledger">{selected.versions.map(version => <div key={version.id}><span>v{version.version}</span><div><strong>{version.case_count} cases</strong><small>{version.notes ?? "No version note"}</small></div></div>)}</div><button className="btn btn-primary" onClick={instantiate} disabled={!projectId || busy}>Instantiate latest in selected project</button>{!projectId && <p className="hint">Select a project before instantiating this dataset.</p>}<details className="library-details"><summary>Add a new immutable version</summary><form className="form" onSubmit={addVersion}><div className="field"><label htmlFor="version-notes">Version notes</label><input id="version-notes" className="input" name="notes" placeholder="What changed and why"/></div><div className="field"><label htmlFor="version-cases">Cases JSON</label><textarea id="version-cases" className="textarea mono" name="cases" required placeholder='[{"name":"...","user_prompt":"...","evaluator_type":"..."}]'/></div><button className="btn btn-secondary" disabled={busy}>Create next version</button></form></details></> : <Empty title="Choose a dataset" text="Its immutable version history and project action will appear here."/>}</section>
      <section className="card library-create"><div className="card-head"><div><p className="section-label">New reusable asset</p><h2>Create dataset</h2></div><Plus size={18}/></div><form className="form" onSubmit={create}><div className="form-row"><div className="field"><label htmlFor="dataset-name">Name</label><input id="dataset-name" className="input" name="name" required/></div><div className="field"><label htmlFor="dataset-engine">Engine</label><select id="dataset-engine" className="select" name="engine"><option value="guard">Guard</option><option value="shield">Shield</option></select></div></div><div className="field"><label htmlFor="dataset-description">Purpose</label><input id="dataset-description" className="input" name="description"/></div><div className="field"><label htmlFor="dataset-org">Access</label><select id="dataset-org" className="select" name="organization_id"><option value="">Personal library</option>{organizations.map(org => <option value={org.id} key={org.id}>{org.name}</option>)}</select></div><div className="field"><label htmlFor="dataset-cases">Cases JSON</label><textarea id="dataset-cases" className="textarea mono" name="cases" required placeholder='[{"name":"...","user_prompt":"...","evaluator_type":"..."}]'/><p className="hint">Every case needs a name, user prompt, and machine-checkable evaluator type.</p></div><button className="btn btn-primary" disabled={busy}>{busy ? "Creating…" : "Create versioned dataset"}</button></form></section>
    </div>
  </section>;
}

function TeamWorkspace({ organizations, selected, selectedId, onSelect, projectId, onChanged }: { organizations: Organization[]; selected: Organization | null; selectedId: string; onSelect: (id: string) => void; projectId: string | null; onChanged: () => void }) {
  const [memberRefresh, setMemberRefresh] = useState(0);
  const members = useLoad<OrganizationMember[]>(selected ? `/organizations/${selected.id}/members` : null, memberRefresh);
  const [message, setMessage] = useState(""); const [busy, setBusy] = useState(false);
  async function createOrg(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setMessage(""); const form = event.currentTarget; const data = new FormData(form); try { await api("/organizations", { method: "POST", body: JSON.stringify({ name: data.get("name") }) }); form.reset(); setMessage("Organization created."); onChanged(); } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); } }
  async function addMember(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!selected) return; setBusy(true); setMessage(""); const form = event.currentTarget; const data = new FormData(form); try { await api(`/organizations/${selected.id}/members`, { method: "POST", body: JSON.stringify({ email: data.get("email"), role: data.get("role") }) }); form.reset(); setMessage("Member added."); setMemberRefresh(value => value + 1); onChanged(); } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); } }
  async function shareProject() { if (!selected || !projectId) return; setBusy(true); setMessage(""); try { await api(`/projects/${projectId}/organization?org_id=${selected.id}`, { method: "POST" }); setMessage("Selected project shared with this organization."); } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); } }
  return <section className="library-section team-section"><div className="library-section-head"><div><p className="section-label">Role-based collaboration</p><h2>Organizations & access</h2><p>People must already have a Prism account before they can be added.</p></div><Building2 size={24}/></div>{message && <Notice error={!/created|added|shared/.test(message)}>{message}</Notice>}<div className="team-grid"><section className="card"><div className="card-head"><h3>Your organizations</h3><span className="hint">{organizations.length} accessible</span></div>{organizations.length ? <div className="organization-list">{organizations.map(org => <button type="button" key={org.id} onClick={() => onSelect(org.id)} className={org.id === selectedId ? "active" : ""}><span><strong>{org.name}</strong><small>{org.member_count ?? 0} members</small></span><StatusBadge status={org.role ?? "member"}/></button>)}</div> : <Empty icon={Users} title="No organization yet" text="Create one when another person needs governed access to a shared project or dataset."/>}<form className="inline-create" onSubmit={createOrg}><input className="input" name="name" aria-label="Organization name" placeholder="Organization name" required/><button className="btn btn-secondary" disabled={busy}><Plus size={15}/>Create</button></form></section><section className="card"><div className="card-head"><div><p className="section-label">Membership</p><h3>{selected?.name ?? "Choose an organization"}</h3></div>{selected && <StatusBadge status={selected.role ?? "member"}/>}</div>{members.error && <Notice error>{members.error}</Notice>}{selected && <>{members.data?.length ? <div className="member-list">{members.data.map(member => <div key={member.user_id}><span><strong>{member.email}</strong><small>Joined {new Intl.DateTimeFormat("en-NG", { dateStyle: "medium" }).format(new Date(member.created_at))}</small></span><StatusBadge status={member.role}/></div>)}</div> : !members.loading && <p className="hint">No members returned.</p>}<form className="member-form" onSubmit={addMember}><div className="field"><label htmlFor="member-email">Existing account email</label><input id="member-email" className="input" type="email" name="email" required/></div><div className="field"><label htmlFor="member-role">Role</label><select id="member-role" className="select" name="role" defaultValue="member"><option value="viewer">Viewer</option><option value="member">Member</option><option value="admin">Admin</option><option value="owner">Owner</option></select></div><button className="btn btn-secondary" disabled={busy}>Add member</button></form><button className="btn btn-primary" onClick={shareProject} disabled={!projectId || busy}>Share selected project with team</button>{!projectId && <p className="hint">Select a project first.</p>}</>}</section></div></section>;
}
