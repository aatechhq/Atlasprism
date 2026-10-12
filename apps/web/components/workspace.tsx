"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { Activity, BarChart3, BookOpenCheck, Boxes, FileDown, FolderKanban, LibraryBig, LogOut, Menu, Play, ShieldCheck, X } from "lucide-react";
import { api } from "@/lib/api";
import { authClient } from "@/lib/auth/client";
import type { Connection, Project } from "@/lib/types";

type Workspace = { projects: Project[]; project: Project | null; loading: boolean; error: string | null; setProjectId: (id: string) => void; refresh: () => Promise<void> };
const WorkspaceContext = createContext<Workspace | null>(null);
export function useWorkspace() { const value = useContext(WorkspaceContext); if (!value) throw new Error("WorkspaceProvider missing"); return value; }

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter(); const [projects, setProjects] = useState<Project[]>([]); const [projectId, setProjectIdState] = useState(""); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    setLoading(true); setError(null);
    try { const data = await api<Project[]>("/projects"); setProjects(data); setProjectIdState(current => current && data.some(p => p.id === current) ? current : (localStorage.getItem("prism_project") && data.some(p => p.id === localStorage.getItem("prism_project")) ? localStorage.getItem("prism_project")! : data[0]?.id ?? "")); }
    catch (e) {
      if ((e as { status?: number }).status === 401) {
        const session = await authClient.getSession();
        if (!session.data) router.replace("/login");
        else setError((e as Error).message);
      } else setError((e as Error).message);
    }
    finally { setLoading(false); }
  }, [router]);
  useEffect(() => { void refresh(); }, [refresh]);
  const setProjectId = (id: string) => { setProjectIdState(id); localStorage.setItem("prism_project", id); };
  const value = useMemo(() => ({ projects, project: projects.find(p => p.id === projectId) ?? null, loading, error, setProjectId, refresh }), [projects, projectId, loading, error, refresh]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

const overview = ["/dashboard", "Overview", BarChart3] as const;
const flowNav = [
  ["/projects", "Configure", FolderKanban, "01"], ["/suites", "Design tests", Boxes, "02"], ["/runs", "Run evaluation", Play, "03"], ["/results", "Inspect evidence", BookOpenCheck, "04"], ["/reports", "Export report", FileDown, "05"],
] as const;
const resourceNav = [["/pulse", "Pulse", Activity], ["/library", "Library & team", LibraryBig]] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname(); const router = useRouter(); const { projects, project, setProjectId } = useWorkspace(); const [open, setOpen] = useState(false); const [connectionState, setConnectionState] = useState("not_configured");
  useEffect(() => { if (!project) { setConnectionState("not_configured"); return; } let active = true; api<Connection[]>(`/connections?project_id=${project.id}`).then(items => { if (active) setConnectionState(items.some(item => item.verification_state === "verified") ? "verified" : items.length ? "unverified" : "not_configured"); }).catch(() => { if (active) setConnectionState("unavailable"); }); return () => { active = false; }; }, [project]);
  const flowItem = flowNav.find(([href]) => pathname.startsWith(href));
  const OverviewIcon = overview[2];
  const title = pathname.startsWith(overview[0]) ? overview[1] : flowItem?.[1] ?? resourceNav.find(([href]) => pathname.startsWith(href))?.[1] ?? "ATLAS Prism";
  const active = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return <div className="shell">
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Primary navigation">
      <div className="brand"><span className="brand-logo"><Image src="/atlas-prism-logo.png" alt="ATLAS Prism crystal" width={34} height={34} priority/></span><div className="brand-copy"><div className="brand-title">ATLAS Prism</div><div className="brand-sub">Evaluation assurance</div></div><button className="btn icon-btn mobile-menu" onClick={() => setOpen(false)} aria-label="Close navigation"><X size={18}/></button></div>
      <nav className="nav workflow-nav"><Link href={overview[0]} className={active(overview[0]) ? "active" : ""} onClick={() => setOpen(false)}><OverviewIcon/><span>{overview[1]}</span></Link><p>Evaluation flow</p>{flowNav.map(([href,label,Icon,number]) => <Link key={href} href={href} className={active(href) ? "active" : ""} onClick={() => setOpen(false)}><span className="nav-step">{number}</span><Icon/><span>{label}</span></Link>)}<p>Workspace</p>{resourceNav.map(([href,label,Icon]) => <Link key={href} href={href} className={active(href) ? "active" : ""} onClick={() => setOpen(false)}><Icon/><span>{label}</span></Link>)}</nav>
      <div className="sidebar-foot"><div className="api-label"><span className="dot"/><span>Fly API connected</span></div></div>
    </aside>
    <div className="content"><header className="topbar"><div className="top-context"><button className="btn btn-secondary icon-btn mobile-menu" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu size={18}/></button><div><span>{flowItem ? `Step ${flowItem[3]} of 05` : "ATLAS Prism"}</span><strong>{title}</strong></div></div><div className="top-actions"><StatusBadge status={connectionState}/><select className="select project-select" aria-label="Current project" value={project?.id ?? ""} onChange={e => setProjectId(e.target.value)} disabled={!projects.length}><option value="">{projects.length ? "Select project" : "No project"}</option>{projects.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select>{!pathname.startsWith("/runs") && <Link className="btn btn-primary top-run" href="/runs"><Play size={15}/>Run</Link>}<button className="btn btn-secondary icon-btn" aria-label="Sign out" title="Sign out" onClick={() => { void authClient.signOut().finally(() => router.push("/login")); }}><LogOut size={17}/></button></div></header><main className="main" id="main-content">{children}</main></div>
  </div>;
}

export function ProtectedLayout({ children }: { children: React.ReactNode }) { return <WorkspaceProvider><AppShell>{children}</AppShell></WorkspaceProvider>; }

export function PageHead({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) { return <div className="page-head"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="lede">{description}</p></div>{action}</div>; }
export function StatusBadge({ status }: { status: string }) { return <span className={`badge ${status.toLowerCase()}`}>{status.replaceAll("_", " ")}</span>; }
export function Empty({ icon: Icon = ShieldCheck, title, text, action }: { icon?: typeof ShieldCheck; title: string; text: string; action?: React.ReactNode }) { return <div className="empty"><Icon className="empty-icon"/><h3>{title}</h3><p>{text}</p>{action}</div>; }
export function Notice({ children, error = false }: { children: React.ReactNode; error?: boolean }) { return <div className={`notice ${error ? "error-box" : ""}`} role={error ? "alert" : "status"}><ShieldCheck size={18}/><div>{children}</div></div>; }
