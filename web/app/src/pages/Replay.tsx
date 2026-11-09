import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { NetworkChart } from "../components/NetworkChart";
import { RolePanel } from "../components/RolePanel";
import { RoleView } from "../components/RoleView";
import { Empty, LoadError, Loading, Refused } from "../components/StateViews";
import { Term } from "../components/Term";
import { Timeline } from "../components/Timeline";
import { TrafficPanel } from "../components/TrafficPanel";
import { useSoundMood } from "../components/SoundControl";
import { useVerifiedReplay } from "../hooks/useVerifiedReplay";
import type { Bundle, ManifestEntry } from "../lib/bundle";
import { buildReplay, formatSimTime, KIND_NAMES, OUTCOME_NAMES, ROLE_IDS, ROLE_NAMES, TOOL_NAMES, type Decision, type Replay as ReplayModel, type RoleId } from "../lib/replay";
import { sound, type Mood } from "../lib/sound";
import type { VerifyResult } from "../lib/verify";
import s from "./Replay.module.css";

export function Replay() {
  const { bundleId = null } = useParams();
  const { outcome, progress, retry } = useVerifiedReplay(bundleId);
  if (outcome === null) return <Loading progress={progress} />;
  if (outcome.kind === "empty") return <Empty />;
  if (outcome.kind === "error") return <LoadError reason={outcome.reason} onRetry={retry} />;
  if (outcome.kind === "refused") return <Refused outcome={outcome} />;
  return <ReplayView bundle={outcome.bundle} entry={outcome.entry} result={outcome.result} />;
}


function ReplayView({ bundle, entry, result }: { bundle: Bundle; entry: ManifestEntry; result: VerifyResult }) {
  const replay = useMemo<ReplayModel>(() => buildReplay(bundle), [bundle]);
  const [params, setParams] = useSearchParams();
  const raw = Math.trunc(Number(params.get("step")));          // 1-based in the address, like "Step N of M"
  const initial = Number.isFinite(raw) && raw > 0 ? Math.min(replay.steps.length - 1, raw - 1) : 0;
  const [index, setIndexRaw] = useState(initial);
  // Addresses that ask for something this run does not have say so, instead of silently changing it.
  const badStep = params.has("step") && !(Number.isFinite(raw) && raw >= 1 && raw <= replay.steps.length) ? (params.get("step") ?? "").slice(0, 12) : null;
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const roleParam = params.get("role");
  const badRole = roleParam !== null && !(ROLE_IDS as readonly string[]).includes(roleParam) ? roleParam.slice(0, 24) : null;
  const [roleId, setRoleIdRaw] = useState<RoleId | null>((ROLE_IDS as readonly string[]).includes(roleParam ?? "") ? (roleParam as RoleId) : null);
  const setRoleId = useCallback((r: RoleId | null) => {
    setRoleIdRaw(r);
    setParams((p) => { if (r) p.set("role", r); else p.delete("role"); return p; }, { replace: true });
  }, [setParams]);
  const [open, setOpen] = useState<Decision | null>(null);

  const setIndex = useCallback((i: number) => {
    setIndexRaw(i);
    setParams((p) => { p.set("step", String(i + 1)); return p; }, { replace: true });
  }, [setParams]);

  const step = replay.steps[index]!;
  const state = replay.stateAt(index);
  // The score follows what is on screen: reading a role view, an unresolved authority question, or disruption.
  const mood: Mood = roleId ? "focus"
    : step.kind === "HUMAN_DECISION" || (step.decision && step.decision.outcome !== "PERMITTED") ? "tension"
    : step.eventId ? "disrupted" : "calm";
  useSoundMood(mood);
  // Cues for story events, when the visitor moves onto them: a link failing, a proposal held at the gate.
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    if (step.kind === "EVENT") sound().cue("break");
    else if (step.kind === "GATE_DECISION" && step.decision && step.decision.outcome !== "PERMITTED") sound().cue("hold");
  }, [step]);
  const role = replay.roles.find((r) => r.id === roleId) ?? null;
  // Key moments of the current event: decisions that were escalated or prohibited, and state changes.
  const evIdx = replay.events.findIndex((e) => e.id === step.eventId);
  const evStart = evIdx >= 0 ? replay.events[evIdx]!.stepIndex : -1;
  const evEnd = evIdx >= 0 && evIdx + 1 < replay.events.length ? replay.events[evIdx + 1]!.stepIndex : replay.steps.length;
  const keyMoments = step.kind === "EVENT" ? replay.steps.slice(evStart + 1, evEnd).filter((x) =>
    (x.kind === "GATE_DECISION" && x.decision && x.decision.outcome !== "PERMITTED") || x.kind === "STATE_CHANGE")
    .filter((x, i, a) => a.findIndex((y) => y.decision?.tool === x.decision?.tool && y.kind === x.kind) === i).slice(0, 3) : [];

  return (
    <div className={s.page} data-replay="">
      <div className={s.provenance} role="region" aria-label="Provenance of this replay">
        <span className="not-ai" data-testid="not-ai-label">TEST-DOUBLE-NOT-AI</span>
        <span className={s.provText} data-testid="provenance"><span className={s.long}>Scripted replay: clients play all four roles from a script. This is not AI output.</span><span className={s.short}>Scripted replay, not AI output.</span></span>
        <span className={s.provCheck} data-testid="verification">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7" /></svg>
          <span className={s.long}>Rehashed in your browser: all {result.checked} of {result.total} records agree with the chain. Compare its head on the audit page.</span>
          <span className={s.short}>{result.checked} of {result.total} records agree with the chain</span>
        </span>
        <Link to="/audit" className={s.provLink}>Audit record <code className={s.long}>{entry.bundle_id}</code></Link>
      </div>

      {(badStep !== null || badRole !== null) && (
        <p className={s.notice} role="status" data-testid="bad-address">
          {badStep !== null && <>There is no step {badStep || "with that number"}: this replay has {replay.steps.length} steps, so it opens at step {initial + 1}. </>}
          {badRole !== null && <>There is no role called {badRole}: the roles are {replay.roles.map((r) => r.id).join(", ")}, so the controller's view is shown.</>}
        </p>
      )}
      <div className={s.grid}>
        <div className={s.main}>
          <div className={s.stage}>
          <article className={s.step} aria-live="polite" aria-atomic="true" data-kind={step.kind}>
            {role && (
              <p className={s.recordScope} data-testid="record-scope">
                Exercise record, as the controller sees it. This narrative is not what the {ROLE_NAMES[role.id]} is given; that is shown below.
              </p>
            )}
            <p className={s.stepMeta}>
              <span className={s.kind}>{KIND_NAMES[step.kind] ?? step.kind}</span>
              <code>{formatSimTime(step.simMin)}</code>
              {step.eventId && <span className={s.long}>during event {step.eventId.replace("E", "")}</span>}
              <Link to={`/audit?record=${step.seq}`} className={s.recordLink}>record <code>#{step.seq}</code> in the audit</Link>
            </p>
            <h1 className={s.stepTitle}>{step.title}</h1>
            {step.detail && <p className={["TURN_PARSED", "MESSAGE", "DELIVERY", "HUMAN_DECISION", "GAP_OBSERVATION"].includes(step.kind) ? s.recorded : s.stepDetail}>{step.detail}</p>}
            {step.warnings.map((w) => <p key={w} className={s.warn} role="note">{w}</p>)}
            {step.decision && (
              <button type="button" className={`btn btn-primary ${s.evidenceBtn}`} onClick={() => setOpen(step.decision!)} aria-haspopup="dialog">
                Open the evidence for this decision
              </button>
            )}
            {keyMoments.length > 0 && (
              <div className={s.moments}>
                <span>Key moments in this event</span>
                {keyMoments.map((k) => (
                  <button key={k.seq} type="button" className="btn" onClick={() => { setPlaying(false); setIndex(k.index); }}>
                    {k.kind === "STATE_CHANGE" ? k.title : <>{TOOL_NAMES[k.decision!.tool] ?? k.decision!.tool}: <span className="outcome" data-o={k.decision!.outcome}>{OUTCOME_NAMES[k.decision!.outcome]}</span></>}
                  </button>
                ))}
              </div>
            )}
          </article>
          {/* On phones the role choice sits right here, under the step, instead of far below the map. */}
          <RoleTabs className={s.tabsInline} roles={replay.roles.map((r) => r.id)} roleId={roleId} onRole={setRoleId} />
          {role ? (
            <RoleView replay={replay} role={role} stepIndex={index} />
          ) : (
            <>
              <div className={s.chartHead}>
                <h2 className={s.h2} id="chart-title">Exercise controller's schematic</h2>
                <span className={s.synthetic}>synthetic: routes and figures are invented</span>
              </div>
              <div className={s.chart}>
                <NetworkChart topology={replay.topology} linksDown={state.linksDown} endpointRegion={state.endpointRegion} labelledBy="chart-title" showCaption={false} motion={playing && open === null} />
              </div>
              <p className={s.legend} aria-label="Legend">
                <span data-l="up">carrying traffic</span><span data-l="down">failed</span><span data-l="endpoint">AI endpoint</span>
              </p>
              <p className={s.observer} data-testid="observer-note">Controller's view: the full network, as only the exercise controller sees it. No AI role is given this map, its link capacities or latencies. Choose a role to see what it is given.</p>
            </>
          )}
          </div>

          {!role && (
            <>
              <p className={s.chartNote}>
                The service's AI endpoint is <strong>{regionName(replay, state.endpointRegion)}</strong>.{" "}
                {state.recordsRegion && <>Its case files are in <strong>{regionName(replay, state.recordsRegion)}</strong>{replay.recordsMoved ? "" : "; no transfer was carried out in this run"}. </>}
                Select a link or a node for details.
              </p>
              <TrafficPanel state={state} topology={replay.topology} scope="all" showServiceNotes />
            </>
          )}
        </div>

        <aside className={s.side} aria-label="Role views">
          <RoleTabs className={s.tabs} roles={replay.roles.map((r) => r.id)} roleId={roleId} onRole={setRoleId} />
          <p className={s.tabHint}>
            Choosing a role replaces the controller's schematic with exactly what that role is given. <Term tip="Each role is shown only what the exercise rules allow it to see. No role is given the network map, link capacities or latencies. The operator sees international link status and traffic; the service sees its own settings and traffic; the regulator learns only the names of the traffic classes; the adviser sees no network data at all, only messages and sources.">Why the views differ</Term>
          </p>
          <h2 className={s.sideTitle}>{role ? ROLE_NAMES[role.id] : "Exercise controller"}</h2>
          <div aria-live="polite">
            <RolePanel replay={replay} bundle={bundle} role={role} uptoSeq={step.seq} onOpen={setOpen} />
          </div>
        </aside>
      </div>

      <Timeline replay={replay} index={index} playing={playing} speed={speed} onIndex={setIndex} onPlaying={setPlaying} onSpeed={setSpeed} />
      <EvidenceDrawer decision={open} bundle={bundle} simMin={open ? (replay.records.find((r) => r.seq === open.seq)?.sim_min ?? 0) : 0} onClose={() => setOpen(null)} regionName={(id) => regionName(replay, id)} />
    </div>
  );
}

const SHORT: Record<RoleId, string> = { operator: "Operator", service: "Service", regulator: "Regulator", adviser: "Adviser" };

// One of the two copies is hidden by CSS at any width, so assistive technology only ever meets one group.
function RoleTabs({ className, roles, roleId, onRole }: { className?: string; roles: RoleId[]; roleId: RoleId | null; onRole: (r: RoleId | null) => void }) {
  return (
    <div className={className} role="group" aria-label="Whose view to show">
      <button type="button" aria-pressed={roleId === null} onClick={() => onRole(null)} aria-label="All roles (exercise controller)">All</button>
      {roles.map((r) => (
        <button key={r} type="button" aria-pressed={roleId === r} onClick={() => onRole(r)} aria-label={ROLE_NAMES[r]}>{SHORT[r]}</button>
      ))}
    </div>
  );
}

function regionName(r: ReplayModel, id: string | null) {
  return r.topology.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "").replace("Cloud region ", "") ?? "unknown";
}
