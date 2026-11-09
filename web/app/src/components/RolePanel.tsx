import { OUTCOME_NAMES, ROLE_NAMES, SEES_NAMES, TOOL_NAMES, formatSimTime, type AuditRec, type Decision, type Replay, type RoleInfo } from "../lib/replay";
import type { Bundle } from "../lib/bundle";
import s from "./RolePanel.module.css";

interface Props {
  replay: Replay;
  bundle: Bundle;
  role: RoleInfo | null;
  uptoSeq: number;
  onOpen: (d: Decision) => void;
}

export function RolePanel({ replay, bundle, role, uptoSeq, onOpen }: Props) {
  const recs = replay.records.filter((r) => r.seq <= uptoSeq);
  if (!role) return <ControllerView replay={replay} uptoSeq={uptoSeq} onOpen={onOpen} />;

  const inbox = recs.filter((r) => (r.kind === "DELIVERY" && r.payload.to === role.id)
    || (r.kind === "MESSAGE" && (r.payload.to === role.id || (r.payload.to === "ALL" && r.actor !== role.id)))).reverse();
  const lastTurn = [...recs].reverse().find((r) => r.kind === "TURN_PARSED" && r.actor === role.id);
  const lastAgent = lastTurn ? [...recs].reverse().find((r) => r.kind === "AGENT_TURN" && r.actor === role.id && r.seq < lastTurn.seq) : undefined;
  const retrieved = (lastAgent?.payload.retrieved as string[] | undefined) ?? [];
  const proposals = replay.decisions.filter((d) => d.role === role.id && d.seq <= uptoSeq).reverse();
  const unsupported: string[] = lastTurn?.payload.unsupported_citations ?? [];

  return (
    <div className={s.panel}>
      <section className={s.block} aria-label={`Kinds of data given to the ${ROLE_NAMES[role.id]}`}>
        <p className={s.titleLine}>{role.title}</p>
        <ul className={s.chips}>
          {role.sees.length ? role.sees.map((x) => <li key={x}>{SEES_NAMES[x] ?? x}</li>) : <li data-none>No network or service data</li>}
        </ul>
      </section>

      <section className={s.block} aria-labelledby={`assess-${role.id}`}>
        <h3 id={`assess-${role.id}`} className={s.h3}>Latest assessment <span className={s.scripted}>scripted placeholder</span></h3>
        {lastTurn ? (
          <>
            <p className={s.quote}>{lastTurn.payload.assessment}</p>
            {(lastTurn.payload.unknowns ?? []).length > 0 && <p className={s.meta}>Unknowns: {(lastTurn.payload.unknowns as string[]).join("; ")}</p>}
            {unsupported.length > 0 && <p className={s.warn} role="note">Cites {unsupported.join(", ")}, which was not among the passages retrieved for this turn.</p>}
            <p className={s.meta}><code>{formatSimTime(lastTurn.sim_min ?? 0)}</code> record <code>#{lastTurn.seq}</code>, recorded text from a scripted client</p>
          </>
        ) : <p className={s.meta}>No turn yet at this point in the replay.</p>}
      </section>

      <section className={s.block} aria-labelledby={`props-${role.id}`}>
        <h3 id={`props-${role.id}`} className={s.h3}>Proposals and gate outcomes</h3>
        {proposals.length ? (
          <ul className={s.list}>
            {proposals.slice(0, 6).map((d) => (
              <li key={d.seq}>
                <button type="button" className={s.decision} onClick={() => onOpen(d)} aria-haspopup="dialog">
                  <span>{TOOL_NAMES[d.tool] ?? d.tool}</span>
                  <span className="outcome" data-o={d.outcome}>{OUTCOME_NAMES[d.outcome]}</span>
                  {(() => { const h = d.followUps.find((f) => f.kind === "HUMAN_DECISION" && f.seq <= uptoSeq); return h ? <span className={s.human}>simulated controller: {h.payload.approved ? "approved" : /never decide authority/.test(String(h.payload.reason ?? "")) ? "not approved, by policy" : "rejected"}</span> : null; })()}
                  <span className={s.open}>Evidence</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className={s.meta}>No proposals yet.</p>}
      </section>

      <section className={s.block} aria-labelledby={`inbox-${role.id}`}>
        <h3 id={`inbox-${role.id}`} className={s.h3}>What reached this role</h3>
        {inbox.length ? (
          <ul className={s.inbox}>
            {inbox.slice(0, 6).map((r) => <InboxItem key={r.seq} r={r} />)}
          </ul>
        ) : <p className={s.meta}>Nothing yet.</p>}
      </section>

      {retrieved.length > 0 && (
        <section className={s.block} aria-labelledby={`src-${role.id}`}>
          <h3 id={`src-${role.id}`} className={s.h3}>Sources retrieved for its latest turn</h3>
          <ul className={s.sources}>
            {retrieved.map((c) => {
              const src = bundle.sources[c];
              return <li key={c}><code>{c}</code>{src?.title ? <span> {src.title}</span> : null}</li>;
            })}
          </ul>
          <p className={s.meta}>Metadata only. Source text is not published.</p>
        </section>
      )}
    </div>
  );
}

function InboxItem({ r }: { r: AuditRec }) {
  const from = r.kind === "DELIVERY" ? String(r.payload.kind).replaceAll("_", " ") : ROLE_NAMES[r.actor as keyof typeof ROLE_NAMES] ?? r.actor;
  return (
    <li>
      <p className={s.from}><code>{formatSimTime(r.sim_min ?? 0)}</code> {r.kind === "DELIVERY" ? `Scenario ${from}` : `From ${from}`}</p>
      <p className={s.msg}>{r.payload.text}</p>
    </li>
  );
}

function ControllerView({ replay, uptoSeq, onOpen }: { replay: Replay; uptoSeq: number; onOpen: (d: Decision) => void }) {
  const ds = replay.decisions.filter((d) => d.seq <= uptoSeq).reverse();
  const humans = replay.records.filter((r) => r.kind === "HUMAN_DECISION" && r.seq <= uptoSeq);
  return (
    <div className={s.panel}>
      <section className={s.block}>
        <p className={s.titleLine}>The exercise controller's view: the full network, everything each role is given, plus the gate's decisions and the simulated controller's.</p>
        <p className={s.meta}>{ds.length} gate {ds.length === 1 ? "decision" : "decisions"} and {humans.length} {humans.length === 1 ? "decision" : "decisions"} by the simulated controller so far.</p>
      </section>
      <section className={s.block} aria-labelledby="ctl-decisions">
        <h3 id="ctl-decisions" className={s.h3}>Gate decisions so far</h3>
        {ds.length ? (
          <ul className={s.list}>
            {ds.map((d) => (
              <li key={d.seq}>
                <button type="button" className={s.decision} onClick={() => onOpen(d)} aria-haspopup="dialog">
                  <span><span className={s.who}>{ROLE_NAMES[d.role]}:</span> {TOOL_NAMES[d.tool] ?? d.tool}</span>
                  <span className="outcome" data-o={d.outcome}>{OUTCOME_NAMES[d.outcome]}</span>
                  {(() => { const h = d.followUps.find((f) => f.kind === "HUMAN_DECISION" && f.seq <= uptoSeq); return h ? <span className={s.human}>simulated controller: {h.payload.approved ? "approved" : /never decide authority/.test(String(h.payload.reason ?? "")) ? "not approved, by policy" : "rejected"}</span> : null; })()}
                  <span className={s.open}>Evidence</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <p className={s.meta}>No proposals yet. Step forward to the first event.</p>}
      </section>
    </div>
  );
}
