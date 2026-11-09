// Replay bundle schema (linkdown-replay-bundle/1). Mirrors web/bundler/schema.py exactly;
// any change must update both and bump the schema id.
import { z } from "zod";
import "./zodConfig";

export const SCHEMA_ID = "linkdown-replay-bundle/1";
export const MANIFEST_ID = "linkdown-bundle-manifest/1";

const hex64 = z.string().regex(/^[0-9a-f]{64}$/);
const count = z.number().int().nonnegative();

// Fields that would carry prompts, turn files or raw model output. Never allowed anywhere.
export const FORBIDDEN_KEYS = new Set([
  "system", "user", "prompt", "prompts", "response_text", "response_json", "raw_response", "messages_raw", "turn_text",
]);

export const AuditRecordSchema = z
  .object({
    seq: z.number().int(),
    kind: z.string(),
    actor: z.string(),
    prev: hex64,
    hash: hex64,
    body: z.string().nullable(),
    withheld: z.boolean(),
  })
  .strict()
  .refine((r) => (r.withheld ? r.body === null : typeof r.body === "string"), {
    message: "withheld records carry no body; published records carry the canonical string",
  });

const InspectSchema = z
  .object({
    passed: z.boolean(),
    mode: z.string(),
    coverage: z.unknown(),
    problems: z.array(z.string()),
    replay: z.unknown(),
    human: z.unknown(),
    human_decisions: z.unknown(),
    served_by: z.unknown(),
    limitations: z.array(z.string()),
    metrics: z.unknown(),
  })
  .strict();

export const ProvenanceSchema = z
  .object({
    mode: z.enum(["offline-NOT-AI", "live"]),
    label: z.string(),
    run_id: z.string(),
    scenario: z.string().nullable(),
    scenario_version: z.string().nullable(),
    variation: z.string().nullable(),
    model: z.string().nullable(),
    is_ai: z.boolean(),
    human: z.string().nullable(),
    rules_version: z.string().nullable(),
    roles_version: z.string().nullable(),
    topology_version: z.string().nullable(),
    prompt_version: z.string().nullable(),
    inputs: z.record(z.string(), z.unknown()),
    source_commit: z.string(),
    generator_run_url: z.string(),
    audit_head: hex64,
    record_count: count,
    withheld_count: count,
    inspect: InspectSchema,
  })
  .strict();

const ContextPart = z.object({ sha256: hex64, data: z.unknown() }).strict();

export const SourceSchema = z
  .object({
    source_id: z.string(),
    known: z.boolean(),
    in_kb: z.boolean(),
    kind: z.string(),
    publish: z.string(),
    title: z.string().optional(),
    issuer: z.string().optional(),
    version_date: z.string().optional(),
    url: z.string().optional(),
    register_status: z.string().optional(),
    jurisdiction: z.string().optional(),
  })
  .strict();

export const BundleSchema = z
  .object({
    schema: z.literal(SCHEMA_ID),
    provenance: ProvenanceSchema,
    context: z.object({ topology: ContextPart, roles: ContextPart, scenario: ContextPart }).strict(),
    audit: z.array(AuditRecordSchema).min(1),
    sources: z.record(z.string(), SourceSchema),
  })
  .strict();

export const ManifestEntrySchema = z.object({
  bundle_id: z.string().regex(/^[0-9a-f]{16}$/),
  file: z.string(),
  sha256: hex64,
  mode: z.enum(["offline-NOT-AI", "live"]),
  label: z.string(),
  audit_head: hex64,
  record_count: count,
  withheld_count: count,
  source_commit: z.string(),
  generator_run_url: z.string(),
  created_at: z.string(),
});

export const ManifestSchema = z.object({
  schema: z.literal(MANIFEST_ID),
  bundles: z.array(ManifestEntrySchema),
});

export type AuditRecord = z.infer<typeof AuditRecordSchema>;
export type Bundle = z.infer<typeof BundleSchema>;
export type Manifest = z.infer<typeof ManifestSchema>;
export type ManifestEntry = z.infer<typeof ManifestEntrySchema>;

export function findForbidden(obj: unknown, where = "$"): string[] {
  const out: string[] = [];
  if (Array.isArray(obj)) obj.forEach((v, i) => out.push(...findForbidden(v, `${where}[${i}]`)));
  else if (obj && typeof obj === "object") {
    for (const [k, v] of Object.entries(obj)) {
      if (FORBIDDEN_KEYS.has(k)) out.push(`${where}.${k}`);
      out.push(...findForbidden(v, `${where}.${k}`));
    }
  }
  return out;
}
