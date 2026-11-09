import { Fragment, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { sound } from "../lib/sound";
import { simulatedControllerNote } from "../lib/wording";
import { LEGAL_STATUS_NAMES, OUTCOME_NAMES, plainDecision, ROLE_NAMES, TOOL_NAMES, type Decision, type Replay } from "../lib/replay";
import s from "./GateExplainer.module.css";

// The Decision Gate: one recorded decision, stepped through the questions a visitor needs answered.
// Every value comes from the hashed GATE_DECISION record and the records that followed it. The diagram's
// motion follows the recorded outcome: an escalated proposal stops at the gate and waits for the
// (simulated) authority; it is never drawn as carried out unless a record says it was.

export const STAGES = ["The proposal", "Its sources", "The limits", "The conclusion", "What happened", "Still uncertain"] as const;

export type GateFacts = ReturnType<typeof gateFacts>;

export function gateFacts(d: Decision) {
  const human = d.followUps.find((f) => f.kind === "HUMAN_DECISION");
  const change = d.followUps.find((f) => f.kind === "STATE_CHANGE" || f.kind === "ACTION_RESULT");
  const executed = !!change && (change.kind === "STATE_CHANGE" || change.payload?.executed === true);
  // An executed action whose record says it only recorded something (a recommendation, a no-op re-route)
  // changed nothing in the network: say "recorded", not "carried out".
  const recordOnly = executed && change!.kind === "ACTION_RESULT" && (change!.payload?.change?.recorded === true || change!.payload?.change?.changed == null);
  const recorded = d.followUps.find((f) => f.kind === "GAP_OBSERVATION" || f.kind === "MESSAGE");
  const dup = d.followUps.find((f) => f.kind === "DUPLICATE_ACTION");
  const stale = d.followUps.find((f) => f.kind === "STALE_APPROVAL");
  // The simulated controller's policy, as its own record states it: it never decides authority questions.
  const byPolicy = !!human && !human.payload.approved && /never decide authority/.test(String(human.payload.reason ?? ""));
  // "Went ahead" only when a record says so: a state change, an executed action, a sent request or a recorded observation.
  const wentAhead = executed || !!recorded;
  const notReason = wentAhead ? null
    : dup ? "it repeats an earlier proposal, so it was not carried out again"
    : stale ? "the approval went stale because the state changed first"
    : human && !human.payload.approved ? (d.approval === "operational" ? "the operational sign-off was refused" : byPolicy ? "the simulated controller did not approve it: by policy it never decides authority questions" : "the competent authority (simulated) rejected it")
    : change ? String(change.payload.change?.note ?? change.payload.change?.error ?? "the action changed nothing")
    : d.outcome === "PERMITTED" ? "no record shows it being carried out" : null;
  const downgraded = d.trail.filter((t) => t.downgraded);
  const simulated = human ? String(human.actor).startsWith("simulated") : false;
  const uncertain: string[] = [];
  for (const t of downgraded) uncertain.push(`Whether rule ${t.rule_id} applies. It would forbid this, but its source (${t.source}${t.clause ? `, clause ${t.clause}` : ""}) has not been checked against the primary text, so the gate does not enforce it.`);
  if (d.legalStatus === "NOT_ASSESSED") uncertain.push("The legal status was not assessed. This outcome rests on an exercise rule, not on a verified law.");
  if (d.outcome === "INSUFFICIENT_AUTHORITY_OR_EVIDENCE" && simulated) uncertain.push("No real competent authority took this decision. The simulated controller is set never to make authority decisions, so it approves none of them: its \"not approved\" is a policy, not a judgement on this proposal.");
  if (d.outcome === "INSUFFICIENT_AUTHORITY_OR_EVIDENCE" && !human) uncertain.push("No decision by the authority is recorded for this proposal.");
  if (d.turn?.unsupported.length) uncertain.push(`In the same turn the role cited ${d.turn.unsupported.join(", ")}, which was not among the passages retrieved for it.`);
  uncertain.push("This record shows what was decided and why. It does not show that the decision is legally correct.");
  return { human, change, executed, recordOnly, recorded, wentAhead, notReason, downgraded, simulated, byPolicy, uncertain };
}

type Pos = "start" | "approach" | "gate" | "authority" | "through" | "held" | "blocked" | "stopped";

function tokenPos(d: Decision, f: GateFacts, stage: number): Pos {
  if (stage <= 0) return "start";
  if (stage <= 2) return "approach";
  if (d.outcome === "PROHIBITED") return "blocked";
  if (stage === 3) return d.requiresHuman ? "authority" : "gate";
  if (f.wentAhead) return "through";
  if (d.outcome === "INSUFFICIENT_AUTHORITY_OR_EVIDENCE") return f.human ? "held" : "authority";
  return f.human ? "held" : "stopped";
}

// Small diagrams (phones, the drawer on a phone) get their own label positions and larger type: scaled down,
// the desktop layout's labels would be unreadably small or collide. Chosen by the diagram's own rendered width.
const NARROW_BELOW = 560;
function useRenderedWidth(ref: React.RefObject<SVGSVGElement | null>) {
  const [width, setWidth] = useState(() => (typeof window !== "undefined" && window.innerWidth < 600 ? window.innerWidth - 40 : 640));
  // A layout effect, so a diagram that can be measured at mount never paints in the wrong layout.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => { const w = el.getBoundingClientRect().width; if (w > 0) setWidth(Math.round(w)); };
    check();
    // Backups for engines whose ResizeObserver misses a change (WebKit: a diagram mounted in a dialog that is
    // still closed, and a window resize): measure again on the next frames and on every window resize.
    let f2 = 0;
    const f1 = requestAnimationFrame(() => { check(); f2 = requestAnimationFrame(check); });
    window.addEventListener("resize", check);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(check) : null;
    ro?.observe(el);
    if (el.parentElement) ro?.observe(el.parentElement);
    return () => { cancelAnimationFrame(f1); cancelAnimationFrame(f2); window.removeEventListener("resize", check); ro?.disconnect(); };
  }, [ref]);
  return width;
}

export function GateDiagram({ d, stage, f, title }: { d: Decision; stage: number; f: GateFacts; title?: string }) {
  const ref = useRef<SVGSVGElement>(null);
  const width = useRenderedWidth(ref);
  const narrow = width < NARROW_BELOW;
  const pos = tokenPos(d, f, stage);
  // The bar opens only for a proposal the rules allow without a sign-off, or one a record shows going ahead.
  const open = d.outcome === "PERMITTED" && (stage === 3 ? !d.requiresHuman : stage >= 4 && f.wentAhead);
  const decided = stage >= 4 && f.human;
  const who = d.approval === "operational" ? "sign-off" : "authority";
  const label = `${title ? `${title}. ` : ""}${OUTCOME_NAMES[d.outcome]}. ${
    pos === "through" ? (f.executed && !f.recordOnly ? "The action was carried out." : f.recordOnly ? "It went ahead as a record only; nothing in the network changed." : "It went ahead and was recorded.")
      : pos === "held" ? `It stopped at the gate; the ${f.simulated ? "simulated " : ""}${who} ${f.human?.payload.approved ? "approved" : f.byPolicy ? "did not approve it, by policy (it never decides authority questions)" : "rejected"}, and nothing was carried out.`
      : pos === "stopped" ? `Permitted by the rules, but nothing was carried out: ${f.notReason}.`
      : pos === "authority" ? (stage >= 4 ? `It stops at the gate. No decision by the ${who} is recorded, and nothing was carried out.` : `It stops at the gate and goes to the ${who}.`)
      : pos === "blocked" ? "It is blocked." : pos === "gate" ? "The rules allow it; it may pass." : "It approaches the gate."}`;
  const verdict = decided ? (f.human!.payload.approved ? "approved" : f.byPolicy ? "not approved" : "rejected") : null;
  // Layout: on phones the authority box holds all three lines and the lower half moves down to make room.
  // The phone layout reserves the verdict row from the start, so the diagram never changes height between stages.
  const L = narrow
    ? { x0: 46, w: 612, h: d.requiresHuman ? 306 : 244, dy: d.requiresHuman ? 62 : 0, box: { x: 112, y: 4, w: 480, h: 144 }, t1: 42, t2: 88, v: 132, up: "M352 212V148", endX: 418, endW: 222, prop: 220, propX: 58, gateY: 230 }
    : { x0: 0, w: 640, h: 230, dy: 0, box: { x: 212, y: 12, w: 280, h: 66 }, t1: 39, t2: 64, v: 0, up: "M352 150V78", endX: 480, endW: 140, prop: 204, propX: 48, gateY: 216 };
  // In the small layout the type is sized from the diagram's rendered width, so labels read at about 11-12px
  // whether the diagram is on a 320px phone or in a 524px drawer (capped at the sizes the boxes are drawn for).
  const typeScale = narrow ? { ["--gate-u" as string]: (L.w / Math.max(width, 1)).toFixed(3) } : undefined;
  const endText = stage >= 4 && pos !== "through" ? "not carried out" : f.recordOnly ? "recorded only" : f.executed || !f.recorded ? "carried out" : "recorded";
  return (
    <svg ref={ref} className={s.diagram} style={typeScale} viewBox={`${L.x0} 0 ${L.w} ${L.h}`} role="img" aria-label={label} data-outcome={d.outcome} data-pos={pos} data-open={open || undefined} data-narrow={narrow || undefined}>
      {d.requiresHuman && <>
        <path className={s.upLane} d={L.up} />
        <g className={s.authority} data-active={pos === "authority" || pos === "held" || undefined}>
          <rect x={L.box.x} y={L.box.y} width={L.box.w} height={L.box.h} rx="2" />
          <text x="352" y={L.t1} textAnchor="middle">{d.approval === "operational" ? "Operational sign-off" : "Competent authority"}</text>
          <text x="352" y={L.t2} textAnchor="middle" className={s.sub}>{f.simulated || !f.human ? "played by a simulated controller" : "human"}</text>
          {verdict && (narrow
            ? <text x="352" y={L.v} textAnchor="middle" className={s.verdict} data-ok={f.human!.payload.approved || undefined}>{verdict}{f.byPolicy && <tspan className={s.sub}> · by policy</tspan>}</text>
            : <>
                <text x="502" y={L.t1} className={s.verdict} data-ok={f.human!.payload.approved || undefined}>{verdict}</text>
                {f.byPolicy && <text x="502" y={L.t2} className={s.sub}>by policy</text>}
              </>)}
        </g>
      </>}
      <g transform={L.dy ? `translate(0 ${L.dy})` : undefined}>
        {/* The lane stops at the outcome box, so it never runs through the outcome's words. */}
        <path className={s.lane} d={`M40 168H${L.endX}`} />
        <path className={s.laneDone} d={`M392 168H${L.endX}`} />
        <g className={s.gate}>
          <rect className={s.post} x="330" y="132" width="8" height="64" />
          <rect className={s.post} x="366" y="132" width="8" height="64" />
          <rect className={s.bar} x="334" y="160" width="36" height="16" />
          <text x="352" y={L.gateY} textAnchor="middle" className={s.sub}>authority gate</text>
        </g>
        <text x={L.propX} y={L.prop} className={s.sub}>proposal</text>
        <g className={s.end} data-active={pos === "through" || undefined} data-none={(stage >= 4 && pos !== "through") || undefined}>
          <rect x={L.endX} y="144" width={L.endW} height="48" rx="2" />
          <text x={L.endX + L.endW / 2} y="174" textAnchor="middle">{endText}</text>
        </g>
        <g className={s.token} data-pos={pos}>
          <circle r="11" />
          {pos === "blocked" && <path className={s.x} d="M-5 -5l10 10M5 -5l-10 10" />}
        </g>
      </g>
    </svg>
  );
}

export function GateExplainer({ d, replay, heading, headingLevel = 3, initialAll = false }: { d: Decision; replay: Replay; heading?: string; headingLevel?: 2 | 3; initialAll?: boolean }) {
  const H4 = headingLevel === 2 ? "h3" : "h4";
  const [stage, setStage] = useState(0);
  const [all, setAll] = useState(initialAll);
  const f = gateFacts(d);
  const uid = useId();
  const pos = tokenPos(d, f, all ? 4 : stage);
  const heard = useRef(false);
  useEffect(() => {
    if (heard.current || !(pos === "authority" || pos === "held" || pos === "blocked")) return;
    heard.current = true;
    sound().cue(pos === "blocked" ? "fail" : "hold");
  }, [pos]);
  const H = headingLevel === 2 ? "h2" : "h3";
  const region = (id: unknown) => replay.topology.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "") ?? String(id);
  const target = "dest_region" in d.args ? ` to ${region(d.args.dest_region)}` : "region" in d.args ? ` to ${region(d.args.region)}` : "";
  const title = `${ROLE_NAMES[d.role]} proposes to ${TOOL_NAMES[d.tool] ?? d.tool}${target}`;
  const facts = Object.entries(d.facts).filter(([k]) => k !== "role" && k !== "tool");
  const simulatedRun = replay.records.some((r) => r.kind === "HUMAN_DECISION" && String(r.actor).startsWith("simulated"));

  const panels = [
    <>
      <p className={s.lead}><strong>{ROLE_NAMES[d.role]}</strong> proposes to <strong>{TOOL_NAMES[d.tool] ?? d.tool}</strong>{target}.</p>
      <p>Stated reason, as recorded: <q className={s.recorded}>{d.why || "none given"}</q></p>
      <p className={s.muted}>Record <code>#{d.seq}</code>. A proposal is only a request: nothing has happened yet.</p>
    </>,
    <>
      <p>{d.cites.length ? `It cites ${d.cites.length === 1 ? "one source" : `${d.cites.length} sources`}:` : "It cites no source."}</p>
      {d.cites.length > 0 && <ul className={s.list}>{d.cites.map((c) => <li key={c}><code>{c}</code></li>)}</ul>}
      <p className={s.muted}>{d.turn ? `${d.turn.retrieved.length} passages were retrieved for this role's turn. ` : ""}Sources are shown as metadata; their text is not published here.</p>
    </>,
    <>
      <p>The gate does not take the proposal's word for anything. It reads these facts from the exercise state:</p>
      {facts.length > 0 && <dl className={s.facts}>{facts.map(([k, v]) => <Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd>{plainValue(v)}</dd></Fragment>)}</dl>}
      <p>Then it applies {d.trail.length === 1 ? "one rule" : `${d.trail.length} rules`}:</p>
      <ol className={s.trail}>
        {d.trail.map((t, i) => (
          <li key={i} data-downgraded={t.downgraded || undefined}>
            <span className={s.rule}><code>{t.rule_id}</code> <RuleEffect t={t} d={d} /></span>
            <span className={s.explain}>{t.verification === "secondary_only" && !t.downgraded ? <>The rule records: <q>{t.explain}</q></> : t.explain}{simulatedControllerNote(t.explain, simulatedRun) && <span className={s.hedge}>{simulatedControllerNote(t.explain, simulatedRun)}</span>}{t.verification === "secondary_only" && !t.downgraded ? <span className={s.hedge}> Its source has not been checked against the primary text.</span> : null}</span>
          </li>
        ))}
      </ol>
    </>,
    <>
      <p className={s.verdictLine}><span className="outcome" data-o={d.outcome}>{OUTCOME_NAMES[d.outcome]}</span></p>
      <p className={s.lead}>{plainDecision(d.outcome, d.legalStatus, d.requiresHuman, d.trail)}</p>
      <p className={s.muted}>{LEGAL_STATUS_NAMES[d.legalStatus] ?? d.legalStatus}</p>
    </>,
    <>
      {f.human ? (
        <p className={s.lead}>The {f.simulated ? "simulated controller (a fixed policy, not a person)" : "human controller"} <strong>{f.human.payload.approved ? "approved" : f.byPolicy ? "did not approve it" : "rejected"}</strong>{f.byPolicy ? ": by policy it never decides authority questions, so this is not a judgement on the proposal" : ""}. <span className={s.recorded}>{f.human.payload.reason}</span></p>
      ) : d.requiresHuman ? <p className={s.lead}>No decision by the controller is recorded for this proposal.</p>
        : <p className={s.lead}>No sign-off was needed.</p>}
      {f.change?.kind === "STATE_CHANGE"
        ? <p>The exercise state changed: <code>{f.change.payload.change?.changed}</code> from <code>{region(f.change.payload.change?.from)}</code> to <code>{region(f.change.payload.change?.to)}</code> (record <code>#{f.change.seq}</code>).</p>
        : f.recordOnly ? <p>Recorded only (record <code>#{f.change!.seq}</code>): {f.change!.payload.change?.note ?? "recorded"}. Nothing in the network changed.</p>
        : f.executed ? <p>Carried out (record <code>#{f.change!.seq}</code>). {f.change!.payload.change?.note ?? ""}</p>
        : f.recorded ? <p>It went ahead: {f.recorded.kind === "GAP_OBSERVATION" ? "the gap observation was recorded for human review" : "the request was sent"} (record <code>#{f.recorded.seq}</code>).</p>
        : <p>Nothing was carried out{f.notReason && !f.human ? `: ${f.notReason}` : ""}.</p>}
      {d.tool === "transfer_records" && !replay.recordsMoved && <p>The case files stayed in {region(replay.stateAt(0).recordsRegion)} for the whole run.</p>}
    </>,
    <ul className={s.list}>{f.uncertain.map((u) => <li key={u}>{u}</li>)}</ul>,
  ];

  return (
    <section className={s.gateBox} aria-labelledby={`${uid}-t`} data-testid="gate-explainer" data-outcome={d.outcome}>
      <div className={s.head}>
        <H id={`${uid}-t`} className={s.title}>{heading ?? title}</H>
        {heading && <p className={s.subtitle}>{title}</p>}
      </div>
      <GateDiagram d={d} stage={all ? 4 : stage} f={f} title={title} />
      {all ? (
        <ol className={s.allStages}>
          {STAGES.map((name, i) => <li key={name}><H4 className={s.stageName}>{name}</H4>{panels[i]}</li>)}
        </ol>
      ) : (
        <>
          <ol className={s.stages} aria-label="Stages of this decision">
            {STAGES.map((name, i) => (
              <li key={name}>
                <button type="button" aria-current={i === stage ? "step" : undefined} data-done={i < stage || undefined} onClick={() => setStage(i)}>
                  <span className={s.n}>{i + 1}</span><span className={s.stageLabel}>{name}</span>
                </button>
              </li>
            ))}
          </ol>
          <div className={s.controls}>
            {/* aria-disabled, not disabled: a focused control must not vanish from the keyboard path. */}
            <button type="button" className="btn" onClick={() => setStage((x) => Math.max(0, x - 1))} aria-disabled={stage === 0}>Back</button>
            <button type="button" className="btn btn-primary" onClick={() => setStage((x) => Math.min(STAGES.length - 1, x + 1))} aria-disabled={stage === STAGES.length - 1}>
              {stage === STAGES.length - 1 ? "All stages seen" : `Next: ${STAGES[stage + 1]}`}
            </button>
          </div>
          <div className={s.panel} aria-live="polite" data-testid="gate-stage">
            <H4 className={s.stageName}>{i18nStage(stage)}</H4>
            {panels[stage]}
          </div>
        </>
      )}
      <button type="button" className={`btn btn-quiet ${s.allToggle}`} onClick={() => setAll((x) => !x)} aria-pressed={all}>Show every stage at once</button>
    </section>
  );
}

/** A rule's effect in the context of this decision: "Permitted" alone would mislead when a sign-off is still required. */
export function RuleEffect({ t, d }: { t: Decision["trail"][number]; d: Decision }) {
  if (t.downgraded) return <span className={s.would}>would prohibit, but its source is not verified</span>;
  if (t.effect === "note") return <span className={s.note}>note only</span>;
  if (t.effect === "PERMITTED" && d.requiresHuman) return <span className="outcome" data-o="PERMITTED">Permitted, but needs {d.approval === "operational" ? "an operational sign-off" : "the controller"}</span>;
  return <span className="outcome" data-o={t.effect}>{OUTCOME_NAMES[t.effect as keyof typeof OUTCOME_NAMES] ?? t.effect}</span>;
}

/** A fact value in plain words: true/false as yes/no, identifiers without underscores. */
export function plainValue(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  return String(v).replaceAll("_", " ");
}

function i18nStage(i: number) { return `${i + 1} of ${STAGES.length}: ${STAGES[i]}`; }

/** The showcase decision: the first escalated cross-border transfer, else the first non-permitted decision, else the first. */
export function showcaseDecision(r: Replay): Decision | undefined {
  return r.decisions.find((d) => d.tool === "transfer_records" && d.outcome !== "PERMITTED")
    ?? r.decisions.find((d) => d.outcome !== "PERMITTED") ?? r.decisions[0];
}
