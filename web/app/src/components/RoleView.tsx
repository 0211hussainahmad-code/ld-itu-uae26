import { useEffect, useId, useRef, useState } from "react";
import { ROLE_NAMES, SEES_NAMES, SHOWN_IN_RECORD, roleViewFor, trafficScope, type Replay, type RoleInfo } from "../lib/replay";
import { TrafficPanel } from "./TrafficPanel";
import s from "./RoleView.module.css";

// Exactly what linkdown/agents.py build_view() gives this role, reconstructed from the published record at
// the current step. Nothing else is rendered: no schematic, no node names, no per-link capacity or latency.
// Items the role is given but the published record does not contain are named, not invented.
export function RoleView({ replay, role, stepIndex, compact = false }: { replay: Replay; role: RoleInfo; stepIndex: number; compact?: boolean }) {
  const view = roleViewFor(role);
  const titleId = useId();
  // A compact view scrolls on phones; it joins the tab order only while it actually overflows.
  const ref = useRef<HTMLElement>(null);
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!compact || !el) return;
    const check = () => setScrolls(el.scrollHeight > el.clientHeight + 1);
    check();
    // Guarded: a browser without ResizeObserver still gets the view (re-checked on window resize instead).
    window.addEventListener("resize", check);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(check) : null;
    ro?.observe(el);
    return () => { window.removeEventListener("resize", check); ro?.disconnect(); };
  }, [compact, role.id, stepIndex]);
  const state = replay.stateAt(stepIndex);
  const name = ROLE_NAMES[role.id];
  const hidden = [...view].filter((k) => !SHOWN_IN_RECORD[k]);
  const region = (id: string | null | undefined) => replay.topology.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "").replace("Cloud region ", "") ?? "unknown";
  const intl = replay.topology.links.filter((l) => l.group !== "domestic");   // build_view: links with group != domestic
  const down = new Set(state.linksDown);

  return (
    <section ref={ref} className={s.view} data-testid="role-view" data-role={role.id} data-compact={compact || undefined}
      tabIndex={scrolls ? 0 : undefined} aria-labelledby={titleId}>
      <h2 className={s.title} id={titleId}>What the {name} is given</h2>
      <p className={s.note}>
        Only what this role receives under the exercise rules, reconstructed from the published record. The role gets this
        view on each of its turns.
      </p>

      {view.size === 0 && (
        <p className={s.empty}>This role receives no network or service data: only messages, gate feedback and source passages.</p>
      )}

      {view.has("links") && (
        <div className={s.block}>
          <h3 className={s.h3}>{SEES_NAMES.links}</h3>
          <ul className={s.links}>
            {intl.map((l) => (
              <li key={l.id} data-down={down.has(l.id) || undefined}>
                <code>{l.id}</code><span>{l.label}</span><b>{down.has(l.id) ? "down" : "up"}</b>
              </li>
            ))}
          </ul>
        </div>
      )}

      {view.has("service") && (
        <div className={s.block}>
          <h3 className={s.h3}>{SEES_NAMES.service}</h3>
          <dl className={s.kv}>
            <dt>AI endpoint</dt><dd>{region(state.endpointRegion)}</dd>
            <dt>Case files stored in</dt><dd>{region(state.recordsRegion)}</dd>
            {state.serviceMode && <><dt>Service mode</dt><dd>{state.serviceMode}</dd></>}
          </dl>
          <p className={s.small}>Under the exercise code (build_view), this role is also given the service's name, owner, entity type and key custody. They are not in the published record, so this page cannot show them.</p>
        </div>
      )}

      {(view.has("traffic") || view.has("service_traffic") || view.has("demand_classes")) && (
        <TrafficPanel state={state} topology={replay.topology} scope={trafficScope(view)} showServiceNotes={view.has("service")} />
      )}

      {hidden.length > 0 && (
        <div className={s.block}>
          <h3 className={s.h3}>Also given to this role, not in the published record</h3>
          <ul className={s.hidden}>{hidden.map((k) => <li key={k}>{SEES_NAMES[k]}</li>)}</ul>
        </div>
      )}
    </section>
  );
}
