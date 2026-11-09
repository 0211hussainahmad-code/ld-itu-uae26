import { readFileSync, readdirSync, existsSync, writeFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { build as viteBuild, type Plugin } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Bundles are committed under web/data/bundles (single source of truth) and published at
// /bundles/<bundle_id>.json. They are copied byte-for-byte; nothing here alters them.
const BUNDLES = resolve(import.meta.dirname, "../data/bundles");

function bundleFiles(): string[] {
  return existsSync(BUNDLES) ? readdirSync(BUNDLES).filter((f) => f.endsWith(".json")).sort() : [];
}

// With no committed bundles, ship an explicit empty list so the site shows its honest empty
// state instead of mistaking an HTML fallback page for data.
const EMPTY_MANIFEST = JSON.stringify({ schema: "linkdown-bundle-manifest/1", bundles: [] }, null, 2) + "\n";

// Pointers to the external anchors: the commit that ADDED each bundle carries its head in the message
// ("BUNDLE <id> AUDIT_HEAD <head> SOURCE <sha> RUN <url>"). Read from git at build time; informational
// only (the site tells visitors to compare it on GitHub). Without git it is an empty list.
const ANCHOR_LINE = /^BUNDLE ([0-9a-f]{16}) AUDIT_HEAD ([0-9a-f]{64}) SOURCE ([0-9a-f]{40}) RUN (\S+)$/m;
function anchorsJson(): string {
  const anchors: Record<string, { commit: string; audit_head: string; source_commit: string; run_url: string }> = {};
  for (const f of bundleFiles().filter((x) => x !== "manifest.json")) {
    try {
      const repo = resolve(import.meta.dirname, "../..");
      const out = execFileSync("git", ["-C", repo, "log", "--diff-filter=A", "--format=%H%x00%B%x1e", "--", `web/data/bundles/${f}`], { encoding: "utf8" });
      const entries = out.split("\x1e").map((e) => e.trim()).filter(Boolean);
      if (entries.length !== 1) continue;
      const [commit, msg] = entries[0]!.split("\x00") as [string, string];
      const m = msg.match(ANCHOR_LINE);
      if (m && `${m[1]}.json` === f) anchors[m[1]!] = { commit, audit_head: m[2]!, source_commit: m[3]!, run_url: m[4]! };
    } catch { /* no git: leave out */ }
  }
  const sorted = Object.fromEntries(Object.entries(anchors).sort(([a], [b]) => a.localeCompare(b)));
  return JSON.stringify({ schema: "linkdown-bundle-anchors/1", anchors: sorted }, null, 2) + "\n";
}

function replayBundles(): Plugin {
  return {
    name: "linkdown-replay-bundles",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const m = req.url?.match(/^\/bundles\/([0-9a-z.-]+\.json)$/);
        if (!m) return next();
        const name = m[1]!;
        if (name === "anchors.json") {
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          return res.end(anchorsJson());
        }
        if (name === "manifest.json" && !bundleFiles().includes(name)) {
          res.setHeader("Content-Type", "application/json; charset=utf-8");
          return res.end(EMPTY_MANIFEST);
        }
        if (!bundleFiles().includes(name)) return next();
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        res.end(readFileSync(resolve(BUNDLES, name)));
      });
    },
    generateBundle() {
      if (!bundleFiles().includes("manifest.json")) {
        this.emitFile({ type: "asset", fileName: "bundles/manifest.json", source: EMPTY_MANIFEST });
      }
      this.emitFile({ type: "asset", fileName: "bundles/anchors.json", source: anchorsJson() });
      for (const f of bundleFiles()) {
        this.emitFile({ type: "asset", fileName: `bundles/${f}`, source: readFileSync(resolve(BUNDLES, f)) });
      }
    },
  };
}

// Serve the production CSP from public/_headers in `vite preview`, so end-to-end tests run under it.
const CSP = readFileSync(resolve(import.meta.dirname, "public/_headers"), "utf8").match(/Content-Security-Policy:\s*(.+)/)?.[1]?.trim() ?? "";



// The fonts that set the first screen's text are preloaded, so text paints in its own face
// instead of swapping from a fallback once the stylesheet discovers them (a layout shift).
const CRITICAL_FONTS = [/ibm-plex-sans-latin-400-normal-[^/]+\.woff2$/, /newsreader-latin-300-normal-[^/]+\.woff2$/, /ibm-plex-mono-latin-400-normal-[^/]+\.woff2$/];
function preloadFonts(): Plugin {
  return {
    name: "linkdown-preload-fonts",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        const files = Object.keys(ctx.bundle ?? {});
        return CRITICAL_FONTS.map((re) => {
          const f = files.find((x) => re.test(x));
          if (!f) throw new Error(`preloadFonts: no file matches ${re}`);
          return { tag: "link", attrs: { rel: "preload", as: "font", type: "font/woff2", crossorigin: true, href: `/${f}` }, injectTo: "head" as const };
        });
      },
    },
  };
}

// First paint without waiting for JavaScript: after the client build, render each route's static
// shell (src/prerender.tsx: header, headings, loading states; never bundle data) into its own HTML
// file. The browser app renders over it. The production CSP forbids inline styles, so a shell with
// a style attribute fails the build rather than shipping a CSP violation.
function prerender(): Plugin {
  let root = "", outDir = "", ssr = false;
  const pages = new Map<string, { js: string; css: string[] }>();   // route page name -> its chunk and styles
  return {
    name: "linkdown-prerender",
    apply: "build",
    configResolved(c) { root = c.root; outDir = resolve(c.root, c.build.outDir); ssr = Boolean(c.build.ssr); },
    generateBundle(_o, bundle) {
      for (const ch of Object.values(bundle)) {
        const m = ch.type === "chunk" && ch.isDynamicEntry ? (ch.facadeModuleId ?? "").match(/\/src\/pages\/([A-Za-z]+)\.tsx$/) : null;
        if (m && ch.type === "chunk") pages.set(m[1]!, { js: ch.fileName, css: [...(ch.viteMetadata?.importedCss ?? [])].sort() });
      }
    },
    async closeBundle() {
      if (ssr) return;
      const tmp = resolve(root, "node_modules/.linkdown-prerender");
      await viteBuild({ root, configFile: resolve(root, "vite.config.ts"), logLevel: "warn",
        build: { ssr: "src/prerender.tsx", outDir: tmp, emptyOutDir: true, rollupOptions: { output: { entryFileNames: "prerender.mjs" } } } });
      const mod = await import(`${pathToFileURL(resolve(tmp, "prerender.mjs")).href}?${Date.now()}`) as
        { ROUTES: Record<string, string>; TITLES: Record<string, string>; render: (url: string) => string };
      const template = readFileSync(resolve(outDir, "index.html"), "utf8");
      const slot = '<div id="root"></div>';
      if (!template.includes(slot)) throw new Error("prerender: index.html has no empty #root");
      // Unknown paths get the plain shell (served by the host as 404.html), never another page's markup.
      const titled = (html: string, title: string) => {
        if (!html.includes("<title>LinkDown</title>")) throw new Error("prerender: index.html has no <title>LinkDown</title>");
        return html.replace("<title>LinkDown</title>", `<title>${title.replace(/[<&]/g, "")}</title>`);
      };
      writeFileSync(resolve(outDir, "404.html"), titled(template, mod.TITLES["404"]!));
      for (const [url, file] of Object.entries(mod.ROUTES)) {
        const html = mod.render(url);
        if (/\sstyle=/.test(html)) throw new Error(`prerender: ${url} has an inline style attribute, which the CSP blocks`);
        if (/<script/i.test(html)) throw new Error(`prerender: ${url} contains a script element`);
        // A route page's own styles and script are split from the main chunk: link them so the shell is styled at once.
        const name = { "/replay": "Replay", "/audit": "Audit", "/walkthrough": "Walkthrough" }[url];
        const page = name ? pages.get(name) : undefined;
        if (name && !page) throw new Error(`prerender: no chunk found for ${name}`);
        const head = page ? [...page.css.map((f) => `<link rel="stylesheet" crossorigin href="/${f}">`), `<link rel="modulepreload" crossorigin href="/${page.js}">`].join("") : "";
        writeFileSync(resolve(outDir, file), titled(template, mod.TITLES[url] ?? "LinkDown").replace("</head>", `${head}</head>`).replace(slot, `<div id="root">${html}</div>`));
      }
      rmSync(tmp, { recursive: true, force: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), replayBundles(), preloadFonts(), prerender()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false, assetsInlineLimit: 0 },
  preview: { port: 4173, strictPort: true, headers: CSP ? { "Content-Security-Policy": CSP } : {} },
  test: { environment: "node", include: ["tests/unit/**/*.test.ts"] },
});
