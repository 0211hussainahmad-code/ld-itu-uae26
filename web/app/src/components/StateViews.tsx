import { Link } from "react-router";
import type { LoadOutcome } from "../lib/loader";
import { describe } from "../lib/verify";
import s from "./StateViews.module.css";

export function Loading({ progress, label = "Loading the verified replay" }: { progress: [number, number] | null; label?: string }) {
  const pct = progress ? Math.round((progress[0] / progress[1]) * 100) : 0;
  return (
    <section className={s.wrap} aria-busy="true" aria-live="polite">
      <div className={s.sonar} aria-hidden="true"><span /><span /><span /></div>
      <h1 className={s.title}>{progress ? "Checking the audit record in your browser" : label}</h1>
      <p className={s.text}>{progress ? `${progress[0]} of ${progress[1]} records rehashed` : "Fetching the bundle and its listed hash."}</p>
      <div className={s.bar} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Verification progress">{progress && <i style={{ width: `${pct}%` }} />}</div>
    </section>
  );
}

export function Empty() {
  return (
    <section className={s.wrap}>
      <h1 className={s.title}>No verified replay has been published yet.</h1>
      <p className={s.text}>A replay appears here once a run has been generated, checked and anchored by the pipeline.</p>
    </section>
  );
}

export function LoadError({ reason, onRetry }: { reason: string; onRetry: () => void }) {
  return (
    <section className={s.wrap} role="alert">
      <h1 className={s.title}>The replay could not be loaded</h1>
      <p className={s.text}>{reason} Check your connection, then try again.</p>
      <button type="button" className="btn btn-primary" onClick={onRetry}>Try again</button>
    </section>
  );
}

export function Refused({ outcome }: { outcome: Extract<LoadOutcome, { kind: "refused" }> }) {
  // An id that is not in the bundle list is "not found", not an integrity failure: say which one it is.
  const notFound = outcome.entry === null && outcome.result === null;
  return (
    <section className={`${s.wrap} ${s.refused}`} role="alert" data-testid="verification-failed" data-reason={notFound ? "not-found" : "integrity"}>
      <BrokenLink />
      <p className={s.status} data-kind={notFound ? "not-found" : undefined}>{notFound ? "NOT IN THE BUNDLE LIST" : "INTEGRITY CHECK FAILED"}</p>
      <h1 className={s.title}>{notFound ? "There is no replay with this id" : "This replay is not shown"}</h1>
      <p className={s.lede}>{outcome.reason}</p>
      {outcome.result && <p className={s.text}>{describe(outcome.result)}</p>}
      <p className={s.text}>{notFound
        ? "Only bundles listed in this release, each with its sha256, can be opened."
        : "LinkDown never displays a replay whose audit record does not verify. Nothing from it is rendered."}</p>
      <p className={s.exits}>{notFound ? <><Link to="/replay" className="btn btn-primary">Open the latest verified replay</Link><Link to="/" className="btn">Back to the story</Link></> : <Link to="/" className="btn btn-primary">Back to the story</Link>}</p>
    </section>
  );
}

/** Decorative: a cable cut in two, the site's own image for "nothing here" and "not shown". */
export function BrokenLink() {
  return (
    <svg className={s.brokenLink} viewBox="0 0 320 60" aria-hidden="true">
      <path className={s.cable} d="M4 38 C 60 30, 100 24, 138 28" />
      <path className={s.cable} d="M182 28 C 222 32, 262 40, 316 30" />
      <path className={s.cut} d="M144 16 l -6 24 M 176 16 l -6 24" />
      <circle className={s.spark} cx="160" cy="28" r="9" />
    </svg>
  );
}
