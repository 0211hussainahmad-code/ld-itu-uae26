// Exact-byte audit-chain verification in the browser (WebCrypto SHA-256).
//
// For every published record: sha256(UTF-8(prev + body)) must equal hash, where body is the
// exact canonical string linkdown/audit.py hashed. Linkage prev[i] == hash[i-1] with a genesis
// of 64 zeros. Withheld records can be linked but never rehashed, so they never count as
// verified. Any failure is final (fail closed).
import { findForbidden, type AuditRecord } from "./bundle";

export const GENESIS = "0".repeat(64);

export type VerifyStatus = "full" | "partial" | "failed";

export interface VerifyResult {
  status: VerifyStatus;
  failedAt: number | null;
  checked: number;
  total: number;
  withheld: number;
  head: string | null;
  problems: string[];
}

const encoder = new TextEncoder();

export async function sha256Hex(data: string | ArrayBuffer | Uint8Array): Promise<string> {
  const bytes = typeof data === "string" ? encoder.encode(data) : data instanceof Uint8Array ? data : new Uint8Array(data);
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

function fail(r: VerifyResult, msg: string, seq: number | null = null): VerifyResult {
  r.status = "failed";
  if (seq !== null && r.failedAt === null) r.failedAt = seq;
  r.problems.push(msg);
  return r;
}

export async function verifyChain(
  records: AuditRecord[],
  expectedHead: string | null,
  onProgress?: (done: number, total: number) => void,
): Promise<VerifyResult> {
  const r: VerifyResult = { status: "failed", failedAt: null, checked: 0, total: records.length, withheld: 0, head: null, problems: [] };
  let prev = GENESIS;
  for (let i = 0; i < records.length; i++) {
    const seq = i + 1;
    const rec = records[i]!;
    if (rec.seq !== seq) return fail(r, `record #${seq}: out of sequence (found ${rec.seq})`, seq);
    if (rec.prev !== prev) return fail(r, `record #${seq}: broken link to the previous record`, seq);
    if (rec.withheld) {
      r.withheld += 1;
    } else {
      if (typeof rec.body !== "string") return fail(r, `record #${seq}: missing canonical body`, seq);
      if ((await sha256Hex(prev + rec.body)) !== rec.hash) return fail(r, `record #${seq}: content does not match its hash`, seq);
      let parsed: { seq?: unknown; kind?: unknown; actor?: unknown };
      try {
        parsed = JSON.parse(rec.body);
      } catch {
        return fail(r, `record #${seq}: body is not JSON`, seq);
      }
      if (parsed.seq !== seq || parsed.kind !== rec.kind || parsed.actor !== rec.actor) {
        return fail(r, `record #${seq}: envelope differs from the hashed body`, seq);
      }
      const bad = findForbidden(parsed);
      if (bad.length) return fail(r, `record #${seq}: forbidden fields ${bad.join(", ")}`, seq);
      r.checked += 1;
    }
    prev = rec.hash;
    onProgress?.(seq, records.length);
  }
  r.head = prev;
  if (expectedHead === null) return fail(r, "no head to compare with");
  if (prev !== expectedHead) return fail(r, "computed head differs from the expected head");
  r.status = r.withheld > 0 ? "partial" : "full";
  return r;
}

export function describe(r: VerifyResult): string {
  if (r.status === "full") return `Fully rehashed in your browser: ${r.checked} of ${r.total} records.`;
  if (r.status === "partial") {
    return `Partially verified: ${r.checked} of ${r.total} records rehashed; ${r.withheld} withheld and not checkable by you. Not a complete verification.`;
  }
  const where = r.failedAt ? ` at record #${r.failedAt}` : "";
  return `Verification failed${where}. ${r.problems.join(" ")}`;
}
