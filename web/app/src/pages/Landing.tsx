import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { GateExplainer, gateFacts, showcaseDecision } from "../components/GateExplainer";
import { NetworkChart, type IntroPhase, type Overlay } from "../components/NetworkChart";
import { RoleView } from "../components/RoleView";
import { useSoundMood } from "../components/SoundControl";
import { Term } from "../components/Term";
import { useVerifiedReplay } from "../hooks/useVerifiedReplay";
import { ACTS, type ActId } from "../lib/acts";
import { AI_RUN_STATUS, flaggedCitations } from "../lib/wording";
import { PRERENDER } from "../lib/env";
import { countWord, effectCounts, formatSimTime, buildReplay, notGivenFor, OUTCOME_NAMES, ROLE_NAMES, SEES_NAMES, TOOL_NAMES, type Replay, type RoleId } from "../lib/replay";
import { sound } from "../lib/sound";
import s from "./Landing.module.css";

const reduceMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const INTRO_SEEN = "linkdown-intro-seen";

export function Landing() {
  const { outcome } = useVerifiedReplay(null);
  const replay = useMemo(() => (outcome?.kind === "verified" ? buildReplay(outcome.bundle) : null), [outcome]);
  const [phase, setPhase] = useState<IntroPhase>(() => {
    try { if (reduceMotion() || sessionStorage.getItem(INTRO_SEEN)) return "final"; } catch { /* storage blocked */ }
    return "draw";
  });

  // The story below the fold mounts after the hero has painted, so the first screen never waits for it.
  const [storyReady, setStoryReady] = useState(false);
  useEffect(() => {
    if (!replay) return;
    const w = window as unknown as { requestIdleCallback?: (f: () => void, o?: { timeout: number }) => number; cancelIdleCallback?: (h: number) => void };
    if (w.requestIdleCallback) { const h = w.requestIdleCallback(() => setStoryReady(true), { timeout: 1200 }); return () => w.cancelIdleCallback?.(h); }
    const t = window.setTimeout(() => setStoryReady(true), 300);
    return () => window.clearTimeout(t);
  }, [replay]);
  const timers = useRef<number[]>([]);
  const ctaRef = useRef<HTMLButtonElement>(null);
  const clearTimers = () => { timers.current.forEach((t) => window.clearTimeout(t)); timers.current = []; };
  useEffect(() => {
    if (!replay || phase === "final") return;
    const advance = (to: IntroPhase) => setPhase((p) => (p === "final" ? p : to));
    timers.current = [
      window.setTimeout(() => advance("flow"), 1500),
      window.setTimeout(() => setPhase((p) => { if (p !== "final") sound().cue("break"); return p === "final" ? p : "break"; }), 3600),
      window.setTimeout(() => { setPhase("final"); try { sessionStorage.setItem(INTRO_SEEN, "1"); } catch { /* ignore */ } }, 5200),
    ];
    return clearTimers;
  }, [replay]); // eslint-disable-line react-hooks/exhaustive-deps

  const e1 = replay?.events[0];
  const down = phase === "break" || phase === "final" ? (e1?.effect.fail_links ?? []) : [];
  const skip = (focusCta = true) => {
    clearTimers();
    setPhase("final");
    try { sessionStorage.setItem(INTRO_SEEN, "1"); } catch { /* ignore */ }
    if (focusCta) ctaRef.current?.focus();   // the Skip button disappears; keep keyboard focus on the page
  };
  // Act I exists only once the verified run has loaded and the story has mounted. A reader can press the button
  // before that (slow network, slow hashing), so the move to Act I waits for both instead of a fixed two frames;
  // otherwise focus stayed on the button and the page never reached Act I.
  const storyRequested = useRef(false);
  const goToAct1 = () => requestAnimationFrame(() => requestAnimationFrame(() => {
    const el = document.getElementById("act-1");
    el?.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
    el?.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
  }));
  const toStory = () => {
    skip(false);
    if (replay && storyReady) { goToAct1(); return; }   // the story is already mounted (the usual case)
    storyRequested.current = true;                       // otherwise move once it mounts (effect below)
    setStoryReady(true);
  };
  useEffect(() => {
    if (!storyRequested.current || !replay || !storyReady) return;
    storyRequested.current = false;
    goToAct1();
  }, [replay, storyReady]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <section className={s.hero} aria-labelledby="hero-title">
        <div className={s.stage} aria-hidden={!replay}>
          {replay && (
            <NetworkChart topology={replay.topology} linksDown={down} phase={phase}
              endpointRegion={replay.initialEndpoint} interactive={false} showCaption={false} />
          )}
        </div>
        <div className={s.copy}>
          <h1 id="hero-title" className={s.headline}>When the cables go dark, who decides?</h1>
          <p className={s.lede}>
            LinkDown is a crisis exercise. Four institutions respond as subsea cables fail, each knowing only part of the
            picture, and a rule-based gate decides which of their proposals may go ahead. Every step is written to a hash-chained record that your browser
            re-checks.
          </p>
          <div className={s.actions}>
            <button type="button" className="btn btn-primary" onClick={toStory} ref={ctaRef} disabled={PRERENDER || undefined}>Experience the story</button>
            <Link to="/replay" className="btn">Explore the evidence</Link>
            <Link to="/walkthrough" className="btn">Judge walkthrough, six steps</Link>
          </div>
          <p className={s.honest}>
            <span className="not-ai">TEST-DOUBLE-NOT-AI</span>
            <span>The published run uses scripted clients to test the machinery. It is not AI output.</span>
          </p>
        </div>
        <div className={s.heroFoot}>
          <p className={s.status} aria-live="polite">
            <span>
              {!replay ? (outcome?.kind === "refused" ? "The replay did not verify, so the network is not shown." : "Loading the verified network")
                : phase === "draw" || phase === "flow" ? "Light moves through the synthetic network."
                : `Event 1, ${formatSimTime(e1?.at_min ?? 0)}: ${e1?.title}. ${down.length ? `${countWord(down.length).replace(/^./, (c) => c.toUpperCase())} ${down.length === 1 ? "link breaks" : "links break"}.` : ""}`}
            </span>
            <span className={s.synthetic}>Exercise controller's schematic of a synthetic network: routes, traffic and capacities are invented for the exercise.</span>
          </p>
          <span className={s.skipSlot}>{replay && phase !== "final" && <button type="button" className="btn btn-quiet" onClick={() => skip()}>Skip intro</button>}</span>
        </div>
      </section>

      {replay && storyReady && <Story replay={replay} />}
    </>
  );
}

/* ---------- The story in five acts: one sticky stage; chapters scroll beside it ---------- */

type Delivery = { to: string; kind: string; text: string; at_min: number };
type Chapter = { act: ActId; step: number | null; key: string };

function Story({ replay }: { replay: Replay }) {
  const [e1, e2, e3] = replay.events;
  const last = replay.steps.length - 1;
  const beforeE3 = (e3?.stepIndex ?? last + 1) - 1;
  // Chart state per chapter, always a real step of the verified run (null = before the first event).
  const chapters: Chapter[] = [
    { act: 1, step: null, key: "network" },
    { act: 1, step: null, key: "institutions" },
    { act: 2, step: e1!.stepIndex, key: "break" },
    { act: 3, step: e1!.stepIndex, key: "roles" },
    { act: 4, step: beforeE3, key: "e2" },
    { act: 4, step: last, key: "e3" },
    { act: 4, step: last, key: "outcomes" },
  ];
  const ROLES_I = chapters.findIndex((c) => c.key === "roles");
  const [active, setActive] = useState(0);
  const [act, setAct] = useState<ActId>(1);
  const [roleId, setRoleId] = useState<RoleId>("operator");
  const refs = useRef<Array<HTMLElement | null>>([]);
  // After a role is chosen, keep the role chapter on the stage while any of it is on screen: on phones the
  // role view can push the chapter out of the trigger band, which would swap the stage under the reader.
  const keepRoles = useRef(false);
  const heardBreak = useRef(false);

  useEffect(() => {
    const io = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        const el = en.target as HTMLElement;
        if (el.dataset.act) setAct(Number(el.dataset.act) as ActId);
        if (el.dataset.i === undefined) continue;
        if (keepRoles.current) {
          const r = refs.current[ROLES_I]?.getBoundingClientRect();
          if (r && r.bottom > 0 && r.top < window.innerHeight) continue;
          keepRoles.current = false;
        }
        setActive(Number(el.dataset.i));
      }
    }, { rootMargin: "-40% 0px -50% 0px" });
    document.querySelectorAll("[data-act]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [ROLES_I]);

  useSoundMood(ACTS[act - 1]!.mood);
  useEffect(() => { if (act === 2 && !heardBreak.current) { heardBreak.current = true; sound().cue("break"); } }, [act]);
  const heardHold = useRef(false);   // the gate: a proposal is held until an authority decides
  useEffect(() => { if (act === 4 && !heardHold.current) { heardHold.current = true; sound().cue("hold"); } }, [act]);

  const stepIdx = chapters[active]?.step ?? null;
  const st = stepIdx === null ? null : replay.stateAt(stepIdx);
  const m = replay.metrics;
  const transfer = replay.decisions.find((d) => d.tool === "transfer_records");
  const transferHuman = transfer?.followUps.find((f) => f.kind === "HUMAN_DECISION");
  const order = replay.decisions.find((d) => d.tool === "issue_priority_order");
  const orderHuman = order?.followUps.find((f) => f.kind === "HUMAN_DECISION");
  const plan = replay.decisions.find((d) => d.tool === "recommend_priority_plan");
  const unenforced = showcaseDecision(replay)?.trail.filter((t) => t.downgraded).length ?? 0;
  const switched = replay.records.find((x) => x.kind === "STATE_CHANGE" && x.payload.change?.changed === "service.endpoint_region");
  const gapCount = replay.records.filter((x) => x.kind === "GAP_OBSERVATION").length;
  const policyStated = replay.records.some((x) => x.kind === "HUMAN_DECISION" && /never decide authority/.test(String(x.payload.reason ?? "")));
  const finalNode = replay.topology.nodes.find((n) => n.id === replay.stateAt(last).endpointRegion);
  const regionName = (id: string | null | undefined) => replay.topology.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "").replace("Cloud region ", "") ?? "unknown";
  const set = (i: number) => (el: HTMLElement | null) => { refs.current[i] = el; };
  const r = replay.roles.find((x) => x.id === roleId)!;
  const notGiven = notGivenFor(r);
  const e1Traffic = replay.stateAt(e1!.stepIndex).traffic;
  const showcase = showcaseDecision(replay);
  // On narrow screens the role view sits inline in its chapter; a scroll box inside the sticky stage
  // would fight the page scroll on touch.
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia?.("(max-width: 900px)");
    if (!mq) return;
    const on = () => setNarrow(mq.matches);
    on(); mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  const isRoles = chapters[active]?.key === "roles" && !narrow;
  // Consequences on the map, each from a record that exists by this chapter's step: the endpoint switch
  // (a STATE_CHANGE) and the case-file copy held at the gate (escalated, never carried out).
  const stepSeq = stepIdx === null ? -1 : replay.steps[stepIdx]!.seq;
  const overlays: Overlay[] = [];
  if (switched && switched.seq <= stepSeq) overlays.push({ kind: "moved", from: String(switched.payload.change?.from), to: String(switched.payload.change?.to), label: "AI endpoint moved" });
  if (transfer && transfer.seq <= stepSeq && !gateFacts(transfer).executed) overlays.push({ kind: "held", from: String(replay.stateAt(0).recordsRegion), to: String(transfer.args.dest_region), label: "case-file copy held at the gate" });
  const actOf = (k: string) => chapters.find((c) => c.key === k)!.act;
  const ActLabel = ({ k }: { k: string }) => actLabel(actOf(k));
  const chapterProps = (k: string) => {
    const i = chapters.findIndex((c) => c.key === k);
    return { ref: set(i), "data-i": i, "data-act": chapters[i]!.act, "data-chapter": k, className: s.chapter, "data-active": active === i || undefined };
  };

  return (
    <>
      <nav className={s.acts} aria-label="Story progress">
        <ol>
          {ACTS.map((a) => (
            <li key={a.id}>
              <a href={`#act-${a.id}`} aria-current={act === a.id ? "step" : undefined} data-done={act > a.id || undefined}>
                <span className={s.actNum}>{a.numeral}</span><span className={s.actName}>{a.name}</span>
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <section className={s.story} aria-label="How the exercise unfolds">
        <div className={s.storyStage}>
          <div className={s.storySticky}>
            {isRoles ? (
              // A role chapter never draws the network: no role is given the map (build_view).
              <div className={s.roleSwap} key={roleId}><RoleView replay={replay} role={r} stepIndex={e1!.stepIndex} compact /></div>
            ) : (
              <NetworkChart topology={replay.topology} linksDown={st?.linksDown ?? []}
                endpointRegion={st?.endpointRegion ?? replay.initialEndpoint} showCaption={false} overlays={overlays} />
            )}
            <p className={s.stageLabel} aria-hidden="true">
              <span className={s.stageAct}>Act {ACTS[act - 1]!.numeral}</span>
              {isRoles ? `Event 1: what the ${ROLE_NAMES[roleId]} is given`
                : `Exercise controller's schematic, ${stepIdx === null ? "before the outage"
                  : st ? `${formatSimTime(st.simMin).replaceAll(" ", "\u00a0")}${st.eventId ? `, during event\u00a0${st.eventId.replace("E", "")}` : ""}` : ""}`}
            </p>
          </div>
        </div>

        <div className={s.chapters}>
          <article {...chapterProps("network")} id="act-1">
            <ActLabel k="network" />
            <h2 className={s.chTitle} tabIndex={-1}>A small, invented network carries a government service.</h2>
            <p>The exercise imagines a region whose international traffic runs through a handful of subsea cables. When several fail at once, a government service that relies on a foreign cloud region can stall. LinkDown models that situation with {countWord(replay.topology.nodes.length)} nodes and {countWord(replay.topology.links.length)} links: a landing station, a national core, a neighbour route and {countWord(replay.topology.nodes.filter((n) => n.kind === "region").length)} cloud regions.</p>
            <p>A residency-renewal service runs its AI checks in {regionName(replay.initialEndpoint)}; its case files are stored in {regionName(replay.stateAt(0).recordsRegion)}.</p>
            <p className={s.aside}>Every figure is synthetic. In the replay, select any link or node to see its capacity and latency.</p>
          </article>

          <article {...chapterProps("institutions")}>
            <ActLabel k="institutions" />
            <h2 className={s.chTitle}>Four institutions share one crisis.</h2>
            <ul className={s.cast}>
              {replay.roles.map((x) => (
                <li key={x.id}><span className={s.castName}>{ROLE_NAMES[x.id]}</span><span className={s.castDesc}>{x.title}. May {x.tools.filter((t) => t !== "send_message").map((t) => TOOL_NAMES[t] ?? t).join(", ")}.</span></li>
              ))}
            </ul>
            <p className={s.aside}>Each role is played here by a scripted client, so the machinery can be tested before any AI model plays it.</p>
          </article>

          <article {...chapterProps("break")} id="act-2">
            <ActLabel k="break" />
            <p className={s.chTime}><code>{formatSimTime(e1!.at_min)}</code> Event 1</p>
            <h2 className={s.chTitle}>{e1!.title}.</h2>
            <p>{e1!.effect.fail_links?.map((id) => replay.topology.links.find((l) => l.id === id)?.label ?? id).join(" and ")} stop carrying traffic. These are the only links the record shows failing.</p>
            {e1Traffic && <p className={s.aside}>Traffic recorded at that moment, in synthetic capacity units (cu):</p>}
            {e1Traffic && (
              <dl className={s.impact} aria-label="Traffic recorded at event 1 (controller's figures)">
                {replay.topology.demand.map((d) => {
                  const t = e1Traffic[d.id];
                  return t ? (
                    <div key={d.id} data-h={t.health}>
                      <dt>{d.label}</dt>
                      <dd><span className={s.meter}><i style={{ width: `${Math.round(t.share * 100)}%` }} /></span><span>{t.delivered} of {t.demand} cu, {t.health.toLowerCase()}</span></dd>
                    </div>
                  ) : null;
                })}
              </dl>
            )}
            <EventInbox items={((e1 as unknown as { deliver?: Delivery[] }).deliver) ?? []} />
            <Link to={`/replay?step=${e1!.stepIndex + 1}`} className={s.chLink}>Replay from event 1</Link>
          </article>

          <article {...chapterProps("roles")} id="act-3">
            <ActLabel k="roles" />
            <h2 className={s.chTitle}>No role sees the whole picture.</h2>
            <p>Choose a role to see what it was given during event 1. No role is given the map itself; the schematic on this page is the exercise controller's view.</p>
            <div className={s.roleSwitch} role="group" aria-label="Choose a role">
              {replay.roles.map((x) => (
                <button key={x.id} type="button" aria-pressed={roleId === x.id} onClick={() => { setRoleId(x.id); setActive(ROLES_I); keepRoles.current = true; }}>{ROLE_NAMES[x.id]}</button>
              ))}
            </div>
            <dl className={s.roleFacts}>
              <dt>Sees</dt><dd>{r.sees.length ? r.sees.map((x) => SEES_NAMES[x] ?? x).join("; ") : "No network or service data. Only messages and sources."}</dd>
              <dt>Not given</dt><dd>{notGiven.length ? notGiven.map((k) => SEES_NAMES[k]).join("; ") : "Nothing else."}</dd>
              <dt>May propose</dt><dd>{r.tools.filter((t) => t !== "send_message").map((t) => TOOL_NAMES[t] ?? t).join("; ")}</dd>
            </dl>
            {narrow && <div className={s.roleInline} data-testid="role-inline"><RoleView replay={replay} role={r} stepIndex={e1!.stepIndex} compact /></div>}
            <Link to={`/replay?step=${e1!.stepIndex + 1}&role=${roleId}`} className={s.chLink}>Open this role's view in the replay</Link>
          </article>

          {[e2, e3].map((e, i) => e && (
            <article key={e.id} {...chapterProps(i === 0 ? "e2" : "e3")} id={i === 0 ? "act-4" : undefined}>
              <ActLabel k={i === 0 ? "e2" : "e3"} />
              <p className={s.chTime}><code>{formatSimTime(e.at_min)}</code> Event {i + 2}</p>
              <h2 className={s.chTitle}>{e.title}.</h2>
              {i === 0 && <p>{switched ? <>The gate permits a switch of the AI endpoint to {regionName(String(switched.payload.change?.to))}, and it is carried out. </> : null}{transfer ? <>A proposal to copy case files to {regionName(String(transfer.args.dest_region))} gets <span className="outcome" data-o={transfer.outcome}>{OUTCOME_NAMES[transfer.outcome]}</span>{transferHuman ? <>, and the simulated controller {transferHuman.payload.approved ? "approves it" : gateFacts(transfer).byPolicy ? "does not approve it: by policy it never decides authority questions" : "rejects it"}</> : transfer.requiresHuman ? <>; no decision on it is recorded</> : null}.</> : null}</p>}
              {i === 1 && <p>Repairs will take weeks. The regulator {plan ? <>proposes a priority plan <span className={s.nowrap}>(<span className="outcome" data-o={plan.outcome}>{OUTCOME_NAMES[plan.outcome]}</span>)</span></> : "considers its options"}{order ? <>, then a binding order <span className={s.nowrap}>(<span className="outcome" data-o={order.outcome}>{OUTCOME_NAMES[order.outcome]}</span>)</span>{orderHuman ? <>, which the simulated controller {orderHuman.payload.approved ? "approves" : gateFacts(order).byPolicy ? "does not approve, by policy" : "rejects"}</> : null}</> : null}.{gapCount ? ` The adviser drafts ${countWord(gapCount)} gap observations for human review.` : ""}</p>}
              <EventInbox items={((e as unknown as { deliver?: Delivery[] }).deliver) ?? []} />
              <Link to={`/replay?step=${e.stepIndex + 1}`} className={s.chLink}>Replay from event {i + 2}</Link>
            </article>
          ))}

          <article {...chapterProps("outcomes")}>
            <ActLabel k="outcomes" />
            <h2 className={s.chTitle}>Every proposal meets the same gate.</h2>
            <p>The <Term tip="A fixed set of written rules, applied the same way every time. It checks facts in the exercise itself, not what a role says about them. Its design adapts the policy step of an ITU standard for AI in networks (Y.3172).">authority gate</Term> returns one of three outcomes. In this run:</p>
            <dl className={s.lanes} aria-label="Outcomes of every proposal in this run">
              {([["PERMITTED", "passed the gate", "Permitted"], ["INSUFFICIENT_AUTHORITY_OR_EVIDENCE", "held for a competent authority", "Needs a competent authority"], ["PROHIBITED", "blocked by a verified rule", "Prohibited"]] as const).map(([o, what, name]) => {
                const n = m.by_outcome?.[o] ?? 0;
                return (
                  <div key={o} data-o={o}>
                    <dt><span className="visually-hidden">{name}: </span><span aria-hidden="true" className={s.laneName}>{what}</span></dt>
                    <dd><span className={s.tokens} aria-hidden="true">{replay.decisions.filter((d) => d.outcome === o).map((d) => <i key={d.seq} />)}</span><span className={s.laneCount}>{n === 0 ? "none" : n}</span></dd>
                  </div>
                );
              })}
            </dl>
            {(m.by_outcome?.PROHIBITED ?? 0) === 0 && unenforced > 0 && (
              <p className={s.keyFact}>Nothing was prohibited, and that is the point. The {countWord(unenforced)} rules that would forbid the cross-border transfer have not been checked against their primary text, so the gate does not enforce them: it sent the transfer to a competent authority instead of deciding it.</p>
            )}
            <p className={s.aside}>Permitted is not the same as carried out: a permitted request for information, recommendation, gap observation or repeated proposal changes nothing in the network. {(() => { const e = effectCounts(replay.records); return `${countWord(e.changed).replace(/^./, (x) => x.toUpperCase())} ${e.changed === 1 ? "action" : "actions"} changed the exercise state (the service's AI endpoint), and ${countWord(e.recordOnly)} ${e.recordOnly === 1 ? "was" : "were"} only recorded. None changed the network itself.`; })()} The case files {replay.recordsMoved ? "were moved" : "never left the UAE"}.</p>
          </article>
        </div>
      </section>

      {showcase && (
        <section className={s.gateAct} aria-labelledby="gate-act-title" data-act={4}>
          <div className={s.gateIntro}>
            <p className={s.actLabel}>Act IV, {ACTS[3]!.name}</p>
            <h2 id="gate-act-title" className={s.sectionTitle}>Possible is not the same as permitted.</h2>
            <p>Under pressure, the service proposes copying its case files abroad as a fallback (the record calls it a scripted unsafe proposal). Proposing it is not deciding it. Step through what the gate did with that proposal, using only the hashed record.</p>
            <Link to={`/replay?step=${(replay.steps.find((x) => x.seq === showcase.seq)?.index ?? 0) + 1}`} className={s.chLink}>See this decision in the replay</Link>
          </div>
          <GateExplainer d={showcase} replay={replay} heading="The Decision Gate" headingLevel={3} />
        </section>
      )}

      <section className={s.proof} id="act-5" aria-labelledby="proof-title" data-act={5}>
        <p className={s.actLabel}>Act V, {ACTS[4]!.name}</p>
        <h2 id="proof-title" className={s.sectionTitle}>Then check it yourself.</h2>
        <div className={s.proofGrid}>
          <div>
            <p>Each of the {replay.records.length} records carries the hash of the one before it. Your browser can recompute every hash and show exactly where a record was changed.</p>
            <p className={s.aside}>A valid chain shows the record has not changed since its head was fixed, provided that head matches a copy kept outside this site. It does not show that a source is relevant, that a decision is legally correct, or that any AI model behaves this way.</p>
            <div className={s.actions}>
              <Link to="/audit" className="btn btn-primary">Verify it in your browser</Link>
              <Link to="/replay" className="btn">Open the replay</Link>
            </div>
          </div>
          <div>
            <div className={s.strand} aria-hidden="true">{replay.records.map((x) => <i key={x.seq} data-k={x.kind} />)}</div>
            <p className={s.strandKey}><span data-k="EVENT">event</span><span data-k="GATE_DECISION">gate decision</span><span data-k="HUMAN_DECISION">simulated human decision</span><span data-k="STATE_CHANGE">state change</span><span>other record</span></p>
          </div>
        </div>

        <div className={s.conclusion}>
          <h3 className={s.conclusionTitle}>What this run establishes, and what it does not</h3>
          <dl className={s.truthList}>
            <dt>Recorded</dt><dd>{m.proposals} proposals: {m.by_outcome?.PERMITTED ?? 0} permitted, {m.by_outcome?.INSUFFICIENT_AUTHORITY_OR_EVIDENCE ?? 0} escalated, {m.by_outcome?.PROHIBITED ?? 0} prohibited. The simulated controller approved {m.human_approved ?? 0} of the {(m.human_approved ?? 0) + (m.human_rejected ?? 0)} proposals put to it{policyStated ? "; by its recorded policy it approves no decision that needs a competent authority" : ""}. {switched ? <>The service moved its AI checks to {regionName(finalNode?.id)}{finalNode?.in_uae ? ", in the UAE" : ""}. </> : null}{m.records_left_uae ? "Case files left the UAE." : `No case file left the UAE (${m.cross_border_executed ?? 0} cross-border transfers carried out).`}</dd>
            <dt>Flagged</dt><dd>{flaggedCitations(replay.records)}</dd>
            <dt>Scripted, not AI</dt><dd>All four roles are played by clients labelled <code>TEST-DOUBLE-NOT-AI</code>. {AI_RUN_STATUS}</dd>
            <dt>Simulated human</dt><dd>Human decisions come from a conservative policy, not from a person. No real authority decided anything.</dd>
            <dt>Synthetic network</dt><dd>Place names evoke the region, but the cables, operators, capacities and traffic are invented.</dd>
          </dl>
          <p className={s.question}>The open question is the one the exercise was built for: when infrastructure, information and authority are all under pressure, which decisions can an AI-assisted institution take on its own, and how would anyone check?</p>
        </div>
      </section>
    </>
  );
}

function actLabel(id: ActId) {
  const a = ACTS[id - 1]!;
  return <p className={s.actLabel}>Act {a.numeral}, {a.name}</p>;
}

function EventInbox({ items }: { items: Delivery[] }) {
  if (!items.length) return null;
  return (
    <ul className={s.inbox} aria-label="Who hears what">
      {items.map((d, k) => (
        <li key={k}><span className={s.inboxWho}>{ROLE_NAMES[d.to as RoleId] ?? d.to}</span><span className={s.inboxText}>{d.text}</span></li>
      ))}
    </ul>
  );
}
