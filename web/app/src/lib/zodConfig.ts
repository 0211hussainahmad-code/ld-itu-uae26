// Imported first by main.tsx, before any schema is constructed: no runtime code generation.
// zod's JIT probes `new Function`, which the site's CSP (script-src 'self') blocks and reports.
import { z } from "zod";

z.config({ jitless: true });
