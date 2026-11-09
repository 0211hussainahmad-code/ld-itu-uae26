// Release identity, fetched at runtime from /release.json (never embedded in the build, so
// release.json can list the hashes of every other file without hashing itself; plan §18.1).
// Its own integrity is anchored outside the site (deploy record in git, GitHub Release, report).
import "./zodConfig";
import { z } from "zod";

export const ReleaseSchema = z.object({
  schema: z.literal("linkdown-release/1"),
  release_id: z.string(),
  git_commit: z.string(),
  built_at: z.string(),
  ci_run_url: z.string(),
  bundles: z.array(z.object({ bundle_id: z.string(), sha256: z.string(), audit_head: z.string() })),
  files: z.record(z.string(), z.object({ sha256: z.string(), bytes: z.number() })),
});
export type Release = z.infer<typeof ReleaseSchema>;

export async function loadRelease(fetcher: (u: string) => Promise<Response> = fetch): Promise<Release | null> {
  try {
    const res = await fetcher("/release.json");
    if (!res.ok) return null;
    const parsed = ReleaseSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}
