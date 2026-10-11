"use client";
import Image from "next/image";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { Notice } from "@/components/workspace";
export default function Login() {
  const router=useRouter(); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError("");const form=new FormData(e.currentTarget);try{const r=await api<{access_token:string}>("/auth/login",{method:"POST",body:JSON.stringify({email:form.get("email"),password:form.get("password")})});setToken(r.access_token);router.push("/dashboard");}catch(err){setError((err as Error).message)}finally{setBusy(false)}}
  return <main className="login-page"><section className="card login-card"><div className="brand login-brand"><span className="brand-logo large"><Image src="/atlas-prism-logo.png" alt="ATLAS Prism crystal" width={44} height={44}/></span><div><div className="brand-title">ATLAS Prism</div><div className="brand-sub">Guard · Shield · Pulse</div></div></div><h1>Evaluation evidence, in focus.</h1><p className="lede">Sign in to test an authorized N-ATLAS connection and inspect reproducible results.</p>{error&&<Notice error>{error}</Notice>}<form className="form" onSubmit={submit}><div className="field"><label htmlFor="email">Email</label><input className="input" id="email" name="email" type="email" autoComplete="username" required/></div><div className="field"><label htmlFor="password">Password</label><input className="input" id="password" name="password" type="password" autoComplete="current-password" required/></div><button className="btn btn-primary" disabled={busy}>{busy?"Signing in…":"Sign in"}</button></form></section></main>;
}
