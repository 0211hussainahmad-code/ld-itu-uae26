// The replay model is derived only from the verified committed bundle (exact project data).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { BundleSchema, ManifestSchema } from "../../src/lib/bundle";
import { buildReplay, roleViewFor, trafficScope, VIEW_KEYS } from "../../src/lib/replay";
import { LAYOUT } from "../../src/lib/layout";

const DIR = resolve(import.meta.dirname, "../../../data/bundles");
const manifest = ManifestSchema.parse(JSON.parse(readFileSync(resolve(DIR, "manifest.json"), "utf8")));
const entry = manifest.bundles[0]!;
const bundle = BundleSchema.parse(JSON.parse(readFileSync(resolve(DIR, entry.file), "utf8")));
const r = buildReplay(bundle);

it("finds the three scenario events in chain order", () => {
  expect(r.events.map((e) => e.id)).toEqual(["E1", "E2", "E3"]);
  expect(r.events.map((e) => e.at_min)).toEqual([0, 120, 1440]);
  expect(r.events[0]!.stepIndex).toBeLessThan(r.events[1]!.stepIndex);
});

it("every step is a hashed record, in order, and none is invented", () => {
  const seqs = r.steps.map((s) => s.seq);
  expect([...seqs].sort((a, b) => a - b)).toEqual(seqs);
  for (const s of r.steps) expect(r.records.find((x) => x.seq === s.seq)?.kind).toBe(s.kind);
  expect(r.steps.some((s) => s.kind === "AGENT_TURN" || s.kind === "DEMO_TURN")).toBe(false);
});

it("network state follows the records", () => {
  const e1 = r.stateAt(r.events[0]!.stepIndex);
  expect(e1.linksDown).toEqual(["W1", "W2"]);
  expect(e1.trafficFrom?.eventId).toBe("E1");
  expect(r.stateAt(0).linksDown).toEqual([]);
  expect(r.stateAt(0).traffic).toBeNull();
  expect(r.initialEndpoint).toBe("eu_west");
  const last = r.stateAt(r.steps.length - 1);
  expect(last.endpointRegion).toBe("uae_central");
  expect(last.trafficFrom?.eventId).toBe("E3");
  expect(r.recordsMoved).toBe(false);
  expect(r.recordsRegion).toBe("uae_central");
});

it("decisions are joined to the turn and the follow-up records", () => {
  expect(r.decisions).toHaveLength(r.metrics.proposals);
  const transfer = r.decisions.find((d) => d.tool === "transfer_records")!;
  expect(transfer.outcome).toBe("INSUFFICIENT_AUTHORITY_OR_EVIDENCE");
  expect(transfer.followUps.find((f) => f.kind === "HUMAN_DECISION")?.payload.approved).toBe(false);
  const sw = r.decisions.find((d) => d.tool === "switch_ai_endpoint")!;
  expect(sw.followUps.some((f) => f.kind === "STATE_CHANGE")).toBe(true);
  const counts = { PERMITTED: 0, PROHIBITED: 0, INSUFFICIENT_AUTHORITY_OR_EVIDENCE: 0 };
  r.decisions.forEach((d) => counts[d.outcome]++);
  expect(counts).toEqual(r.metrics.by_outcome);
});

it("flags the scripted invented citation", () => {
  const flagged = r.steps.filter((s) => s.warnings.some((w) => w.includes("made-up#c999")));
  expect(flagged.length).toBeGreaterThan(0);
  expect(bundle.sources["made-up#c999"]?.known ?? false).toBe(false);   // absent or unknown: shown as invented
});

it("role views are exactly the build_view keys each role receives", () => {
  const byId = Object.fromEntries(r.roles.map((x) => [x.id, x]));
  const keys = (id: string) => [...roleViewFor(byId[id]!)].sort();
  expect(keys("operator")).toEqual(["capacity", "links", "traffic"]);
  expect(keys("service")).toEqual(["endpoints", "record_sets", "service", "service_traffic"]);
  expect(keys("regulator")).toEqual(["demand_classes"]);
  expect(keys("adviser")).toEqual([]);
  expect(trafficScope(roleViewFor(byId.operator!))).toBe("all");
  expect(trafficScope(roleViewFor(byId.service!))).toBe("gov_ai");
  expect(trafficScope(roleViewFor(byId.regulator!))).toBe("names");
  expect(trafficScope(roleViewFor(byId.adviser!))).toBe("none");
  expect(trafficScope("controller")).toBe("all");
  // Exactly the eight build_view keys: none of them is the topology graph, per-link capacity or latency.
  expect([...VIEW_KEYS].sort()).toEqual(["capacity", "demand_classes", "endpoints", "links", "record_sets", "service", "service_traffic", "traffic"]);
});

it("the chart layout covers every node and link of the bundle topology", () => {
  for (const n of r.topology.nodes) expect(LAYOUT.nodes[n.id], n.id).toBeDefined();
  for (const l of r.topology.links) expect(LAYOUT.links[l.id], l.id).toBeDefined();
  expect(r.topology.nodes).toHaveLength(6);
  expect(r.topology.links).toHaveLength(10);
});

it("links gap observations and information requests to their decisions (no false 'nothing carried out')", async () => {
  const gaps = r.decisions.filter((d) => d.tool === "record_gap_observation");
  expect(gaps.length).toBeGreaterThan(0);
  for (const d of gaps) expect(d.followUps.some((f) => f.kind === "GAP_OBSERVATION" && f.payload.gap_id === d.args.gap_id)).toBe(true);
  const req = r.decisions.filter((d) => d.tool === "request_information");
  for (const d of req) expect(d.followUps.some((f) => f.kind === "MESSAGE")).toBe(true);
});

it("only https URLs become links, and delivery titles read naturally", async () => {
  const { safeHttpsUrl } = await import("../../src/lib/replay");
  expect(safeHttpsUrl("https://example.org/a")).toBe("https://example.org/a");
  expect(safeHttpsUrl("javascript:alert(1)")).toBeNull();
  expect(safeHttpsUrl("http://example.org")).toBeNull();
  expect(safeHttpsUrl(42)).toBeNull();
  expect(r.steps.some((s) => s.title.includes("receives an alarm"))).toBe(true);
  expect(r.steps.some((s) => / a alarm| a external/.test(s.title))).toBe(false);
});

it("service settings are reconstructed per step, not from the final values", () => {
  const first = r.stateAt(0), last = r.stateAt(r.steps.length - 1);
  expect(first.recordsRegion).toBe(r.metrics.final_service.records_region);   // no transfer in this run
  expect(last.serviceMode).toBe(r.metrics.final_service.mode);
  expect(first.endpointRegion).toBe(r.initialEndpoint);
  // A synthetic records transfer part-way through must not show before it happens (parsing only; no chain check).
  const audit = bundle.audit.map((x) => ({ ...x }));
  const at = Math.floor(audit.length / 2);
  const b = JSON.parse(audit[at]!.body as string);
  audit[at] = { ...audit[at]!, kind: "STATE_CHANGE", body: JSON.stringify({ ...b, kind: "STATE_CHANGE",
    payload: { tool: "transfer_records", change: { changed: "record_sets.case_files.region", from: "uae_central", to: "eu_west" } } }) };
  const r2 = buildReplay({ ...bundle, audit } as typeof bundle);
  const changeStep = r2.steps.findIndex((st) => st.seq === b.seq);
  expect(changeStep).toBeGreaterThan(0);
  expect(r2.stateAt(changeStep - 1).recordsRegion).toBe("uae_central");
  expect(r2.stateAt(changeStep).recordsRegion).toBe("eu_west");
  expect(r2.stateAt(r2.steps.length - 1).recordsRegion).toBe("eu_west");
});

describe("notGivenFor (M3 role chapters)", () => {
  it("never lists data a role already receives, including data contained in every-class traffic", async () => {
    const { buildReplay, notGivenFor, roleViewFor } = await import("../../src/lib/replay");
    const { readFileSync } = await import("node:fs");
    const { resolve } = await import("node:path");
    const dir = resolve(import.meta.dirname, "../../../data/bundles");
    const manifest = JSON.parse(readFileSync(resolve(dir, "manifest.json"), "utf8"));
    const bundle = JSON.parse(readFileSync(resolve(dir, manifest.bundles[0].file), "utf8"));
    const r = buildReplay(bundle);
    for (const role of r.roles) {
      const given = roleViewFor(role);
      for (const k of notGivenFor(role)) expect(given.has(k)).toBe(false);
    }
    const op = r.roles.find((x) => x.id === "operator")!;
    expect(notGivenFor(op)).not.toContain("service_traffic");
    expect(notGivenFor(op)).not.toContain("demand_classes");
    const adv = r.roles.find((x) => x.id === "adviser")!;
    expect(notGivenFor(adv).length).toBe(8);
  });
});
