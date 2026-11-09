// Cross-language exact-byte parity and fail-closed behaviour (M1-T4, M1-T5).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe as group, expect, it } from "vitest";
import { BundleSchema, type AuditRecord, type ManifestEntry } from "../../src/lib/bundle";
import { verifyBundleBytes } from "../../src/lib/loader";
import { sha256Hex, verifyChain } from "../../src/lib/verify";

const FIX = resolve(import.meta.dirname, "../fixtures");
const bytes = readFileSync(resolve(FIX, "synthetic-bundle.json"));
const expected = JSON.parse(readFileSync(resolve(FIX, "synthetic-bundle.expected.json"), "utf8"));
const bundle = BundleSchema.parse(JSON.parse(bytes.toString("utf8")));
const clone = (): AuditRecord[] => structuredClone(bundle.audit);

function entry(b: Buffer, head = expected.audit_head): ManifestEntry {
  return { bundle_id: expected.sha256.slice(0, 16), file: `${expected.sha256.slice(0, 16)}.json`, sha256: expected.sha256, mode: "offline-NOT-AI",
    label: "fixture", audit_head: head, record_count: expected.records, withheld_count: 0, source_commit: "0".repeat(40),
    generator_run_url: "local:fixture", created_at: "2026-11-02T00:00:00Z" };
}

group("exact-byte parity with Python (linkdown/audit.py serialisation)", () => {
  it("reproduces the Python head over awkward values", async () => {
    const r = await verifyChain(bundle.audit, expected.audit_head);
    expect(r.status).toBe("full");
    expect(r.checked).toBe(expected.records);
    expect(r.head).toBe(expected.audit_head);
  });
  it("hashes the file bytes like Python", async () => {
    expect(await sha256Hex(new Uint8Array(bytes))).toBe(expected.sha256);
  });
  it("the loader accepts the untouched fixture", async () => {
    const o = await verifyBundleBytes(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), entry(bytes));
    expect(o.kind).toBe("verified");
  });
});

group("fail closed", () => {
  it("a one-character change fails at that record", async () => {
    for (let k = 1; k <= bundle.audit.length; k++) {
      const recs = clone();
      recs[k - 1]!.body = recs[k - 1]!.body!.replace('"seq":', '"seq" :');
      const r = await verifyChain(recs, expected.audit_head);
      expect(r.status).toBe("failed");
      expect(r.failedAt).toBe(k);
    }
  });
  it("reordering fails", async () => {
    const recs = clone();
    [recs[2], recs[3]] = [recs[3]!, recs[2]!];
    expect((await verifyChain(recs, expected.audit_head)).failedAt).toBe(3);
  });
  it("dropping a record fails", async () => {
    const recs = clone();
    recs.splice(4, 1);
    expect((await verifyChain(recs, expected.audit_head)).failedAt).toBe(5);
  });
  it("a different head fails", async () => {
    const r = await verifyChain(bundle.audit, "f".repeat(64));
    expect(r.status).toBe("failed");
  });
  it("truncation is caught by the head", async () => {
    const r = await verifyChain(clone().slice(0, -1), expected.audit_head);
    expect(r.status).toBe("failed");
  });
  it("withheld records are never counted as verified, and the loader refuses partial bundles", async () => {
    const recs = clone();
    recs[3]!.body = null;
    recs[3]!.withheld = true;
    const r = await verifyChain(recs, expected.audit_head);
    expect(r.status).toBe("partial");
    expect(r.checked).toBe(expected.records - 1);
    const tampered = { ...bundle, audit: recs, provenance: { ...bundle.provenance, withheld_count: 1 } };
    const b = Buffer.from(JSON.stringify(tampered));
    const e = { ...entry(b), sha256: await sha256Hex(new Uint8Array(b)) };
    e.bundle_id = e.sha256.slice(0, 16);
    e.file = `${e.bundle_id}.json`;
    const o = await verifyBundleBytes(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), e);
    expect(o.kind).toBe("refused");
  });
  it("a file that does not match its listed sha256 is refused", async () => {
    const b = Buffer.from(bytes);
    b[b.length - 2] = b[b.length - 2] === 0x7d ? 0x7d : 0x20;
    const o = await verifyBundleBytes(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength),
      { ...entry(b), sha256: "0".repeat(64) });
    expect(o.kind).toBe("refused");
  });
  it("a prompt field inside a hashed body is refused", async () => {
    const recs = clone();
    const body = JSON.parse(recs[8]!.body!);
    body.payload.user = "leaked prompt";
    recs[8]!.body = JSON.stringify(body);
    recs[8]!.hash = await sha256Hex(recs[8]!.prev + recs[8]!.body);
    const r = await verifyChain(recs, recs[8]!.hash);
    expect(r.status).toBe("failed");
    expect(r.problems.join(" ")).toMatch(/forbidden/);
  });
});
