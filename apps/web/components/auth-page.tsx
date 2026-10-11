"use client";

import Image from "next/image";
import Link from "next/link";
import type { ComponentProps } from "react";
import { AuthView } from "@neondatabase/auth/react/ui";

type AuthPath = ComponentProps<typeof AuthView>["path"];

export function AuthPage({ mode }: { mode: AuthPath }) {
  const signingUp = mode === "sign-up";
  return (
    <main className="auth-page">
      <section className="auth-context" aria-label="About ATLAS Prism">
        <Link className="landing-brand" href="/" aria-label="ATLAS Prism home">
          <Image src="/atlas-prism-logo.png" alt="" width={48} height={48} priority />
          <span>ATLAS Prism</span>
        </Link>
        <div className="auth-context-copy">
          <p className="landing-kicker">Independent N-ATLAS assurance</p>
          <h1>{signingUp ? "Build evidence before you ship." : "Return to your evaluation record."}</h1>
          <p>Connect a model endpoint, test its behavior, and export a reproducible evidence trail.</p>
        </div>
        <ol className="auth-proof-list">
          <li><span>01</span>Behavior and quality checks</li>
          <li><span>02</span>Security-focused probes</li>
          <li><span>03</span>Latency and reliability evidence</li>
        </ol>
      </section>
      <section className="auth-panel" aria-label={signingUp ? "Create account" : "Sign in"}>
        <div className="auth-panel-inner">
          <AuthView path={mode} />
        </div>
      </section>
    </main>
  );
}
