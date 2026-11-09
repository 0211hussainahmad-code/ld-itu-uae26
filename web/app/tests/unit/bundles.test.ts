// Every committed bundle verifies fully in the browser verifier (M1-T4, §18.3 step 5).
// Set EXPECTED_HEAD to require that a bundle with exactly that head exists and verifies.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { ManifestSchema } from "../../src/lib/bundle";
import { verifyBundleBytes } from "../../src/lib/loader";

const DIR = resolve(import.meta.dirname, "../../../data/bundles");
const manifestPath = resolve(DIR, "manifest.json");
const manifest = existsSync(manifestPath) ? ManifestSchema.parse(JSON.parse(readFileSync(manifestPath, "utf8"))) : null;
const expectedHead = process.env.EXPECTED_HEAD ?? null;

it("committed bundles verify fully and match the manifest", async () => {
  const entries = manifest?.bundles ?? [];
  if (expectedHead) expect(entries.some((e) => e.audit_head === expectedHead)).toBe(true);
  for (const e of entries) {
    const b = readFileSync(resolve(DIR, e.file));
    const o = await verifyBundleBytes(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength), e);
    expect(o.kind, `${e.file}: ${"reason" in o ? o.reason : ""}`).toBe("verified");
    if (o.kind === "verified") {
      expect(o.result.head).toBe(e.audit_head);
      expect(o.bundle.provenance.mode).toBe(e.mode);
      if (e.mode === "offline-NOT-AI") expect(o.bundle.provenance.model).toBe("TEST-DOUBLE-NOT-AI");
    }
  }
  console.log(`browser verifier: ${entries.length} committed bundle(s) verified` + (expectedHead ? `; head ${expectedHead} present` : ""));
});
