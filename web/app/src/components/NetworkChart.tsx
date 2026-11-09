import { useEffect, useId, useMemo, useRef, useState } from "react";
import { LAYOUT, VIEW, contours, linkPath, midpoint } from "../lib/layout";
import type { Topology } from "../lib/replay";
import s from "./NetworkChart.module.css";

export type IntroPhase = "draw" | "flow" | "break" | "final";

/** Consequences drawn on the map, each derived by the caller from a record (never invented). */
export type Overlay =
  | { kind: "moved"; from: string; to: string; label: string }      // a recorded state change of the AI endpoint
  | { kind: "held"; from: string; to: string; label: string };      // a proposal stopped at the gate, never carried out

interface Props {
  topology: Topology;
  linksDown: string[];
  endpointRegion?: string | null;
  phase?: IntroPhase;
  interactive?: boolean;
  labelledBy?: string;
  caption?: string;
  compact?: boolean;
  /** Decorative motion follows the replay transport; recorded state is always rendered. */
  motion?: boolean;
  showCaption?: boolean;
  overlays?: Overlay[];
}

type Focus = { kind: "link" | "node"; id: string } | null;

// Keep a focused chart element clear of the sticky replay timeline (about 190px tall on phones).
function revealAboveTimeline(el: Element) {
  const r = el.getBoundingClientRect();
  if (r.bottom > window.innerHeight - 200 || r.top < 80) el.scrollIntoView({ block: "center" });
}

const CONTOURS = contours();

// The full schematic is the exercise controller's (independent observer's) view. No AI role is given the
// topology, per-link capacity or latency (linkdown/agents.py build_view), so this chart is never used as a
// role view; role views are rendered by RoleView instead.
export function NetworkChart({ topology, linksDown, endpointRegion = null, phase = "final", interactive = true, labelledBy, caption, compact = false, motion = true, showCaption = true, overlays = [] }: Props) {
  const [focus, setFocus] = useState<Focus>(null);
  const [pinned, setPinned] = useState<Focus>(null);
  const uid = useId().replace(/:/g, "");
  const shown = pinned ?? focus;
  const down = useMemo(() => new Set(linksDown), [linksDown]);
  const nodes = topology.nodes.map((n) => ({ ...n, ...LAYOUT.nodes[n.id]! }));
  const pos = Object.fromEntries(nodes.map((n) => [n.id, n]));

  const state = (id: string, _group: string) => (down.has(id) ? "down" : "up");

  const toggle = (f: NonNullable<Focus>) => setPinned((p) => (p && p.id === f.id && p.kind === f.kind ? null : f));

  // The signal and endpoint animations repaint the whole SVG every frame (stroke-dashoffset and SVG transforms
  // cannot be composited; WebKit repaints even when the map is scrolled away). Pause them while no part of the
  // map is on screen; they resume where they were when it returns. Nothing visible changes.
  const figRef = useRef<HTMLElement>(null);
  const [offscreen, setOffscreen] = useState(false);
  useEffect(() => {
    const el = figRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([en]) => setOffscreen(!en!.isIntersecting), { rootMargin: "200px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <figure ref={figRef} className={s.figure} data-phase={phase} data-motion={motion ? undefined : "paused"} data-compact={compact || undefined} data-offscreen={offscreen || undefined} aria-labelledby={labelledBy}>
      <svg className={s.svg} viewBox={`0 0 ${VIEW.w} ${VIEW.h}`} role="group"
        aria-label="Exercise controller's schematic of the synthetic network (controller's view, not given to any AI role): six nodes and ten links">
        <defs>
          <radialGradient id={`${uid}-glow`} cx="50%" cy="45%" r="60%">
            <stop offset="0%" stopColor="var(--shelf-light)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--abyss)" stopOpacity="0" />
          </radialGradient>
          <filter id={`${uid}-soft`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3.2" />
          </filter>
        </defs>
        <rect width={VIEW.w} height={VIEW.h} fill={`url(#${uid}-glow)`} />
        <g className={s.contours} aria-hidden="true">
          {CONTOURS.map((d, i) => <path key={i} d={d} />)}
        </g>

        <g aria-hidden="true">
          {topology.links.map((l) => {
            const a = pos[l.a]!, b = pos[l.b]!, c = LAYOUT.links[l.id]!.c;
            const st = state(l.id, l.group);
            return (
              <g key={l.id} className={s.link} data-state={st} data-group={l.group}>
                <path className={s.cable} d={linkPath(a, b, c)} />
                {st === "up" && (
                  <>
                    <path className={s.halo} d={linkPath(a, b, c)} filter={`url(#${uid}-soft)`} />
                    <path className={s.signal} d={linkPath(a, b, c)} pathLength={100}
                      style={{ animationDuration: `${(2.4 + l.ms / 28).toFixed(2)}s` }} />
                  </>
                )}
              </g>
            );
          })}
        </g>

        <g aria-hidden="true">
          {topology.links.filter((l) => state(l.id, l.group) === "down").map((l) => {
            const m = midpoint(pos[l.a]!, pos[l.b]!, LAYOUT.links[l.id]!.c);
            return (
              <g key={`break-${l.id}`} className={s.break} transform={`translate(${m.x} ${m.y})`}>
                <circle className={s.ripple} r="10" />
                <path d="M-7,-9 L-2,9 M3,-9 L8,9" />
              </g>
            );
          })}
        </g>

        {overlays.length > 0 && <Overlays overlays={overlays} pos={pos} uid={uid} />}

        {nodes.map((n) => {
          const isEndpoint = endpointRegion === n.id;
          return (
            <g key={n.id} className={s.node} data-kind={n.kind} data-endpoint={isEndpoint || undefined}
              transform={`translate(${n.x} ${n.y})`} aria-hidden="true">
              {isEndpoint && <circle className={s.endpointRing} r="26" />}
              {n.kind === "landing" ? (
                <g className={s.mark}><circle r="11" /><path d="M-17,0 H17 M0,-17 V17" /></g>
              ) : n.kind === "transit" ? (
                <rect className={s.mark} x="-8" y="-8" width="16" height="16" transform="rotate(45)" />
              ) : n.kind === "domestic" ? (
                <circle className={s.mark} r="9" />
              ) : (
                <g className={s.mark}><circle r="14" /><circle r="5" className={s.core} /></g>
              )}
              {!compact && <text className={s.name} x={n.dx} y={n.dy} textAnchor={n.anchor}>{n.name}</text>}
              {!compact && n.kind === "region" && (
                <text className={s.sub} x={n.dx} y={n.dy + (n.dy < 0 ? -28 : 20)} textAnchor={n.anchor}>
                  {n.in_uae ? "cloud region in the UAE" : "cloud region abroad"}
                </text>
              )}
            </g>
          );
        })}

        {interactive && (
          <g className={s.hits}>
            {topology.links.map((l) => {
              const a = pos[l.a]!, b = pos[l.b]!, c = LAYOUT.links[l.id]!.c;
              const st = state(l.id, l.group);
              const f = { kind: "link" as const, id: l.id };
              return (
                <path key={`hit-${l.id}`} d={linkPath(a, b, c)} className={s.hitLink} tabIndex={0} role="button"
                  aria-pressed={pinned?.id === l.id}
                  aria-label={`${l.label}, link ${l.id}: ${st === "down" ? "failed" : "carrying traffic"}`}
                  onMouseEnter={() => setFocus(f)} onMouseLeave={() => setFocus(null)}
                  onFocus={(e) => { setFocus(f); revealAboveTimeline(e.currentTarget); }} onBlur={() => setFocus(null)}
                  onClick={() => toggle(f)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(f); } if (e.key === "Escape") setPinned(null); }} />
              );
            })}
            {nodes.map((n) => {
              const f = { kind: "node" as const, id: n.id };
              return (
                <circle key={`hitn-${n.id}`} cx={n.x} cy={n.y} r="44" className={s.hitNode} tabIndex={0} role="button"
                  aria-pressed={pinned?.id === n.id} aria-label={`${n.label}`}
                  onMouseEnter={() => setFocus(f)} onMouseLeave={() => setFocus(null)}
                  onFocus={(e) => { setFocus(f); revealAboveTimeline(e.currentTarget); }} onBlur={() => setFocus(null)}
                  onClick={() => toggle(f)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(f); } if (e.key === "Escape") setPinned(null); }} />
              );
            })}
          </g>
        )}
      </svg>
      {overlays.length > 0 && (
        <p className={s.overlayKey} aria-hidden="true">
          {overlays.map((o) => <span key={o.kind} data-k={o.kind}>{o.label}</span>)}
        </p>
      )}
      {interactive && shown && <ChartCard focus={shown} topology={topology} state={state} endpointRegion={endpointRegion} onClose={() => setPinned(null)} pinned={!!pinned} />}
      {!compact && showCaption && <figcaption className={s.caption}>{caption ?? "Synthetic schematic: routes, traffic and capacities are invented for the exercise."}</figcaption>}
    </figure>
  );
}

type P = { x: number; y: number };
const at = (a: P, c: P, b: P, t: number) => ({ x: (1 - t) ** 2 * a.x + 2 * (1 - t) * t * c.x + t ** 2 * b.x, y: (1 - t) ** 2 * a.y + 2 * (1 - t) * t * c.y + t ** 2 * b.y });
// Split a quadratic curve at t (de Casteljau), returning the two halves as path data.
function split(a: P, c: P, b: P, t: number): [string, string] {
  const c1 = { x: a.x + (c.x - a.x) * t, y: a.y + (c.y - a.y) * t }, c2 = { x: c.x + (b.x - c.x) * t, y: c.y + (b.y - c.y) * t }, m = at(a, c, b, t);
  return [`M${a.x},${a.y} Q${c1.x},${c1.y} ${m.x},${m.y}`, `M${m.x},${m.y} Q${c2.x},${c2.y} ${b.x},${b.y}`];
}
// A bend that keeps an overlay clear of the cables: bulge away from the map's centre.
function bend(a: P, b: P): P {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len, ny = dx / len;
  if ((mx + nx - 600) ** 2 + (my + ny - 350) ** 2 < (mx - 600) ** 2 + (my - 350) ** 2) { nx = -nx; ny = -ny; }
  return { x: mx + nx * len * 0.32, y: my + ny * len * 0.32 };
}

function Overlays({ overlays, pos, uid }: { overlays: Overlay[]; pos: Record<string, P>; uid: string }) {
  return (
    <g aria-hidden="true">
      <defs>
        <marker id={`${uid}-arrow`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className={s.arrowHead} />
        </marker>
      </defs>
      {overlays.map((o) => {
        const a = pos[o.from], b = pos[o.to];
        if (!a || !b) return null;
        const c = bend(a, b);
        if (o.kind === "moved") {
          const m = at(a, c, b, 0.3);   // label high on the arc, clear of the node names below
          return (
            <g key={`m-${o.from}-${o.to}`} className={s.moved} data-overlay="moved">
              <path d={`M${a.x},${a.y} Q${c.x},${c.y} ${b.x},${b.y}`} markerEnd={`url(#${uid}-arrow)`} />
              <text x={m.x + (m.x < 600 ? -16 : 16)} y={m.y + 6} textAnchor={m.x < 600 ? "end" : "start"} className={s.overlayLabel}>{o.label}</text>
            </g>
          );
        }
        const [done, rest] = split(a, c, b, 0.55);
        const g = at(a, c, b, 0.55);
        return (
          <g key={`h-${o.from}-${o.to}`} className={s.held} data-overlay="held">
            <path d={rest} className={s.heldRest} />
            <path d={done} />
            <g transform={`translate(${g.x} ${g.y})`} className={s.heldGate}><rect x="-12" y="-16" width="5" height="32" /><rect x="7" y="-16" width="5" height="32" /><rect x="-9" y="-4" width="18" height="8" /></g>
            <text x={g.x + 24} y={g.y + 6} textAnchor="start" className={s.overlayLabel}>{o.label}</text>
          </g>
        );
      })}
    </g>
  );
}

function ChartCard({ focus, topology, state, endpointRegion, onClose, pinned }: {
  focus: NonNullable<Focus>; topology: Topology; state: (id: string, g: string) => string;
  endpointRegion?: string | null; onClose: () => void; pinned: boolean;
}) {
  let x = 0, y = 0, body: React.ReactNode = null;
  if (focus.kind === "link") {
    const l = topology.links.find((k) => k.id === focus.id)!;
    const n = LAYOUT.nodes;
    const m = midpoint({ x: n[l.a]!.x, y: n[l.a]!.y }, { x: n[l.b]!.x, y: n[l.b]!.y }, LAYOUT.links[l.id]!.c);
    x = m.x; y = m.y;
    const st = state(l.id, l.group);
    body = (
      <>
        <p className={s.cardTitle}>{l.label}</p>
        <dl className={s.cardMeta}>
          <dt>Link</dt><dd><code>{l.id}</code></dd>
          <dt>Capacity</dt><dd><code>{l.cap} cu</code> (capacity units)</dd>
          <dt>Latency</dt><dd><code>{l.ms} ms</code></dd>
          <dt>Status</dt>
          <dd data-state={st}>{st === "down" ? "Failed" : "Carrying traffic"}</dd>
        </dl>
      </>
    );
  } else {
    const nd = topology.nodes.find((k) => k.id === focus.id)!;
    const p = LAYOUT.nodes[nd.id]!;
    x = p.x; y = p.y;
    const links = topology.links.filter((l) => l.a === nd.id || l.b === nd.id);
    body = (
      <>
        <p className={s.cardTitle}>{nd.label}</p>
        <dl className={s.cardMeta}>
          <dt>Kind</dt><dd>{nd.kind}</dd>
          <dt>Links</dt><dd><code>{links.map((l) => l.id).join(", ")}</code></dd>
          {endpointRegion === nd.id && (<><dt>Role</dt><dd>Current AI endpoint of the service</dd></>)}
        </dl>
      </>
    );
  }
  const left = (x / VIEW.w) * 100, top = (y / VIEW.h) * 100;
  return (
    <div className={s.card} role="status" style={{ left: `${left}%`, top: `${top}%` }} data-flip={left > 62 || undefined}>
      {body}
      <p className={s.cardNote}>Synthetic value. Controller's view: no AI role is given this.</p>
      {pinned && <button type="button" className={`btn ${s.cardClose}`} onClick={onClose}>Close</button>}
    </div>
  );
}
