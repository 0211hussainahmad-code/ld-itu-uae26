import { useEffect, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { GateDiagram, GateExplainer, gateFacts, showcaseDecision } from "../components/GateExplainer";
import { Hash } from "../components/Hash";
import { PRERENDER } from "../lib/env";
import { AI_RUN_STATUS, flaggedCitations, simulatedControllerNote } from "../lib/wording";
import { NetworkChart } from "../components/NetworkChart";
import { useSoundMood } from "../components/SoundControl";
import { Empty, LoadError, Refused } from "../components/StateViews";
import { useVerifiedReplay } from "../hooks/useVerifiedReplay";
import type { Bundle, ManifestEntry } from "../lib/bundle";
import { buildReplay, countWord, formatSimTime, OUTCOME_NAMES, ROLE_NAMES, SEES_NAMES, TOOL_NAMES, VIEW_KEYS, roleViewFor, type Replay, type RoleId } from "../lib/replay";
import { sound, type Cue, type Mood } from "../lib/sound";
import type { VerifyResult } from "../lib/verify";
import s from "./Walkthrough.module.css";

// A direct path for judges: six short steps, each built from the same verified bundle as the story and the replay.
const STEPS: Array<{ name: string; mood: Mood; cue?: Cue }> = [
  { name: "The crisis", mood: "disrupted", cue: "break" },
  { name: "Four roles, four realities", mood: "focus" },
  { name: "A proposal meets the gate", mood: "tension", cue: "hold" },
  { name: "An authority gap", mood: "tension", cue: "hold" },
  { name: "Check the record", mood: "verify", cue: "ok" },
  { name: "What this does not prove", mood: "calm" },
];

function gapStatus(g: { payload: Record<string, any> }) {
  return g.payload.status === "candidate_for_human_review" ? "candidate for human review" : "hypothesis";
}

const SHORT: Record<RoleId, string> = { operator: "Operator", service: "Service", regulator: "Regulator", adviser: "Adviser" };

export function Walkthrough() {
  const { outcome, progress, retry } = useVerifiedReplay(null);
  if (outcome?.kind === "empty") return <Empty />;
  if (outcome?.kind === "error") return <LoadError reason={outcome.reason} onRetry={retry} />;
  if (outcome?.kind === "refused") return <Refused outcome={outcome} />;
  return <Guide data={outcome?.kind === "verified" ? outcome : null} progress={progress} />;
}

interface Verified { bundle: Bundle; entry: ManifestEntry; result: VerifyResult }

// The frame (steps, title, navigation) is static and paints at once; a step's content appears only
// after the browser has verified the run it is built from.
function Guide({ data, progress }: { data: Verified | null; progress: [number, number] | null }) {
  const [params, setParams] = useSearchParams();
  const raw = Math.trunc(Number(params.get("s")));
  const i = Number.isFinite(raw) && raw >= 1 && raw <= STEPS.length ? raw - 1 : 0;
  const badStep = params.has("s") && !(Number.isFinite(raw) && raw >= 1 && raw <= STEPS.length) ? params.get("s") : null;
  const go = (n: number) => setParams((p) => { p.set("s", String(n + 1)); return p; });
  const headRef = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);
  useSoundMood(STEPS[i]!.mood);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const cue = STEPS[i]!.cue;
    if (cue) sound().cue(cue);
    headRef.current?.focus({ preventScroll: true });
    headRef.current?.scrollIntoView({ block: "nearest" });
  }, [i]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.altKey || e.ctrlKey || e.metaKey || t.closest("input, select, textarea, dialog, [role='group'], [data-testid='gate-explainer']")) return;
      if (e.key === "ArrowRight" && i < STEPS.length - 1) { e.preventDefault(); go(i + 1); }
      if (e.key === "ArrowLeft" && i > 0) { e.preventDefault(); go(i - 1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });


  return (
    <div className={s.page}>
      <header className={s.head}>
        <p className={s.kicker}><span className="not-ai">TEST-DOUBLE-NOT-AI</span> Judge walkthrough of the scripted run, rehashed in your browser</p>
        <nav aria-label="Walkthrough steps">
          <ol className={s.steps}>
            {STEPS.map((x, k) => (
              <li key={x.name}>
                <button type="button" onClick={() => go(k)} aria-current={k === i ? "step" : undefined} data-done={k < i || undefined} disabled={PRERENDER || undefined}>
                  <span className={s.n}>{k + 1}</span><span className={s.stepName}>{x.name}</span>
                </button>
              </li>
            ))}
          </ol>
        </nav>
      </header>

      {badStep !== null && <p className={s.notice} role="status" data-testid="bad-step">There is no step {badStep.slice(0, 12) || "with that number"}: the walkthrough has {STEPS.length} steps, so it starts at step 1.</p>}
      <section className={s.body} aria-labelledby="wt-title" data-testid="walkthrough-step" data-step={i + 1} data-pending={!data || undefined}>
        <p className={s.count}>Step {i + 1} of {STEPS.length}</p>
        <h1 id="wt-title" ref={headRef} tabIndex={-1} className={s.title}>{STEPS[i]!.name}</h1>

        {data ? <StepBody {...data} i={i} /> : (
          <p className={s.pending} role="status" data-testid="walkthrough-pending">
            {progress ? `Checking the run in your browser: ${progress[0]} of ${progress[1]} records rehashed.` : "Fetching the published run to check it in your browser…"}
          </p>
        )}
      </section>

      <div className={s.nav}>
        <button type="button" className="btn" onClick={() => go(i - 1)} disabled={i === 0 || PRERENDER}>Back</button>
        {i < STEPS.length - 1
          ? <button type="button" className="btn btn-primary" onClick={() => go(i + 1)} disabled={PRERENDER || undefined}>Next: {STEPS[i + 1]!.name}</button>
          : <Link to="/" className="btn btn-primary">Experience the full story</Link>}
        <span className={s.hint}>Arrow keys move between steps.</span>
      </div>
    </div>
  );
}

function StepBody({ bundle, entry, result, i }: Verified & { i: number }) {
  const replay = useMemo<Replay>(() => buildReplay(bundle), [bundle]);
  const e1 = replay.events[0]!;
  const st1 = replay.stateAt(e1.stepIndex);
  const showcase = showcaseDecision(replay);
  const order = replay.decisions.find((d) => d.tool === "issue_priority_order");
  const orderHuman = order?.followUps.find((f) => f.kind === "HUMAN_DECISION");
  const plan = replay.decisions.find((d) => d.tool === "recommend_priority_plan");
  const orderFacts = order ? gateFacts(order) : null;
  const orders = replay.decisions.filter((d) => d.tool === "issue_priority_order");
  const planRecord = plan?.outcome === "PERMITTED" ? gateFacts(plan).change : undefined;
  const unenforced = showcase?.trail.filter((t) => t.downgraded).length ?? 0;
  const gaps = replay.records.filter((r) => r.kind === "GAP_OBSERVATION");
  const stepOf = (seq: number) => (replay.steps.find((x) => x.seq === seq)?.index ?? 0) + 1;
  const m = replay.metrics;

  return (
    <>
      {i === 0 && (
        <div className={s.split}>
          <div className={s.text}>
            <p className={s.lead}>At {formatSimTime(e1.at_min)}, {e1.effect.fail_links?.map((id) => replay.topology.links.find((l) => l.id === id)?.label ?? id).join(" and ")} fail. International capacity drops, and a government service whose AI checks run abroad starts to fall behind.</p>
            <p>Traffic the exercise recorded at that moment (synthetic capacity units):</p>
            <ul className={s.traffic}>
              {replay.topology.demand.map((d) => {
                const t = st1.traffic?.[d.id];
                return t ? <li key={d.id} data-h={t.health}><span>{d.label}</span><span>{t.delivered} of {t.demand} cu, {t.health.toLowerCase()}</span></li> : null;
              })}
            </ul>
            <p className={s.muted}>The network, the service and every figure are invented for the exercise.</p>
          </div>
          <figure className={s.figure}>
            <NetworkChart topology={replay.topology} linksDown={st1.linksDown} endpointRegion={st1.endpointRegion} interactive={false} showCaption={false} labelledBy="wt-chart" />
            <figcaption id="wt-chart" className={s.caption}>Exercise controller's schematic at event 1. No role is given this map.</figcaption>
          </figure>
        </div>
      )}

      {i === 1 && (
        <>
          <p className={s.lead}>Each role decides from what it is given, and none is given the whole picture. This follows the exercise code exactly (<code>build_view</code>).</p>
          <div className={s.matrixWrap}>
            <table className={s.matrix}>
              <caption className="visually-hidden">What each role is given on each of its turns</caption>
              <thead>
                <tr><th scope="col">Information</th>{replay.roles.map((r) => <th key={r.id} scope="col"><span className={s.longRole}>{ROLE_NAMES[r.id]}</span><span className={s.shortRole} aria-hidden="true">{SHORT[r.id]}</span></th>)}</tr>
              </thead>
              <tbody>
                {VIEW_KEYS.map((k) => (
                  <tr key={k}>
                    <th scope="row">{SEES_NAMES[k]}</th>
                    {replay.roles.map((r) => {
                      const v = roleViewFor(r);
                      const got = v.has(k) ? "given" : v.has("traffic") && (k === "service_traffic" || k === "demand_classes") ? "included" : "no";
                      return <td key={r.id} data-v={got}>{got === "given" ? <><span aria-hidden="true">●</span><span className="visually-hidden">given</span></>
                        : got === "included" ? <><span aria-hidden="true">○</span><span className="visually-hidden">included in every-class traffic</span></>
                        : <><span aria-hidden="true">–</span><span className="visually-hidden">not given</span></>}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className={s.matrixKey}><span>● given</span><span>○ included in every-class traffic</span><span>– not given</span></p>
          </div>
          <div className={s.roles}>
            {replay.roles.map((r) => (
              <article key={r.id} className={s.role}>
                <h2 className={s.roleName}>{ROLE_NAMES[r.id]}</h2>
                <p className={s.tools}>May propose: {r.tools.filter((t) => t !== "send_message").map((t) => TOOL_NAMES[t] ?? t).join("; ")}.</p>
                <Link to={`/replay?step=${e1.stepIndex + 1}&role=${r.id}`}>See its view at event 1</Link>
              </article>
            ))}
          </div>
        </>
      )}

      {i === 2 && showcase && (
        <>
          <p className={s.lead}>Under pressure, the service proposes copying its case files to another region as a fallback. Proposing it is a technical act; deciding it is institutional, and the service may not decide that alone. This is what the gate did, record by record.</p>
          <GateExplainer d={showcase} replay={replay} headingLevel={2} />
          <p><Link to={`/replay?step=${stepOf(showcase.seq)}`}>Open this decision in the replay</Link></p>
        </>
      )}

      {i === 3 && (
        <div className={s.split}>
        <div className={s.text}>
          {order && (
            <>
              <p className={s.lead}>During event 3 the regulator proposes a binding national priority order. A fixed exercise rule ({order.trail.map((t) => t.rule_id).join(", ")}) covers binding orders: no verified legal power for them was recorded when the rules were written, so the gate escalates the order instead of deciding it.</p>
              <blockquote className={s.quote}><span className="outcome" data-o={order.outcome}>{OUTCOME_NAMES[order.outcome]}</span><p>{order.summary.replace(/^[A-Z_]+:\s*/, "")}<span className={s.muted}>{simulatedControllerNote(order.summary, !!orderFacts?.simulated) ?? ""}</span></p></blockquote>
              <p>{orderHuman
                ? <>So the order stops at the exercise controller. In this run the controller is simulated: a fixed policy, not a person. {orderHuman.payload.approved ? "It approves the order." : orderFacts?.byPolicy ? "It does not approve the order: by policy it never decides authority questions, so this is not a judgement on the order." : "It rejects the order."}{planRecord ? <> The regulator's non-binding recommendation, proposed just before the order, stays recorded (<Link to={`/audit?record=${planRecord.seq}`}>record #{planRecord.seq}</Link>); it changes nothing in the network.</> : null}</>
                : <>No decision by the controller on this order is recorded.</>}</p>
              <p><Link to={`/replay?step=${stepOf(order.seq)}`}>See the order in the replay</Link></p>
            </>
          )}
          <h2 className={s.h2}>Gap observations, drafted for human review</h2>
          <p>The adviser records each open question as a hypothesis. None is a finding until a person reviews it.</p>
          {gaps[0] && (
              <ul className={s.gaps}>
                <li><code>{gaps[0].payload.gap_id}</code><span className={s.recorded}>{gaps[0].payload.wording}</span><span className={s.muted}>{gapStatus(gaps[0])}</span></li>
              </ul>
            )}
            {gaps.length > 1 && <p>{countWord(gaps.length - 1).replace(/^./, (x) => x.toUpperCase())} more scripted drafts in the same form: {gaps.slice(1).map((g) => `${g.payload.gap_id} (${gapStatus(g)})`).join(", ")}.</p>}
            <p className={s.muted}>The wording is the scripted client's, recorded as written. A draft becomes a candidate for human review only when it cites a primary passage written for that gap; the others stay hypotheses.</p>
            <p>These drafts only test the mechanism. The exercise's five gap hypotheses (G1 to G5), each with the global policy examples behind it, are set out in section 6 of the technical report and in the repository's <code>config/gaps.yaml</code>.</p>
        </div>
        {order && (
          <figure className={s.figure}>
            <GateDiagram d={order} stage={4} f={gateFacts(order)} title="Regulator proposes a binding priority order" />
            <figcaption className={s.caption}>{orders.length > 1 ? <>The binding order stops at the gate each time it is proposed (records {orders.map((o) => `#${o.seq}`).join(" and ")}).</> : <>The binding order (record #{order.seq}) stops at the gate.</>} It is never carried out.</figcaption>
          </figure>
        )}
        </div>
      )}

      {i === 4 && (
        <div className={s.split}>
        <div className={s.text}>
          <p className={s.lead}>Your browser has already rehashed all {result.total} records of this run: <strong>{result.checked} of {result.total} agree with the chain.</strong> That shows no record was changed after the head was fixed, provided the head matches a copy kept outside this site.</p>
          <p>Each record carries the hash of the one before. Change a single character and the chain breaks at that record. Compare the head below with a copy kept outside this site: the head printed in the submission repository's README and in the submission e-mail to the organisers.</p>
          <p><Hash value={entry.audit_head} /></p>
          <div className={s.actions}>
            <Link to="/audit" className="btn btn-primary">Try the tamper test</Link>
            <Link to="/replay" className="btn">Browse the full replay</Link>
          </div>
        </div>
        <div>
          <div className={`${s.strand} ${s.strandBig}`} aria-hidden="true">{replay.records.map((x) => <i key={x.seq} data-k={x.kind} />)}</div>
          <p className={s.strandKey}><span data-k="EVENT">event</span><span data-k="GATE_DECISION">gate decision</span><span data-k="HUMAN_DECISION">simulated human decision</span><span data-k="STATE_CHANGE">state change</span><span>other record</span></p>
        </div>
        </div>
      )}

      {i === 5 && (
        <div className={s.twoCol}>
        <div className={s.text}>
          <p className={s.lead}>The record is tamper-evident. That is all it claims to be.</p>
          <ul className={s.limits}>
            <li>The four roles are played by scripted clients (<code>TEST-DOUBLE-NOT-AI</code>). This run shows the machinery, not AI reasoning.</li>
            <li>Human decisions come from a fixed, conservative policy. No real authority decided anything.</li>
            {bundle.provenance.inspect.limitations.map((l) => <li key={l}>{l}</li>)}
            <li>{flaggedCitations(replay.records)}</li>
            {unenforced > 0 && <li>{countWord(unenforced).replace(/^./, (c) => c.toUpperCase())} {unenforced === 1 ? "rule" : "rules"} that would forbid the transfer {unenforced === 1 ? "is" : "are"} not enforced, because {unenforced === 1 ? "its" : "their"} source has not been checked against the primary text.</li>}
          </ul>
        </div>
        <div className={s.text}>
          <h2 className={`${s.h2} ${s.h2Top}`}>What comes next</h2>
          <ul className={s.limits}>
            <li>{AI_RUN_STATUS}</li>
            <li>Primary-text checks of the sources behind the unenforced rules.</li>
            <li>Human review of every citation's relevance and every gap observation.</li>
          </ul>
        </div>
        </div>
      )}
    </>
  );
}
