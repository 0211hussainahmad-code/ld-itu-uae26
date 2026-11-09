import { formatSimTime, type NetState, type Topology, type TrafficScope } from "../lib/replay";
import s from "./TrafficPanel.module.css";

const HEALTH = { OK: "Healthy", DEGRADED: "Degraded", DOWN: "Down" } as const;

// `scope` comes from the role's build_view keys ("all" for the exercise controller). `showServiceNotes` adds
// controller-only context about the AI endpoint, which roles without service data are not given.
export function TrafficPanel({ state, topology, scope, showServiceNotes }: { state: NetState; topology: Topology; scope: TrafficScope; showServiceNotes: boolean }) {
  if (scope === "none") {
    return <div className={s.wrap}><p className={s.empty}>This role is shown no traffic figures and no demand classes.</p></div>;
  }
  const classes = topology.demand.filter((d) => scope !== "gov_ai" || d.id === "gov_ai");
  const regionLabel = (id: string) => topology.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "").replace("Cloud region ", "") ?? id;
  return (
    <div className={s.wrap}>
      <div className={s.head}>
        <h3 className={s.h3}>Traffic by demand class</h3>
        <p className={s.source}>
          {scope === "names" ? "This role sees the class names only, no figures."
            : state.traffic && state.trafficFrom ? <>As recorded at event {state.trafficFrom.eventId.replace("E", "")}, <code>{formatSimTime(state.trafficFrom.simMin)}</code>. Synthetic capacity units (cu).</>
            : "No traffic has been recorded yet at this point."}
          {showServiceNotes && scope !== "names" && state.trafficFrom && state.endpointChangedAt && state.endpointChangedAt > state.trafficFrom.seq &&
            <> The AI endpoint changed after this measurement; the next figures arrive with the next event.</>}
        </p>
      </div>
      <ul className={s.rows}>
        {classes.map((d) => {
          const t = scope === "names" ? null : state.traffic?.[d.id];
          const pct = t ? Math.round(t.share * 100) : 0;
          return (
            <li key={d.id} className={s.row} data-health={t?.health}>
              <span className={s.label}>{d.label}</span>
              {t ? (
                <>
                  <span className={s.meter} aria-hidden="true"><i style={{ width: `${pct}%` }} /></span>
                  <span className={s.value}><code>{t.delivered}/{t.demand} cu</code> to {regionLabel(t.dest)}</span>
                  <span className={s.health}>{HEALTH[t.health]}</span>
                </>
              ) : <span className={s.value}>{scope === "names" ? "figures not visible to this role" : "not recorded yet"}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
