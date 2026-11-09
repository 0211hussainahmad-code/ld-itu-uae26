import { Fragment, useEffect, useRef } from "react";
import { Link } from "react-router";
import type { Bundle } from "../lib/bundle";
import { formatSimTime, KIND_NAMES, LEGAL_STATUS_NAMES, OUTCOME_NAMES, plainDecision, ROLE_NAMES, TOOL_NAMES, safeHttpsUrl, type Decision } from "../lib/replay";
import { GateDiagram, gateFacts, plainValue, RuleEffect } from "./GateExplainer";
import { simulatedControllerNote } from "../lib/wording";
import s from "./EvidenceDrawer.module.css";

const REGISTER_NOTE = "Source-register status records how far the team has checked the source. It is not a legal verification.";

export function EvidenceDrawer({ decision, bundle, simMin, onClose, regionName = (id) => id }: { decision: Decision | null; bundle: Bundle; simMin: number; onClose: () => void; regionName?: (id: string) => string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (decision && !d.open) d.showModal();
    if (!decision && d.open) d.close();
  }, [decision]);

  return (
    <dialog ref={ref} className={s.dialog} onClose={onClose} aria-labelledby="evidence-title"
      onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      {decision && <Body d={decision} bundle={bundle} simMin={simMin} onClose={onClose} regionName={regionName} />}
    </dialog>
  );
}

function Body({ d, bundle, simMin, onClose, regionName }: { d: Decision; bundle: Bundle; simMin: number; onClose: () => void; regionName: (id: string) => string }) {
  const f = gateFacts(d);
  const simulatedRun = bundle.provenance.human?.startsWith("simulated") ?? false;
  const unsupported = new Set(d.turn?.unsupported ?? []);
  const human = d.followUps.find((f) => f.kind === "HUMAN_DECISION");
  const change = d.followUps.find((f) => f.kind === "STATE_CHANGE" || f.kind === "ACTION_RESULT");
  const dup = d.followUps.find((f) => f.kind === "DUPLICATE_ACTION");
  const stale = d.followUps.find((f) => f.kind === "STALE_APPROVAL");
  const gap = d.followUps.find((f) => f.kind === "GAP_OBSERVATION");
  const msg = d.followUps.find((f) => f.kind === "MESSAGE");
  return (
    <div className={s.body}>
      <header className={s.head}>
        <p className={s.kicker}>Evidence for record <code>#{d.seq}</code>, <code>{formatSimTime(simMin)}</code></p>
        <h2 id="evidence-title" className={s.title}>{ROLE_NAMES[d.role]} proposes to {TOOL_NAMES[d.tool] ?? d.tool}</h2>
        <button type="button" className={`btn btn-quiet ${s.close}`} onClick={onClose} autoFocus>Close</button>
      </header>

      <p className={s.provenance}><span className="not-ai">TEST-DOUBLE-NOT-AI</span> This proposal was written by a scripted client, not by AI.</p>
      <GateDiagram d={d} stage={4} f={f} title={`${ROLE_NAMES[d.role]} proposes to ${TOOL_NAMES[d.tool] ?? d.tool}`} />
      <div className={s.summary}>
        <p className={s.decision}><span className="outcome" data-o={d.outcome}>{OUTCOME_NAMES[d.outcome]}</span></p>
        <p className={s.plain}>{plainDecision(d.outcome, d.legalStatus, d.requiresHuman, d.trail)}{f.human
          ? ` The ${f.simulated ? "simulated controller, standing in for the authority," : "authority"} ${f.human.payload.approved ? "approved it." : f.byPolicy ? "did not approve it: by policy it never decides authority questions, so this is not a judgement on the proposal." : "rejected it."}`
          : ""}</p>
      </div>

      <section className={s.section} aria-labelledby="ev-proposal">
        <h3 id="ev-proposal" className={s.h3}>1. The proposal</h3>
        <p>{ROLE_NAMES[d.role]} asks to {TOOL_NAMES[d.tool] ?? d.tool}{"dest_region" in d.args ? <> to <strong>{regionName(String(d.args.dest_region))}</strong></> : null}{"region" in d.args ? <> to <strong>{regionName(String(d.args.region))}</strong></> : null}. Stated reason: <q>{d.why || "none given"}</q>.</p>
        <details className={s.tech}><summary>Technical detail</summary>
          <dl className={s.kv}>
            <dt>Action</dt><dd><code>{d.tool}</code></dd>
            <dt>Arguments</dt><dd><code className={s.args}>{JSON.stringify(d.args)}</code></dd>
          </dl>
        </details>
      </section>

      <section className={s.section} aria-labelledby="ev-cites">
        <h3 id="ev-cites" className={s.h3}>2. Sources it cites</h3>
        {d.cites.length === 0 ? <p className={s.muted}>No citations were given for this proposal.</p> : (
          <ul className={s.cites}>
            {d.cites.map((c) => {
              const src = bundle.sources[c];
              const warn = !src?.known ? `Not in the knowledge base: flagged as an invented citation.${c.startsWith("made-up") ? " The scripted client plants it on purpose to test this check." : ""}`
                : unsupported.has(c) ? "Not among the passages retrieved for this turn: flagged as unsupported."
                : src.kind === "analyst_note" ? "Analyst note: context written by the team, not legal text." : null;
              return (
                <li key={c} className={s.cite} data-warn={warn ? "" : undefined}>
                  <p className={s.citeId}><code>{c}</code></p>
                  {src?.known ? (
                    <>
                      <p className={s.citeTitle}>{safeHttpsUrl(src.url) ? <a href={safeHttpsUrl(src.url)!} target="_blank" rel="noopener noreferrer">{src.title}</a> : src.title}</p>
                      <p className={s.muted}>{[src.issuer, src.version_date, src.jurisdiction].filter(Boolean).join(", ")}</p>
                      {src.register_status && <p className={s.muted} title={REGISTER_NOTE}>Register status of this cited passage: <code>{src.register_status}</code> (not a legal verification)</p>}
                      <p className={s.muted}>Shown as metadata only. The source text is not published here.</p>
                    </>
                  ) : null}
                  {warn && <p className={s.warn} role="note">{warn}</p>}
                </li>
              );
            })}
          </ul>
        )}
        {(d.turn?.unsupported.length ?? 0) > 0 && !d.cites.some((c) => unsupported.has(c)) && (
          <p className={s.warn} role="note">In the same turn the role also cited {d.turn!.unsupported.join(", ")}, which was not among the passages retrieved for it.{d.turn!.unsupported.some((u) => u.startsWith("made-up")) ? " The scripted client plants this invented citation on purpose to test the check." : ""}</p>
        )}
      </section>

      <section className={s.section} aria-labelledby="ev-gate">
        <h3 id="ev-gate" className={s.h3}>3. The gate decides</h3>
        <p>{LEGAL_STATUS_NAMES[d.legalStatus] ?? d.legalStatus}</p>
        {d.requiresHuman && <p>{d.approval === "competent_authority" ? "A competent authority must decide, with a written basis. In this run a simulated controller plays that authority." : "An operational sign-off is required. In this run a simulated controller gives or refuses it."}</p>}
        <details className={s.tech}><summary>Facts the gate used (taken from the exercise state, not from the proposal)</summary>
        <dl className={s.kv}>
          {Object.entries(d.facts).map(([k, v]) => (
            <Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd>{plainValue(v)}</dd></Fragment>
          ))}
        </dl>
        </details>
        <h4 className={s.h4}>Decision trail</h4>
        <ol className={s.trail}>
          {d.trail.map((t, i) => (
            <li key={i}>
              <p className={s.rule}><code>{t.rule_id}</code> <span className={s.ruleKind}>{t.kind} rule</span> <RuleEffect t={t} d={d} /></p>
              <p>{t.verification === "secondary_only" && !t.downgraded ? <>The rule records: <q>{t.explain}</q></> : t.explain}{simulatedControllerNote(t.explain, simulatedRun) && <span className={s.muted}>{simulatedControllerNote(t.explain, simulatedRun)}</span>}{t.verification === "secondary_only" && !t.downgraded ? <span className={s.muted}> Its source has not been checked against the primary text.</span> : null}</p>
              {(t.source || t.clause) && <p className={s.muted}>Source <code>{t.source}</code>{t.clause ? <> clause <code>{t.clause}</code></> : null}{t.verification ? <> (rule source check: {t.verification.replaceAll("_", " ")})</> : null}{t.downgraded ? ", downgraded because it is not verified" : ""}</p>}
            </li>
          ))}
        </ol>
      </section>

      <section className={s.section} aria-labelledby="ev-then">
        <h3 id="ev-then" className={s.h3}>4. What happened next</h3>
        {human && (
          <p>
            <strong>{human.payload.approved ? "Approved" : f.byPolicy ? "Not approved" : "Rejected"}</strong> by {String(human.actor).startsWith("simulated") ? "the simulated controller (a fixed policy, not a person)" : <code>{human.actor}</code>}{f.byPolicy ? ", which never decides authority questions" : ""}. {human.payload.label ? `${human.payload.label}. ` : ""}
            Recorded reason: <q>{human.payload.reason}</q>
          </p>
        )}
        {change && <p>{change.kind === "STATE_CHANGE" ? <>The state changed: <code>{change.payload.change?.changed}</code> from <code>{change.payload.change?.from}</code> to <code>{change.payload.change?.to}</code>.</> : f.recordOnly ? <>Recorded only: {change.payload.change?.note ?? "recorded"}. Nothing in the network changed.</> : change.payload.executed === true ? <>Carried out. {change.payload.change?.note ?? ""}</> : <>Not carried out. {change.payload.change?.note ?? change.payload.change?.error ?? ""}</>}</p>}
        {stale && <p><strong>The approval went stale</strong>: the state changed before the action could run, so nothing was carried out.</p>}
        {dup && <p>This repeats an earlier proposal, so it was not carried out again.</p>}
        {gap && <p>The gap observation <code>{gap.payload.gap_id}</code> was recorded as a draft for human review ({gap.payload.review_status ?? gap.payload.status}).</p>}
        {msg && <p>The request was sent as a message to <code>{msg.payload.to}</code>.</p>}
        {!human && !change && !dup && !stale && !gap && !msg && <p className={s.muted}>Nothing was carried out for this proposal.</p>}
        <p className={s.muted}>State digest at decision time <code>{d.stateDigest}</code>; action id <code>{d.actionId}</code>.</p>
        <p className={s.records} data-testid="drawer-records">
          <span>Check it in the audit record:</span>{" "}
          <Link to={`/audit?record=${d.seq}`}>gate decision #{d.seq}</Link>
          {d.followUps.map((f) => <Fragment key={f.seq}>, <Link to={`/audit?record=${f.seq}`}>{(KIND_NAMES[f.kind] ?? f.kind).toLowerCase()} #{f.seq}</Link></Fragment>)}
        </p>
      </section>
    </div>
  );
}
