import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check, Gauge, LockKeyhole, ScanSearch } from "lucide-react";

const steps = ["Connect", "Test", "Understand", "Reproduce", "Export"];

export default function HomePage() {
  return (
    <main className="landing-page">
      <header className="landing-nav">
        <Link className="landing-brand" href="/" aria-label="ATLAS Prism home">
          <Image src="/atlas-prism-logo.png" alt="" width={42} height={42} priority />
          <span>ATLAS Prism</span>
        </Link>
        <nav aria-label="Account">
          <Link className="landing-login" href="/login">Sign in</Link>
          <Link className="btn btn-primary" href="/signup">Create account <ArrowRight size={16} /></Link>
        </nav>
      </header>

      <section className="landing-hero">
        <div className="landing-hero-copy">
          <p className="landing-kicker">Independent N-ATLAS assurance</p>
          <h1>See what your model does. Keep the evidence.</h1>
          <p className="landing-intro">Test quality, security, and performance with a reproducible record built for review.</p>
          <div className="landing-actions">
            <Link className="btn btn-primary" href="/signup">Start evaluating <ArrowRight size={16} /></Link>
            <Link className="btn btn-secondary" href="/login">Open workspace</Link>
          </div>
          <p className="landing-independence">Independent evaluation tooling. Not an official N-ATLAS service.</p>
        </div>
        <div className="prism-stage" aria-hidden="true">
          <div className="prism-orbit prism-orbit-one" />
          <div className="prism-orbit prism-orbit-two" />
          <div className="prism-frame">
            <Image src="/atlas-prism-logo.png" alt="" fill sizes="(max-width: 800px) 70vw, 42vw" priority />
          </div>
        </div>
      </section>

      <section className="workflow-strip" aria-label="Evaluation workflow">
        <p>One traceable workflow</p>
        <ol>{steps.map((step, index) => <li key={step}><span>{String(index + 1).padStart(2, "0")}</span>{step}</li>)}</ol>
      </section>

      <section className="landing-system">
        <div className="system-heading">
          <p className="landing-kicker">Three evaluation lenses</p>
          <h2>A clear reading of model behavior.</h2>
          <p>Each engine produces inspectable results without collapsing uncertainty into a decorative score.</p>
        </div>
        <div className="engine-grid">
          <article className="engine-card guard-card">
            <span className="engine-index">01 / Guard</span><ScanSearch />
            <h3>Quality under pressure</h3><p>Test task behavior against explicit cases and retain the model response behind every result.</p>
          </article>
          <article className="engine-card shield-card">
            <span className="engine-index">02 / Shield</span><LockKeyhole />
            <h3>Security you can inspect</h3><p>Probe defined risks, record findings, and keep errors outside the pass-rate calculation.</p>
          </article>
          <article className="engine-card pulse-card">
            <span className="engine-index">03 / Pulse</span><Gauge />
            <h3>Performance in context</h3><p>Read latency with its sample count, model identity, and connection evidence attached.</p>
          </article>
        </div>
      </section>

      <section className="evidence-band">
        <div><p className="landing-kicker">The evidence ledger</p><h2>Every conclusion has a path back to the run.</h2></div>
        <ul>
          <li><Check size={17} /> Versioned suites and scoring</li>
          <li><Check size={17} /> Response excerpts and latency</li>
          <li><Check size={17} /> Exportable run records</li>
        </ul>
        <Link className="btn btn-primary" href="/signup">Create your workspace <ArrowRight size={16} /></Link>
      </section>

      <footer className="landing-footer"><span>ATLAS Prism</span><span>Evaluation assurance for N-ATLAS integrations</span></footer>
    </main>
  );
}
