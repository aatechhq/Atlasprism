import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check, Gauge, GitCompare, Languages, LockKeyhole, ScanSearch } from "lucide-react";

const steps = ["Define", "Connect", "Evaluate", "Compare", "Release"];

const decisions = [
  {
    title: "Compare what changed",
    text: "Read case-by-case regressions and improvements with confidence warnings when sampled generations can flip.",
    icon: GitCompare,
  },
  {
    title: "Retest the misses",
    text: "Run only failed or errored cases again, then compare the new evidence with the original run.",
    icon: ScanSearch,
  },
  {
    title: "Apply your release policy",
    text: "Evaluate pass-rate and critical-finding thresholds without presenting a policy decision as a safety guarantee.",
    icon: LockKeyhole,
  },
  {
    title: "Understand language performance",
    text: "Inspect outcomes and latency by each test case's declared language, with sample counts kept visible.",
    icon: Languages,
  },
];

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
          <h1>Test your AI application. Keep the evidence.</h1>
          <p className="landing-intro">Evaluate quality, security, and latency against your own rules, then compare changes before release.</p>
          <div className="landing-actions">
            <Link className="btn btn-primary" href="/signup">Create account <ArrowRight size={16} /></Link>
            <Link className="btn btn-secondary" href="/login">Sign in</Link>
          </div>
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
        <div>
          <strong>One traceable path</strong>
          <span>Independent tooling, not an official N-ATLAS service.</span>
        </div>
        <ol>{steps.map(step => <li key={step}>{step}</li>)}</ol>
      </section>

      <section className="landing-system">
        <div className="system-heading">
          <p className="landing-kicker">Product outline</p>
          <h2>Guard. Shield. Pulse.</h2>
          <p>Three parts inspect the same application from quality, security, and performance perspectives. Every conclusion stays connected to one evaluation record.</p>
        </div>
        <div className="engine-grid">
          <article className="engine-card guard-card">
            <div className="engine-card-head"><span className="engine-index">01 / Guard</span><span className="engine-role">Quality</span></div><ScanSearch />
            <h3>Did the application follow its rules?</h3><p>Apply your application prompt before every case and retain the model response and scoring rationale behind each result.</p>
            <span className="engine-output">Produces scored case evidence</span>
          </article>
          <article className="engine-card shield-card">
            <div className="engine-card-head"><span className="engine-index">02 / Shield</span><span className="engine-role">Security</span></div><LockKeyhole />
            <h3>Can bounded attacks override those rules?</h3><p>Inspect authorized security outcomes with severity rationale, redacted evidence, and mitigation guidance.</p>
            <span className="engine-output">Produces actionable findings</span>
          </article>
          <article className="engine-card pulse-card">
            <div className="engine-card-head"><span className="engine-index">03 / Pulse</span><span className="engine-role">Observability</span></div><Gauge />
            <h3>What happened during real inference?</h3><p>Read latency, trace outcomes, model identity, and language-level sample counts from persisted calls.</p>
            <span className="engine-output">Produces performance context</span>
          </article>
        </div>
      </section>

      <section className="decision-section">
        <div className="decision-intro">
          <p className="landing-kicker">After the first run</p>
          <h2>Turn evaluation into a release decision.</h2>
          <p>Prism helps a developer answer the practical question: did the change improve the application, and is the evidence complete enough to proceed?</p>
        </div>
        <div className="decision-list">
          {decisions.map(({ title, text, icon: Icon }) => (
            <article className="decision-row" key={title}>
              <Icon aria-hidden="true" />
              <div><h3>{title}</h3><p>{text}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="evidence-band">
        <div><h2>Every conclusion has a path back to the run.</h2><p>Versioned suites, immutable snapshots, response excerpts, traces, and exports keep the result reviewable.</p></div>
        <ul>
          <li><Check size={17} /> Errors stay outside the pass rate</li>
          <li><Check size={17} /> Threshold checks show observed values</li>
          <li><Check size={17} /> JSON and CSV evidence exports</li>
        </ul>
        <Link className="btn btn-primary" href="/signup">Create account <ArrowRight size={16} /></Link>
      </section>

      <footer className="landing-footer"><span>ATLAS Prism</span><span>Evaluation assurance for N-ATLAS integrations</span></footer>
    </main>
  );
}
