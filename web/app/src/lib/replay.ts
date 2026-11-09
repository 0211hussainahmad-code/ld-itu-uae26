// Replay model derived ONLY from a verified bundle: hashed audit record bodies plus the bundle's
// fingerprinted context (topology, roles, scenario). Nothing here invents values: every state shown at
// a step is the latest value an audit record states, labelled with where it came from.
import type { Bundle } from "./bundle";
import VISIBILITY from "./role-visibility.json";

export type Health = "OK" | "DEGRADED" | "DOWN";
export type Outcome = "PERMITTED" | "PROHIBITED" | "INSUFFICIENT_AUTHORITY_OR_EVIDENCE";
export const ROLE_IDS = ["operator", "service", "regulator", "adviser"] as const;
export type RoleId = (typeof ROLE_IDS)[number];

export interface AuditRec {
  seq: number;
  kind: string;
  actor: string;
  sim_min: number | null;
  payload: Record<string, any>;
  [meta: string]: unknown;
}

export interface TopoNode { id: string; label: string; kind: string; in_uae?: boolean }
export interface TopoLink { id: string; a: string; b: string; cap: number; ms: number; group: string; label: string }
export interface Demand { id: string; label: string; dest: string; cu: number }
export interface Topology { nodes: TopoNode[]; links: TopoLink[]; demand: Demand[] }
export interface RoleInfo { id: RoleId; title: string; sees: string[]; tools: string[] }
export interface ScenarioEvent { id: string; at_min: number; title: string; effect: { fail_links?: string[] } }

export interface TrafficClass { dest: string; delivered: number; demand: number; share: number; avg_ms: number; health: Health }

export interface Step {
  index: number;
  seq: number;
  kind: string;
  actor: string;
  simMin: number;
  eventId: string | null;
  title: string;
  detail: string;
  role: RoleId | null;
  decision?: Decision;
  warnings: string[];
}

export interface Decision {
  seq: number;
  role: RoleId;
  tool: string;
  args: Record<string, unknown>;
  why: string;
  cites: string[];
  outcome: Outcome;
  requiresHuman: boolean;
  approval: string;
  legalStatus: string;
  facts: Record<string, unknown>;
  conditions: string[];
  trail: Array<Record<string, any>>;
  summary: string;
  actionId: string;
  stateDigest: string;
  turn: { seq: number; unsupported: string[]; notes: string[]; retrieved: string[]; model: string | null; isAi: boolean | null } | null;
  followUps: AuditRec[];
}

export interface NetState {
  simMin: number;
  eventId: string | null;
  linksDown: string[];
  traffic: Record<string, TrafficClass> | null;
  trafficFrom: { eventId: string; seq: number; simMin: number } | null;
  endpointRegion: string | null;
  endpointChangedAt: number | null;
  recordsRegion: string | null;   // where the service's case files are at this step
  serviceMode: string | null;     // the service mode at this step
}

export interface Replay {
  records: AuditRec[];
  steps: Step[];
  events: Array<ScenarioEvent & { stepIndex: number; seq: number }>;
  topology: Topology;
  roles: RoleInfo[];
  decisions: Decision[];
  initialEndpoint: string | null;
  recordsRegion: string | null;
  recordsMoved: boolean;
  metrics: Record<string, any>;
  stateAt(stepIndex: number): NetState;
}

const STEP_KINDS = new Set([
  "RUN_START", "EVENT", "DELIVERY", "TURN_PARSED", "MESSAGE", "GATE_DECISION", "HUMAN_DECISION",
  "STATE_CHANGE", "ACTION_RESULT", "DUPLICATE_ACTION", "STALE_APPROVAL", "GAP_OBSERVATION", "RUN_END",
]);

export const DELIVERY_NAMES: Record<string, string> = {
  alarm: "alarm",
  service_monitor: "service-monitor alert",
  public_signal: "public signal",
  external_notice: "external notice",
};

export const ROLE_NAMES: Record<RoleId, string> = {
  operator: "Network operator",
  service: "Government AI service",
  regulator: "Regulator",
  adviser: "Policy and legal adviser",
};

export const TOOL_NAMES: Record<string, string> = {
  reroute_traffic: "re-route traffic",
  apply_operator_qos: "apply quality of service",
  send_message: "send a message",
  set_service_mode: "change service mode",
  switch_ai_endpoint: "switch the AI endpoint",
  transfer_records: "transfer case files",
  request_information: "request information",
  recommend_priority_plan: "recommend a priority plan",
  issue_priority_order: "issue a binding priority order",
  record_gap_observation: "record a gap observation",
};

export const OUTCOME_NAMES: Record<Outcome, string> = {
  PERMITTED: "Permitted",
  PROHIBITED: "Prohibited",
  INSUFFICIENT_AUTHORITY_OR_EVIDENCE: "Needs a competent authority",
};

export const LEGAL_STATUS_NAMES: Record<string, string> = {
  NOT_ASSESSED: "Exercise rule only. Legal status not assessed.",
  UNVERIFIED_OR_INSUFFICIENT: "The legal source is not verified, so the gate does not decide: it escalates to a competent authority (in this run, a simulated controller).",
  VERIFIED_PROHIBITED: "Prohibited by a verified legal source.",
  VERIFIED_PERMITTED: "Permitted by a verified legal source.",
};

const isRole = (x: unknown): x is RoleId => typeof x === "string" && (ROLE_IDS as readonly string[]).includes(x);
const toolName = (t: unknown) => (typeof t === "string" ? TOOL_NAMES[t] ?? t.replaceAll("_", " ") : "act");
const regionName = (topo: Topology, id: unknown) =>
  typeof id === "string" ? (topo.nodes.find((n) => n.id === id)?.label.replace(/\s*\(synthetic\)/, "") ?? id) : "unknown";

export function parseRecords(bundle: Bundle): AuditRec[] {
  return bundle.audit.map((r) => JSON.parse(r.body as string) as AuditRec);
}

export function buildReplay(bundle: Bundle): Replay {
  const records = parseRecords(bundle);
  const ctx = bundle.context;
  const topoData = ctx.topology.data as any;
  const topology: Topology = {
    nodes: Object.entries(topoData.nodes as Record<string, any>).map(([id, n]) => ({ id, ...n })),
    links: topoData.links,
    demand: topoData.demand,
  };
  const rolesData = (ctx.roles.data as any).roles as Record<string, any>;
  const roles: RoleInfo[] = ROLE_IDS.map((id) => ({ id, title: rolesData[id].title, sees: rolesData[id].sees ?? [], tools: rolesData[id].tools ?? [] }));
  const scenarioEvents = ((ctx.scenario.data as any).events ?? []) as ScenarioEvent[];

  // Decisions, joined to the turn that proposed them and the records that followed.
  const decisions: Decision[] = [];
  let lastTurnByRole: Partial<Record<RoleId, Decision["turn"]>> = {};
  let lastAgentTurn: AuditRec | null = null;
  records.forEach((r, i) => {
    if (r.kind === "AGENT_TURN") lastAgentTurn = r;
    if (r.kind === "TURN_PARSED" && isRole(r.actor)) {
      const at = lastAgentTurn && lastAgentTurn.actor === r.actor ? lastAgentTurn : null;
      lastTurnByRole[r.actor] = {
        seq: r.seq,
        unsupported: r.payload.unsupported_citations ?? [],
        notes: r.payload.analyst_note_citations ?? [],
        retrieved: (at?.payload.retrieved as string[]) ?? [],
        model: (at?.model as string) ?? null,
        isAi: (at?.is_ai as boolean) ?? null,
      };
    }
    if (r.kind === "GATE_DECISION") {
      const p = r.payload;
      const followUps: AuditRec[] = [];
      for (let j = i + 1; j < records.length; j++) {
        const f = records[j]!;
        if (f.kind === "GATE_DECISION" || f.kind === "TURN_PARSED" || f.kind === "EVENT") break;
        if (f.payload?.action_id === p.action_id) followUps.push(f);
        else if (f.kind === "GAP_OBSERVATION" && f.actor === p.role && p.tool === "record_gap_observation"
          && f.payload?.gap_id === p.args?.gap_id) followUps.push(f);
        else if (f.kind === "MESSAGE" && f.actor === p.role && p.tool === "request_information"
          && String(f.payload?.text ?? "").startsWith("INFORMATION REQUEST:")) followUps.push(f);
      }
      decisions.push({
        seq: r.seq, role: p.role, tool: p.tool, args: p.args ?? {}, why: p.why ?? "", cites: p.cites ?? [],
        outcome: p.outcome, requiresHuman: !!p.requires_human, approval: p.approval, legalStatus: p.legal_status,
        facts: p.facts ?? {}, conditions: p.conditions ?? [], trail: p.trail ?? [], summary: p.summary ?? "",
        actionId: p.action_id, stateDigest: p.state_digest, turn: lastTurnByRole[p.role as RoleId] ?? null, followUps,
      });
    }
  });
  const decisionBySeq = new Map(decisions.map((d) => [d.seq, d]));

  const firstEndpointChange = records.find((r) => r.kind === "STATE_CHANGE" && r.payload.change?.changed === "service.endpoint_region");
  const end = records.find((r) => r.kind === "RUN_END");
  const metrics = (end?.payload.metrics ?? {}) as Record<string, any>;
  const initialEndpoint = (firstEndpointChange?.payload.change?.from as string) ?? metrics.final_service?.endpoint_region ?? null;
  const recordsMoved = records.some((r) => r.kind === "STATE_CHANGE" && r.payload.tool === "transfer_records");
  // Values at the start of the run: the "from" of the first change, else the final value (never changed).
  const isRecordsChange = (r: AuditRec) => r.kind === "STATE_CHANGE" && r.payload.tool === "transfer_records" && String(r.payload.change?.changed ?? "").startsWith("record_sets.");
  const isModeChange = (r: AuditRec) => r.kind === "STATE_CHANGE" && r.payload.change?.changed === "service.mode";
  const initialRecords = (records.find(isRecordsChange)?.payload.change?.from as string) ?? metrics.final_service?.records_region ?? null;
  const initialMode = (records.find(isModeChange)?.payload.change?.from as string) ?? metrics.final_service?.mode ?? null;

  // Steps: one per meaningful record, in chain order.
  const steps: Step[] = [];
  let eventId: string | null = null;
  for (const r of records) {
    if (r.kind === "EVENT") eventId = r.payload.id;
    if (!STEP_KINDS.has(r.kind)) continue;
    const role = isRole(r.actor) ? r.actor : isRole(r.payload?.role) ? r.payload.role : isRole(r.payload?.to) ? r.payload.to : null;
    const s: Step = { index: steps.length, seq: r.seq, kind: r.kind, actor: r.actor, simMin: r.sim_min ?? 0, eventId, title: "", detail: "", role, warnings: [] };
    describeStep(s, r, topology, scenarioEvents, decisionBySeq.get(r.seq));
    steps.push(s);
  }
  const events = scenarioEvents.map((e) => {
    const st = steps.find((s) => s.kind === "EVENT" && s.eventId === e.id);
    return { ...e, stepIndex: st?.index ?? 0, seq: st?.seq ?? 0 };
  });

  // Network state by step (cumulative over records up to the step's sequence number).
  const cache = new Map<number, NetState>();
  function stateAt(stepIndex: number): NetState {
    const idx = Math.max(0, Math.min(stepIndex, steps.length - 1));
    const hit = cache.get(idx);
    if (hit) return hit;
    const upto = steps[idx]?.seq ?? 0;
    const down = new Set<string>();
    let traffic: NetState["traffic"] = null;
    let trafficFrom: NetState["trafficFrom"] = null;
    let endpoint = initialEndpoint;
    let changedAt: number | null = null;
    let recordsAt = initialRecords;
    let mode = initialMode;
    let ev: string | null = null;
    let simMin = 0;
    for (const r of records) {
      if (r.seq > upto) break;
      simMin = r.sim_min ?? simMin;
      if (r.kind === "EVENT") {
        ev = r.payload.id;
        for (const l of r.payload.effect?.fail_links ?? []) down.add(l);
        if (r.payload.traffic) {
          traffic = r.payload.traffic;
          trafficFrom = { eventId: r.payload.id, seq: r.seq, simMin: r.sim_min ?? 0 };
        }
      }
      if (r.kind === "STATE_CHANGE" && r.payload.change?.changed === "service.endpoint_region") {
        endpoint = r.payload.change.to;
        changedAt = r.seq;
      }
      if (isRecordsChange(r)) recordsAt = r.payload.change.to;
      if (isModeChange(r)) mode = r.payload.change.to;
    }
    const st: NetState = { simMin, eventId: ev, linksDown: [...down].sort(), traffic, trafficFrom, endpointRegion: endpoint, endpointChangedAt: changedAt, recordsRegion: recordsAt, serviceMode: mode };
    cache.set(idx, st);
    return st;
  }

  return {
    records, steps, events, topology, roles, decisions, initialEndpoint,
    recordsRegion: metrics.final_service?.records_region ?? null, recordsMoved, metrics, stateAt,
  };

  function describeStep(s: Step, r: AuditRec, topo: Topology, evs: ScenarioEvent[], d?: Decision) {
    const p = r.payload ?? {};
    const who = s.role ? ROLE_NAMES[s.role] : r.actor;
    switch (r.kind) {
      case "RUN_START":
        s.title = "The exercise starts";
        s.detail = `Scenario ${p.scenario} (${p.scenario_version}). Every role is played by a scripted client labelled ${p.model}; human decisions use the ${p.human} policy.`;
        break;
      case "EVENT": {
        const e = evs.find((x) => x.id === p.id);
        const fail: string[] = p.effect?.fail_links ?? [];
        s.title = `Event ${String(p.id).replace(/^E/, "")}: ${e?.title ?? p.title}`;
        s.detail = fail.length
          ? `${fail.map((id) => topo.links.find((l) => l.id === id)?.label ?? id).join(" and ")} stop carrying traffic.`
          : "No further links fail. The outage continues.";
        break;
      }
      case "DELIVERY":
        s.title = `${who} receives ${withArticle(DELIVERY_NAMES[p.kind] ?? String(p.kind).replaceAll("_", " "))}`;
        s.detail = p.text ?? "";
        break;
      case "TURN_PARSED":
        s.title = `${who} assesses the situation`;
        s.detail = p.assessment ?? "";
        if ((p.unsupported_citations ?? []).length) s.warnings.push(`Cites ${p.unsupported_citations.join(", ")}, which was not among the passages retrieved for this turn.`);
        if ((p.unverified_legal_wording ?? []).length) s.warnings.push("Uses legal wording without a verified source.");
        if ((p.malformed ?? []).length) s.warnings.push("Part of the reply was malformed and ignored.");
        break;
      case "MESSAGE":
        s.title = `${who} messages ${p.to === "ALL" ? "all roles" : isRole(p.to) ? ROLE_NAMES[p.to] : p.to}`;
        s.detail = p.text ?? "";
        break;
      case "GATE_DECISION":
        s.title = `${who} proposes to ${toolName(p.tool)}`;
        s.detail = plainDecision(p.outcome, p.legal_status, p.requires_human, p.trail ?? []);
        s.decision = d;
        break;
      case "HUMAN_DECISION":
        // "rejects" would read as a judgement; the simulated controller's own record says it never decides authority.
        s.title = `The ${String(r.actor).startsWith("simulated") ? "simulated" : "human"} controller ${p.approved ? "approves" : /never decide authority/.test(String(p.reason ?? "")) ? "does not approve, by policy" : "rejects"}: ${toolName(p.tool)}`;
        s.detail = [p.label, p.reason].filter(Boolean).join(". ");
        s.role = isRole(p.role) ? p.role : s.role;
        break;
      case "STATE_CHANGE":
        s.title = p.change?.changed === "service.endpoint_region"
          ? `The service now uses ${regionName(topo, p.change.to)}`
          : `State changes: ${p.change?.changed}`;
        s.detail = p.change?.changed === "service.endpoint_region"
          ? `The AI endpoint moves from ${regionName(topo, p.change.from)} to ${regionName(topo, p.change.to)} after the gate permitted it.`
          : JSON.stringify(p.change);
        break;
      case "ACTION_RESULT": {
        // "Carried out" only when the record shows the network state changed; a recorded-only result says so.
        const recordOnly = p.executed === true && (p.change?.recorded === true || p.change?.changed == null);
        s.title = recordOnly ? `Recorded only: ${toolName(p.tool)}` : p.executed === true ? `Carried out: ${toolName(p.tool)}` : `Not carried out: ${toolName(p.tool)}`;
        s.detail = `${p.change?.note ?? p.change?.error ?? (p.change?.changed ? `Changed ${p.change.changed}.` : "Recorded.")}${recordOnly ? ". Nothing in the network changed." : ""}`;
        break;
      }
        break;
      case "DUPLICATE_ACTION":
        s.title = `Repeated proposal not carried out again: ${toolName(p.tool)}`;
        s.detail = "The same action was already handled, so the orchestrator does not execute it twice.";
        break;
      case "STALE_APPROVAL":
        s.title = "An approval expired because the state changed";
        s.detail = "Approvals are bound to the state they were given in.";
        break;
      case "GAP_OBSERVATION":
        s.title = `The adviser drafts gap observation ${p.gap_id}`;
        s.detail = `${p.wording ?? ""} Status: ${p.review_status ?? p.status ?? "draft"}.`;
        break;
      case "RUN_END":
        s.title = "The exercise ends";
        s.detail = `${metrics_line(p.metrics, effectCounts(records))}`;
        break;
    }
  }
}

function metrics_line(m: any, e: { changed: number; recordOnly: number }): string {
  if (!m) return "";
  return `${m.proposals} proposals: ${m.by_outcome?.PERMITTED ?? 0} permitted, ${m.by_outcome?.PROHIBITED ?? 0} prohibited, `
    + `${m.by_outcome?.INSUFFICIENT_AUTHORITY_OR_EVIDENCE ?? 0} escalated. ${m.executed} executed: ${e.changed} changed the exercise state, `
    + `${e.recordOnly} recorded only. ${m.unsafe_executed} prohibited proposals carried out.`;
}

/** What executed actions did, from the records: changed the exercise state, or were only recorded. */
export function effectCounts(records: Array<{ kind: string; payload: any }>) {
  const changed = records.filter((r) => r.kind === "STATE_CHANGE").length;
  const recordOnly = records.filter((r) => r.kind === "ACTION_RESULT" && r.payload?.executed === true
    && (r.payload?.change?.recorded === true || r.payload?.change?.changed == null)).length;
  return { changed, recordOnly };
}

// What each role is given, mirroring linkdown/agents.py build_view() (see role-visibility.json).

export type ViewKey = "links" | "capacity" | "traffic" | "service" | "service_traffic" | "endpoints" | "demand_classes" | "record_sets";
export const VIEW_KEYS = Object.keys(VISIBILITY).filter((k) => !k.startsWith("_")) as ViewKey[];
export const SEES_NAMES: Record<string, string> = Object.fromEntries(VIEW_KEYS.map((k) => [k, (VISIBILITY as any)[k].label]));
export const SHOWN_IN_RECORD: Record<string, boolean> = Object.fromEntries(VIEW_KEYS.map((k) => [k, (VISIBILITY as any)[k].shown]));

/** The keys of build_view() this role receives. Unknown keys in a role's `sees` are ignored, as build_view ignores them. */
export function roleViewFor(role: RoleInfo): Set<ViewKey> {
  return new Set(role.sees.filter((k): k is ViewKey => (VIEW_KEYS as string[]).includes(k)));
}

/** View keys a role does not receive. A key already contained in one it does receive is not listed:
 *  every-class traffic contains the AI service's traffic and the class names. */
export function notGivenFor(role: RoleInfo): ViewKey[] {
  const v = roleViewFor(role);
  const contained = new Set<ViewKey>(v.has("traffic") ? ["service_traffic", "demand_classes"] : []);
  return VIEW_KEYS.filter((k) => !v.has(k) && !contained.has(k));
}

/** Which traffic figures a role receives: all classes, the AI service only, class names only, or nothing. */
export type TrafficScope = "all" | "gov_ai" | "names" | "none";
export function trafficScope(view: Set<ViewKey> | "controller"): TrafficScope {
  if (view === "controller") return "all";
  return view.has("traffic") ? "all" : view.has("service_traffic") ? "gov_ai" : view.has("demand_classes") ? "names" : "none";
}

/** Small counts in words, for sentences built from the record. */
export function countWord(n: number): string {
  return ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"][n] ?? String(n);
}

export function formatSimTime(min: number): string {
  if (min < 60) return `T+${min} min`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `T+${h} h ${m} min` : `T+${h} h`;
}

/** Only https links from bundle data become hrefs. */
export function safeHttpsUrl(u: unknown): string | null {
  if (typeof u !== "string") return null;
  try { const url = new URL(u); return url.protocol === "https:" ? url.href : null; } catch { return null; }
}

/** English indefinite article for a lowercase noun phrase. */
export function withArticle(phrase: string): string {
  return /^[aeiou]/i.test(phrase) ? `an ${phrase}` : `a ${phrase}`;
}

export const KIND_NAMES: Record<string, string> = {
  RUN_START: "Start", EVENT: "Event", DELIVERY: "Message from the scenario", AGENT_TURN: "Turn (metadata)",
  TURN_PARSED: "Assessment", DEMO_TURN: "Turn check", MESSAGE: "Message", GATE_DECISION: "Gate decision",
  HUMAN_DECISION: "Controller decision", STATE_CHANGE: "State change", ACTION_RESULT: "Action",
  DUPLICATE_ACTION: "Repeat", STALE_APPROVAL: "Expired approval", GAP_OBSERVATION: "Gap observation", RUN_END: "End",
};

/** One plain-language sentence for a gate decision (derived only from the decision's own fields). */
export function plainDecision(outcome: string, legalStatus: string, requiresHuman: boolean, trail: Array<Record<string, any>>): string {
  const downgraded = trail.some((t) => t.downgraded);
  if (outcome === "PERMITTED") return requiresHuman ? "Allowed by the rules, but it still needs a human sign-off." : "Allowed: it is within this role's mandate.";
  if (outcome === "PROHIBITED") return "Not allowed: a verified rule forbids it, and no human can override that.";
  if (downgraded) return "Not decided by the gate: a rule would forbid it, but that rule's legal source is not verified, so a competent authority has to decide.";
  if (legalStatus === "UNVERIFIED_OR_INSUFFICIENT") return "Not decided by the gate: the evidence is not enough, so a competent authority has to decide.";
  return "Not decided by the gate: this role does not have the authority on its own, so a competent authority has to decide.";
}
