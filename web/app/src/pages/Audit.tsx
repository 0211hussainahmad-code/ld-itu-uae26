import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useSoundMood } from "../components/SoundControl";
import { showcaseDecision } from "../components/GateExplainer";
import { sound } from "../lib/sound";
import { z } from "zod";
import { Empty, LoadError, Refused } from "../components/StateViews";
import { Hash } from "../components/Hash";
import { useVerifiedReplay } from "../hooks/useVerifiedReplay";
import type { AuditRecord, Bundle, ManifestEntry } from "../lib/bundle";
import { buildReplay, formatSimTime, KIND_NAMES, type Replay } from "../lib/replay";
import { describe, verifyChain, type VerifyResult } from "../lib/verify";
import s from "./Audit.module.css";

const AnchorsSchema = z.object({
  schema: z.literal("linkdown-bundle-anchors/1"),
  anchors: z.record(z.string(), z.object({ commit: z.string().regex(/^[0-9a-f]{40}$/), audit_head: z.string().regex(/^[0-9a-f]{64}$/),
    source_commit: z.string().regex(/^[0-9a-f]{40}$/), run_url: z.string() })),
});
type Anchor = z.infer<typeof AnchorsSchema>["anchors"][string];
type Cell = "pending" | "ok" | "bad" | "unchecked";

// Records that are hashed in the chain but are not replay steps: per-turn bookkeeping.
const BOOKKEEPING: Record<string, string> = {
  AGENT_TURN: "Call record for this turn: which sources were retrieved and a fingerprint of the prompt (the prompt itself is not published)",
  DEMO_TURN: "Turn-file check: the file's fingerprint, and whether it parsed and was usable",
};

// The page's header and story frame paint at once; the chain fills as the browser really rehashes it.
export function Audit() {
  const { outcome, progress, retry } = useVerifiedReplay(null);
  // The loader rehashes every record before anything is shown. If this visit watched it happen, its
  // result is the page's verification; otherwise (already loaded on another page) the page reruns it.
  const watched = useRef(false);
  if (progress && progress[0] === progress[1] && progress[1] > 0) watched.current = true;
  if (outcome?.kind === "empty") return <Empty />;
  if (outcome?.kind === "error") return <LoadError reason={outcome.reason} onRetry={retry} />;
  if (outcome?.kind === "refused") return <Refused outcome={outcome} />;
  const verified = outcome?.kind === "verified" ? outcome : null;
  return (
    <div className={s.page}>
      <Header />
      {verified
        ? <AuditView bundle={verified.bundle} entry={verified.entry} loaderResult={watched.current ? verified.result : null} />
        : <LoadingChain progress={progress} />}
    </div>
  );
}

function Header() {
  return (
    <header className={s.head}>
      <p className={s.act}><span>Act V</span> The proof</p>
      <p className={s.kicker}>
        <span className="not-ai">TEST-DOUBLE-NOT-AI</span> Audit record of the scripted replay
      </p>
      <h1 className={s.title}>Every record, sealed to the one before.</h1>
      <p className={s.lede}>
        Each record carries the hash of the previous one. Your browser recomputes every hash from the exact published bytes. Change a
        single character anywhere and the chain breaks at that record.
      </p>
    </header>
  );
}

function LoadingChain({ progress }: { progress: [number, number] | null }) {
  const [done, total] = progress ?? [0, 0];
  return (
    <section className={s.verify} aria-labelledby="verify-title" aria-busy="true">
      <div className={s.verifyHead}><h2 id="verify-title" className={s.h2}>Verification in your browser</h2></div>
      {total > 0 && <Chain cells={Array.from({ length: total }, (_, i) => (i < done ? "ok" : "pending"))} kinds={null} focusSeq={null} label={`Rehashing: ${done} of ${total} records`} />}
      <div className={s.result} aria-live="polite" data-testid="audit-result">
        <p className={s.resultTitle}>{total ? `Rehashing ${total} records…` : "Fetching the published bytes…"}</p>
      </div>
    </section>
  );
}

const Chain = memo(function Chain({ cells, kinds, focusSeq, label }: { cells: Cell[]; kinds: string[] | null; focusSeq: number | null; label: string }) {
  return (
    <>
      <div className={s.chain} role="img" aria-label={label} data-testid="audit-chain">
        {cells.map((c, i) => <i key={i} data-c={c} data-k={kinds?.[i]} data-focus={focusSeq === i + 1 || undefined} />)}
      </div>
      <p className={s.key} aria-hidden="true">
        <span data-k="ok">rehashed</span><span data-k="bad">changed</span><span data-k="unchecked">not checked</span>
        <span data-k="mark">tick marks: event, gate decision, controller decision</span>
      </p>
    </>
  );
});

function AuditView({ bundle, entry, loaderResult }: { bundle: Bundle; entry: ManifestEntry; loaderResult: VerifyResult | null }) {
  const total = bundle.audit.length;
  const kinds = useMemo(() => bundle.audit.map((r) => r.kind), [bundle]);
  const replay = useMemo(() => buildReplay(bundle), [bundle]);
  const [cells, setCells] = useState<Cell[]>(() => Array(total).fill(loaderResult?.status === "full" ? "ok" : "pending"));
  const [result, setResult] = useState<VerifyResult | null>(loaderResult?.status === "full" ? loaderResult : null);
  const [running, setRunning] = useState(false);
  // The default tamper target is the decision the Decision Gate features (the escalated case-file copy), so the
  // break lands on a record a visitor has just seen, not on bookkeeping.
  const [tamperSeq, setTamperSeq] = useState(() => showcaseDecision(replay)?.seq ?? 40);
  const [tampered, setTampered] = useState(false);
  const [anchor, setAnchor] = useState<Anchor | null | undefined>(undefined);
  const runId = useRef(0);
  const [params] = useSearchParams();
  const focusRaw = Math.trunc(Number(params.get("record")));
  const focusSeq = Number.isFinite(focusRaw) && focusRaw >= 1 && focusRaw <= total ? focusRaw : null;
  const badRecord = params.has("record") && focusSeq === null ? params.get("record") : null;
  // The resolved "verify" chord only while the chain agrees; a broken chain sounds disrupted until it is restored.
  useSoundMood((tampered && running) || (result && result.status !== "full") ? "disrupted" : "verify");

  const run = useCallback(async (records: AuditRecord[], isTamper: boolean) => {
    const id = ++runId.current;
    setRunning(true);
    setResult(null);
    setTampered(isTamper);
    setCells(Array(total).fill("pending"));
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let shown = 0, pending = 0, frame = 0;
    const flush = () => {
      frame = 0;
      if (id !== runId.current || pending <= shown) return;
      const from = shown, upto = pending;     // capture now: the updater runs later
      setCells((c) => { const n = [...c]; for (let k = from; k < upto; k++) n[k] = "ok"; return n; });
      shown = upto;
    };
    // A cell turns "ok" only after its record has been rehashed and checked (verifyChain reports after each).
    const res = await verifyChain(records, entry.audit_head, (done) => {
      if (id !== runId.current) return;
      pending = done;
      if (!frame) frame = requestAnimationFrame(flush);
    });
    if (frame) cancelAnimationFrame(frame);
    flush();
    if (!reduce) await new Promise((r) => setTimeout(r, 150));
    if (id !== runId.current) return;
    if (res.status !== "full") {
      setCells((c) => c.map((v, i) => (res.failedAt && i + 1 === res.failedAt ? "bad" : res.failedAt && i + 1 > res.failedAt ? "unchecked" : v === "pending" ? "unchecked" : v)));
    }
    setResult(res);
    setRunning(false);
    sound().cue(res.status === "full" ? "ok" : "fail");
    if (isTamper) requestAnimationFrame(() => document.querySelector('[data-testid="audit-result"]')?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" }));
  }, [entry.audit_head, total]);

  // Rerun only when this visit did not watch the loader's own rehash (for example, arriving from the replay).
  useEffect(() => { if (loaderResult?.status !== "full") run(bundle.audit, false); else sound().cue("ok"); }, [bundle, run, loaderResult]);
  useEffect(() => {
    fetch("/bundles/anchors.json").then((r) => (r.ok ? r.json() : null)).then((j) => {
      const p = AnchorsSchema.safeParse(j);
      setAnchor(p.success ? p.data.anchors[entry.bundle_id] ?? null : null);
    }).catch(() => setAnchor(null));
  }, [entry.bundle_id]);

  const tamper = () => {
    const recs = bundle.audit.map((r) => ({ ...r }));
    const target = recs[tamperSeq - 1]!;
    // Change one character inside the hashed body, exactly as a careless or malicious edit would.
    const edited = target.body!.replace(/"sim_min":(\d+)/, (_, n) => `"sim_min":${Number(n) + 1}`);
    target.body = edited !== target.body ? edited : target.body!.replace('"seq":', '"seq": ');
    run(recs, true);
  };

  // The run and anchor commit live in the team's private repository: shown as text, never as links, because
  // a link would only lead judges to a 404 (and to the private repository's name).
  const ciRunId = entry.generator_run_url.match(/\/actions\/runs\/(\d+)/)?.[1];
  const ok = result?.status === "full";
  const stepCount = replay.steps.length;
  const bookkeeping = useMemo(() => Object.keys(BOOKKEEPING).map((k) => [k, kinds.filter((x) => x === k).length] as const).filter(([, n]) => n > 0), [kinds]);

  return (
    <>
      {badRecord !== null && (
        <p className={s.notice} role="status" data-testid="bad-record">There is no record {badRecord.slice(0, 12) || "with that number"} in this run: it has {total} records, numbered 1 to {total}. All of them are listed below.</p>
      )}
      <section className={s.verify} aria-labelledby="verify-title">
        <div className={s.verifyHead}>
          <h2 id="verify-title" className={s.h2}>{tampered ? "Tamper test" : "Verification in your browser"}</h2>
          <div className={s.actions}>
            <label className={s.tamperPick}>
              <span>Record to change</span>
              <select value={tamperSeq} onChange={(e) => setTamperSeq(Number(e.target.value))} disabled={running}>
                {bundle.audit.map((r) => <option key={r.seq} value={r.seq}>#{r.seq} {KIND_NAMES[r.kind] ?? r.kind}</option>)}
              </select>
            </label>
            <button type="button" className="btn btn-primary" onClick={() => { if (!running) tamper(); }} aria-disabled={running}>Change it and verify</button>
            {tampered && !running
              ? <button type="button" className="btn btn-quiet" onClick={() => { if (!running) run(bundle.audit, false); }}>Restore the original</button>
              : <button type="button" className="btn btn-quiet" onClick={() => { if (!running) run(bundle.audit, false); }} aria-disabled={running}>Verify again</button>}
          </div>
        </div>

        <Chain cells={cells} kinds={kinds} focusSeq={focusSeq} label={result ? describe(result) : "Verifying"} />

        <div className={s.result} data-ok={result ? (ok ? "yes" : "no") : undefined} aria-live="polite" data-testid="audit-result">
          {!result ? <p className={s.resultTitle}>Rehashing {total} records…</p> : ok ? (
            <>
              <p className={s.big}><span>{result.checked}</span> / {result.total} records rehashed</p>
              <p className={s.resultTitle}>{describe(result)}</p>
              <p>The computed head matches this release's bundle list. That check alone is not an external anchor; compare the head below with the records outside this site.</p>
            </>
          ) : (
            <>
              <p className={s.big} data-bad=""><span>#{result.failedAt}</span> chain broken</p>
              <p className={s.resultTitle}>{tampered ? `The edit was caught at record #${result.failedAt}.` : describe(result)}</p>
              <p>{tampered ? "One changed character makes that record's hash disagree with the chain. Records after it can no longer be trusted, so they are shown as unchecked. The published bundle itself is unchanged." : result.problems.join(" ")}</p>
            </>
          )}
        </div>
      </section>

      <section className={s.mapping} aria-labelledby="mapping-title" data-testid="record-mapping">
        <h2 id="mapping-title" className={s.h2}>How the record relates to the replay</h2>
        <p>
          The replay walks through <strong>{stepCount}</strong> of these {total} records, one step each. The other <strong>{total - stepCount}</strong> are
          bookkeeping kept for every scripted turn, hashed in the same chain and verified with the rest:
        </p>
        <ul>
          {bookkeeping.map(([k, n]) => <li key={k}><strong>{n}</strong> <code>{k}</code>: {BOOKKEEPING[k]!.charAt(0).toLowerCase() + BOOKKEEPING[k]!.slice(1)}.</li>)}
        </ul>
      </section>

      <section className={s.anchors} aria-labelledby="anchors-title">
        <h2 id="anchors-title" className={s.h2}>Compare the head with records outside this site</h2>
        <p className={s.notice} data-testid="anchor-access">The anchor commit below is in the team's private development repository. The public submission repository is a clean copy without that history, so judges cannot open the anchor commit. Compare the head instead with the copies kept outside this site: the submission repository's README and the submission e-mail to the organisers.</p>
        <dl className={s.kv}>
          <dt>Bundle</dt><dd><code>{entry.bundle_id}</code></dd>
          <dt>Audit head</dt><dd><Hash value={entry.audit_head} /></dd>
          <dt>Anchor commit</dt>
          <dd>{anchor === undefined ? "Looking up" : anchor ? (
            <>
              <Hash value={anchor.commit} /> (in the team's private development repository)
              <span className={s.note} data-testid="anchor-note">
                {anchor.audit_head === entry.audit_head
                  ? "This site's anchor list, written from git when the site was built, says this commit's message records the same head that your browser computed. That list is served by this site, so it is a pointer, not proof: the independent check is to compare the head above with a copy kept outside this site."
                  : "This site's anchor list gives a different head for this commit: do not trust this replay."}
              </span>
            </>
          ) : "Not available in this build."}</dd>
          <dt>Generated by</dt><dd>{ciRunId ? <>GitHub Actions run <code>{ciRunId}</code> in the team's private development repository</> : <code>{entry.generator_run_url}</code>}, from source commit <Hash value={entry.source_commit} /></dd>
          <dt>Bundle file</dt><dd><Hash prefix="sha256" value={entry.sha256} /></dd>
        </dl>
        <p className={s.note}>The development repository stays private, so the run and commit above cannot be opened outside the team. The head is also printed in the submission repository's README and in the submission e-mail, where it can be compared without this site.</p>
      </section>

      <section className={s.limits} aria-labelledby="limits-title">
        <h2 id="limits-title" className={s.h2}>What this check does and does not show</h2>
        <ul>
          <li>It shows the published records have not changed since the head was fixed, provided the head matches one kept outside this site. Someone able to rewrite the whole chain would also produce a new, self-consistent head: only the outside copy of the head catches that.</li>
          {bundle.provenance.inspect.limitations.map((l) => <li key={l}>{l}</li>)}
          <li>It does not show that a cited source is relevant, or that any decision is legally correct.</li>
        </ul>
      </section>

      <RecordBrowser bundle={bundle} replay={replay} focusSeq={focusSeq} settled={result !== null && anchor !== undefined} />
      <p className={s.back}><Link to="/replay">Back to the replay</Link> <Link to="/">Back to the story</Link></p>
    </>
  );
}

interface Row { r: AuditRecord; body: Record<string, any>; title: string; step: number | null }

const RecordBrowser = memo(function RecordBrowser({ bundle, replay, focusSeq, settled }: { bundle: Bundle; replay: Replay; focusSeq: number | null; settled: boolean }) {
  const rows = useMemo<Row[]>(() => {
    const bySeq = new Map(replay.steps.map((st) => [st.seq, st]));
    return bundle.audit.map((r) => {
      const st = bySeq.get(r.seq);
      const body = r.body ? JSON.parse(r.body) : {};
      return { r, body, step: st ? st.index + 1 : null, title: st ? st.title : BOOKKEEPING[r.kind]?.split(":")[0] ?? KIND_NAMES[r.kind] ?? r.kind };
    });
  }, [bundle, replay]);
  const kinds = useMemo(() => [...new Set(bundle.audit.map((r) => r.kind))].sort(), [bundle]);
  const [kind, setKind] = useState("all");
  const [all, setAll] = useState(focusSeq !== null && focusSeq > 24);
  useEffect(() => {
    if (focusSeq === null) return;
    setKind("all");
    if (focusSeq > 24) setAll(true);
  }, [focusSeq]);
  // Scroll to a linked record only once the content above it has its final height (the verification result
  // and the anchor lookup). Scrolling earlier left the record to slide away when they filled in: about 130 px
  // on a phone, which browsers without scroll anchoring (Safari) do not compensate. Fallback after 3 s.
  const scrolledFor = useRef<number | null>(null);
  const [waited, setWaited] = useState(false);
  useEffect(() => {
    if (focusSeq === null || settled) return;
    const t = setTimeout(() => setWaited(true), 3000);
    return () => clearTimeout(t);
  }, [focusSeq, settled]);
  useEffect(() => {
    if (focusSeq === null || !(settled || waited) || scrolledFor.current === focusSeq) return;
    scrolledFor.current = focusSeq;
    requestAnimationFrame(() => {
      const el = document.getElementById(`record-${focusSeq}`);
      el?.scrollIntoView({ block: "center" });
      el?.querySelector("summary")?.focus({ preventScroll: true });   // keyboard and screen-reader users land on the record
    });
  }, [focusSeq, settled, waited]);
  const matching = rows.filter((x) => kind === "all" || (kind === "replay" ? x.step !== null : kind === "bookkeeping" ? x.step === null : x.r.kind === kind));
  const shown = all ? matching : matching.slice(0, 24);
  const inReplay = rows.filter((x) => x.step !== null).length;
  return (
    <section className={s.records} aria-labelledby="records-title">
      <div className={s.recordsHead}>
        <h2 id="records-title" className={s.h2}>Every record</h2>
        <label className={s.filter}>
          <span>Show</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All records ({rows.length})</option>
            <option value="replay">Steps in the replay ({inReplay})</option>
            <option value="bookkeeping">Bookkeeping only ({rows.length - inReplay})</option>
            {kinds.map((k) => <option key={k} value={k}>{k} ({bundle.audit.filter((r) => r.kind === k).length})</option>)}
          </select>
        </label>
      </div>
      <ol className={s.list}>
        {shown.map((x) => <RecordRow key={x.r.seq} row={x} replay={replay} focused={focusSeq === x.r.seq} />)}
      </ol>
      {matching.length > shown.length && (
        <button type="button" className={`btn ${s.more}`} onClick={() => setAll(true)}>Show all {matching.length} records</button>
      )}
    </section>
  );
});

function RecordRow({ row, replay, focused }: { row: Row; replay: Replay; focused: boolean }) {
  const { r, body, title, step } = row;
  const [open, setOpen] = useState(focused);
  useEffect(() => { if (focused) setOpen(true); }, [focused]);   // a link to this record opens it
  // Relationships between records: a gate decision and the records that followed it share an action id.
  const related = (): Array<{ seq: number; label: string }> => {
    const d = replay.decisions.find((x) => x.seq === r.seq);
    if (d) return d.followUps.map((f) => ({ seq: f.seq, label: KIND_NAMES[f.kind] ?? f.kind }));
    const aid = body?.payload?.action_id;
    const parent = aid ? replay.decisions.find((x) => x.actionId === aid && x.seq < r.seq) : replay.decisions.find((x) => x.followUps.some((f) => f.seq === r.seq));
    return parent ? [{ seq: parent.seq, label: "Gate decision it follows" }] : [];
  };
  return (
    <li id={`record-${r.seq}`} data-focus={focused || undefined} data-bookkeeping={step === null || undefined}>
      <details open={open || undefined} onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>
          <code className={s.seq}>#{r.seq}</code>
          <span className={s.what}>
            <span className={s.recTitle}>{title}</span>
            <span className={s.rk} data-k={r.kind}>{r.kind} · {r.actor}</span>
          </span>
          <code className={s.time}>{formatSimTime(body.sim_min ?? 0)}</code>
          <code className={s.h}>{r.hash.slice(0, 12)}</code>
        </summary>
        {open && (
          <>
            <p className={s.relations}>
              {step !== null ? <Link to={`/replay?step=${step}`}>Step {step} in the replay</Link> : <span className={s.noStep}>Bookkeeping record: not a step in the replay</span>}
              {related().map((x) => <Link key={x.seq} to={`/audit?record=${x.seq}`}>{x.label} #{x.seq}</Link>)}
            </p>
            <pre className={s.pre}>{JSON.stringify(body, null, 2)}</pre>
            <p className={s.note}>prev <Hash value={r.prev} /><br />hash <Hash value={r.hash} /></p>
          </>
        )}
      </details>
    </li>
  );
}
