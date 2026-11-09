// Fail-closed replay loader: manifest -> exact bundle bytes -> sha256 -> schema -> chain -> head.
// A bundle is renderable only when verification is "full". Partial bundles are refused in
// Phase 1 (publication of withheld records is not approved).
import { BundleSchema, ManifestSchema, type Bundle, type Manifest, type ManifestEntry } from "./bundle";
import { sha256Hex, verifyChain, type VerifyResult } from "./verify";

export type LoadOutcome =
  | { kind: "empty" }
  | { kind: "verified"; entry: ManifestEntry; bundle: Bundle; result: VerifyResult }
  | { kind: "refused"; entry: ManifestEntry | null; result: VerifyResult | null; reason: string }
  | { kind: "error"; reason: string };

type Fetcher = (url: string) => Promise<Response>;

export async function loadManifest(fetcher: Fetcher = fetch): Promise<Manifest | null> {
  const res = await fetcher("/bundles/manifest.json");
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`The bundle list could not be loaded (HTTP ${res.status}).`);
  let json: unknown;
  try {
    json = await res.json();
  } catch {
    throw new Error("The bundle list is not valid JSON, so no replay is shown.");
  }
  const parsed = ManifestSchema.safeParse(json);
  if (!parsed.success) throw new Error("The bundle list is malformed.");
  return parsed.data;
}

export async function verifyBundleBytes(bytes: ArrayBuffer, entry: ManifestEntry,
  onProgress?: (done: number, total: number) => void): Promise<LoadOutcome> {
  if (entry.file !== `${entry.bundle_id}.json`) {
    return { kind: "refused", entry, result: null, reason: "The bundle list entry names an unexpected file." };
  }
  if (entry.mode !== "offline-NOT-AI") {
    // Phase 1: the site's labels describe scripted runs. Live bundles need their own labelling first.
    return { kind: "refused", entry, result: null, reason: "Live-run bundles are not enabled on this site yet." };
  }
  const digest = await sha256Hex(bytes);
  if (digest !== entry.sha256 || digest.slice(0, 16) !== entry.bundle_id) {
    return { kind: "refused", entry, result: null, reason: "The bundle file does not match its listed sha256." };
  }
  let json: unknown;
  try {
    json = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    return { kind: "refused", entry, result: null, reason: "The bundle is not valid UTF-8 JSON." };
  }
  const parsed = BundleSchema.safeParse(json);
  if (!parsed.success) return { kind: "refused", entry, result: null, reason: "The bundle does not match the published schema." };
  const bundle = parsed.data;
  const pv = bundle.provenance;
  if (pv.audit_head !== entry.audit_head || pv.mode !== entry.mode) {
    return { kind: "refused", entry, result: null, reason: "The bundle and its list entry disagree." };
  }
  const result = await verifyChain(bundle.audit, entry.audit_head, onProgress);
  if (result.status !== "full") {
    return { kind: "refused", entry, result, reason: result.status === "partial"
      ? "Some records are withheld, so this replay cannot be fully verified and is not shown."
      : "The audit chain did not verify, so this replay is not shown." };
  }
  if (pv.record_count !== result.total || pv.withheld_count !== result.withheld) {
    return { kind: "refused", entry, result, reason: "Record counts differ from the bundle's provenance." };
  }
  const start = JSON.parse(bundle.audit[0]!.body!) as { kind?: string; payload?: { model?: string; is_ai?: boolean } };
  if (start.kind !== "RUN_START" || start.payload?.is_ai !== pv.is_ai || start.payload?.model !== pv.model) {
    return { kind: "refused", entry, result, reason: "The provenance differs from the hashed RUN_START record." };
  }
  if (pv.mode === "offline-NOT-AI" && (pv.is_ai || pv.model !== "TEST-DOUBLE-NOT-AI")) {
    return { kind: "refused", entry, result, reason: "An offline bundle must be the TEST-DOUBLE-NOT-AI client." };
  }
  return { kind: "verified", entry, bundle, result };
}

export async function loadReplay(bundleId: string | null, fetcher: Fetcher = fetch,
  onProgress?: (done: number, total: number) => void): Promise<LoadOutcome> {
  try {
    const manifest = await loadManifest(fetcher);
    if (!manifest || manifest.bundles.length === 0) return { kind: "empty" };
    const entry = bundleId ? manifest.bundles.find((b) => b.bundle_id === bundleId) : manifest.bundles.at(-1);
    if (!entry) return { kind: "refused", entry: null, result: null, reason: "No bundle with that id is listed." };
    const res = await fetcher(`/bundles/${entry.file}`);
    if (!res.ok) return { kind: "error", reason: `The replay file could not be loaded (HTTP ${res.status}).` };
    return await verifyBundleBytes(await res.arrayBuffer(), entry, onProgress);
  } catch (e) {
    return { kind: "error", reason: e instanceof Error ? e.message : "The replay could not be loaded." };
  }
}
