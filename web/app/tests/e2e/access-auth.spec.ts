// Regression tests: Cloudflare Access credentials reach the preview's exact origin and nothing else, in
// browser requests (subresources, fetch, redirects) and in API requests. Runs in every browser project.
import { readFileSync } from "node:fs";
import { createServer, type IncomingMessage, type Server } from "node:http";
import { resolve } from "node:path";
import type { AddressInfo } from "node:net";
import { expect, test } from "@playwright/test";
import { accessCredentials, accessRequest, handleAccessRoute, installAccessAuth, sameOrigin, type AccessCreds } from "./access-auth";

const CREDS: AccessCreds = { "CF-Access-Client-Id": "test-id.access", "CF-Access-Client-Secret": "test-secret-value" };
type Seen = { path: string; id?: string; secret?: string };

function listen(handler: (req: IncomingMessage, res: import("node:http").ServerResponse, seen: Seen[]) => void) {
  const seen: Seen[] = [];
  const server: Server = createServer((req, res) => {
    seen.push({ path: req.url ?? "", id: req.headers["cf-access-client-id"] as string | undefined, secret: req.headers["cf-access-client-secret"] as string | undefined });
    handler(req, res, seen);
  });
  return new Promise<{ server: Server; seen: Seen[]; origin: string }>((ok) =>
    server.listen(0, "127.0.0.1", () => ok({ server, seen, origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}` })));
}

test.describe("Cloudflare Access credentials stay on the preview's origin", () => {
  let A: Awaited<ReturnType<typeof listen>>, B: Awaited<ReturnType<typeof listen>>;

  test.beforeAll(async () => {
    B = await listen((req, res) => {
      // Chromium's Private Network Access: a fulfilled (routed) document counts as outside the loopback
      // address space, so B must allow the preflight, as a real cross-origin server would allow CORS.
      const pna = { "access-control-allow-origin": "*", "access-control-allow-private-network": "true", "access-control-allow-headers": "*" };
      if (req.method === "OPTIONS") { res.writeHead(204, pna); res.end(); return; }
      if (req.url === "/img.png") { res.writeHead(200, { "content-type": "image/gif", ...pna }); res.end(Buffer.from("R0lGODlhAQABAAAAACw=", "base64")); return; }
      if (req.url === "/bounce") { res.writeHead(302, { location: `${A.origin}/page`, ...pna }); res.end(); return; }
      res.writeHead(200, { "content-type": req.url === "/s.js" ? "text/javascript" : "text/html", ...pna });
      res.end(req.url === "/s.js" ? "window.__b = 1;" : "<!doctype html><title>other origin</title>");
    });
    A = await listen((req, res) => {
      if (req.url === "/redir") { res.writeHead(302, { location: `${B.origin}/landing` }); res.end(); return; }
      if (req.url === "/via-b") { res.writeHead(302, { location: `${B.origin}/bounce` }); res.end(); return; }
      if (req.url === "/self") { res.writeHead(302, { location: "/self-2" }); res.end(); return; }          // same origin, two hops
      if (req.url === "/self-2") { res.writeHead(307, { location: `${A.origin}/page` }); res.end(); return; }
      if (req.url === "/self-then-b") { res.writeHead(302, { location: "/redir" }); res.end(); return; }    // same origin, then out
      res.writeHead(200, { "content-type": "text/html" });
      res.end(`<!doctype html><title>preview</title><img src="${B.origin}/img.png"><script src="${B.origin}/s.js"></script>
        <script>fetch("${B.origin}/api").then(() => { document.title = "fetched"; });</script>`);
    });
  });
  test.afterAll(async () => { A.server.close(); B.server.close(); });

  test("browser: same-origin requests carry the token; subresources, fetch and redirects to another origin never do", async ({ playwright, browserName }) => {
    // Test harness only: both test origins are on 127.0.0.1, and Chromium's local-network checks block a
    // routed (fulfilled) page from loading other loopback origins. Disabling them lets the page make MORE
    // cross-origin requests, so a leak would be easier, not harder, to see. Firefox and WebKit run as is.
    const browser = await playwright[browserName].launch(browserName === "chromium"
      ? { args: ["--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights"] } : {});
    const context = await browser.newContext();
    await installAccessAuth(context, A.origin, CREDS);
    const page = await context.newPage();
    await page.goto(`${A.origin}/page`);
    await expect(page).toHaveTitle("fetched");                         // the cross-origin fetch completed
    await page.goto(`${A.origin}/redir`);                               // A -> 302 -> B
    await expect(page).toHaveURL(`${B.origin}/landing`);
    await page.goto(`${A.origin}/via-b`);                               // A -> B -> back to A
    await expect(page).toHaveURL(`${A.origin}/page`);
    await page.goto(`${A.origin}/self`);                                // A -> A -> A/page (same-origin chain)
    await expect(page).toHaveTitle("fetched");                          // the final page rendered
    await page.goto(`${A.origin}/self-then-b`);                         // A -> A/redir -> B (leaves the origin later)
    await expect(page).toHaveURL(`${B.origin}/landing`);
    await context.close();
    await browser.close();

    expect(B.seen.map((s) => s.path)).toEqual(expect.arrayContaining(["/img.png", "/s.js", "/api", "/landing", "/bounce"]));
    for (const s of B.seen) {
      expect(s.id, `other origin got the id on ${s.path}`).toBeUndefined();
      expect(s.secret, `other origin got the secret on ${s.path}`).toBeUndefined();
    }
    // The preview's own navigations carry the token (a redirect *back* to A may or may not be re-routed by
    // the engine; without the token Access would refuse it, which fails closed and leaks nothing).
    for (const path of ["/page", "/redir", "/via-b", "/self", "/self-2", "/self-then-b"]) {
      expect(A.seen.some((s) => s.path === path && s.id === CREDS["CF-Access-Client-Id"] && s.secret === CREDS["CF-Access-Client-Secret"]), path).toBe(true);
    }
  });

  test("API: same-origin calls carry the token and do not follow redirects; other origins never get it", async ({ playwright }) => {
    const api = accessRequest(await playwright.request.newContext({ baseURL: A.origin }), A.origin, CREDS);
    const before = B.seen.length;
    const r = await api.get("/redir");
    expect(r.status()).toBe(302);                                       // not followed with the token
    expect(B.seen.length).toBe(before);                                 // B was never contacted
    await api.get(`${B.origin}/landing`);                               // an explicit other-origin call
    const last = B.seen.at(-1)!;
    expect([last.path, last.id, last.secret]).toEqual(["/landing", undefined, undefined]);
    await api.get("/page");
    const a = A.seen.at(-1)!;
    expect([a.path, a.id, a.secret]).toEqual(["/page", CREDS["CF-Access-Client-Id"], CREDS["CF-Access-Client-Secret"]]);
    await api.dispose();
  });
});

test("origin matching is exact: scheme, host and port", () => {
  const base = "https://preview.linkdown-preview.pages.dev";
  expect(sameOrigin("/audit", base)).toBe(true);
  expect(sameOrigin("https://preview.linkdown-preview.pages.dev/x", base)).toBe(true);
  for (const other of ["http://preview.linkdown-preview.pages.dev/", "https://preview.linkdown-preview.pages.dev:8443/",
    "https://linkdown-preview.pages.dev/", "https://preview.linkdown-preview.pages.dev.evil.example/",
    "https://evil.example/?u=https://preview.linkdown-preview.pages.dev", "https://x.cloudflareaccess.com/"]) {
    expect(sameOrigin(other, base), other).toBe(false);
  }
});

test("credentials are used only with an https base URL and both values present", () => {
  const ok = { E2E_BASE_URL: "https://preview.linkdown-preview.pages.dev", CF_ACCESS_CLIENT_ID: "i", CF_ACCESS_CLIENT_SECRET: "s" };
  expect(accessCredentials(ok)).not.toBeNull();
  expect(accessCredentials({ ...ok, E2E_BASE_URL: "http://preview.linkdown-preview.pages.dev" })).toBeNull();
  expect(accessCredentials({ ...ok, CF_ACCESS_CLIENT_SECRET: "" })).toBeNull();
  expect(accessCredentials({ CF_ACCESS_CLIENT_ID: "i", CF_ACCESS_CLIENT_SECRET: "s" })).toBeNull();
});

test("the Playwright config never sends headers to every origin", () => {
  const cfg = readFileSync(resolve(import.meta.dirname, "../../playwright.config.ts"), "utf8").replace(/\/\/.*$/gm, "");
  expect(cfg).not.toMatch(/extraHTTPHeaders\s*:/);
  expect(cfg).not.toMatch(/CF_ACCESS|CF-Access/);
});

// WebKit refuses route.fulfill() with a 3xx ("Cannot fulfill with redirect status"), which Chromium and
// Firefox accept, so the handler must never attempt it. A fake route that behaves like WebKit, in every engine.
function fakeRoute(url: string, answers: Record<string, { status: number; location?: string }>) {
  const calls: { fetched: Array<{ url: string; id?: string }>; fulfilled: number[]; continued: Array<unknown> } = { fetched: [], fulfilled: [], continued: [] };
  const route = {
    request: () => ({ url: () => url, headers: () => ({ accept: "*/*" }) }),
    fetch: async (o: { url: string; headers: Record<string, string> }) => {
      calls.fetched.push({ url: o.url, id: o.headers["CF-Access-Client-Id"] });
      const a = answers[o.url] ?? { status: 200 };
      return { status: () => a.status, headers: () => (a.location ? { location: a.location } : {}) };
    },
    fulfill: async ({ response }: { response: { status(): number } }) => {
      if (response.status() >= 300 && response.status() <= 399) throw new Error(`Cannot fulfill with redirect status: ${response.status()}`);
      calls.fulfilled.push(response.status());
    },
    continue: async (...args: unknown[]) => { calls.continued.push(args); },
  };
  return { route: route as unknown as import("@playwright/test").Route, calls };
}

test("handler: same-origin redirect chains are followed with the token and only the final 200 is fulfilled", async () => {
  const base = "https://preview.linkdown-preview.pages.dev";
  const { route, calls } = fakeRoute(`${base}/audit.html`, { [`${base}/audit.html`]: { status: 308, location: "/audit" } });
  await handleAccessRoute(route, base, CREDS);
  expect(calls.fetched).toEqual([{ url: `${base}/audit.html`, id: CREDS["CF-Access-Client-Id"] }, { url: `${base}/audit`, id: CREDS["CF-Access-Client-Id"] }]);
  expect(calls.fulfilled).toEqual([200]);
  expect(calls.continued).toEqual([]);
});

test("handler: a redirect that leaves the origin is never fulfilled and the browser repeats it without the token", async () => {
  const base = "https://preview.linkdown-preview.pages.dev";
  const { route, calls } = fakeRoute(`${base}/x`, { [`${base}/x`]: { status: 302, location: "https://team.cloudflareaccess.com/login" } });
  await handleAccessRoute(route, base, CREDS);
  expect(calls.fulfilled).toEqual([]);
  expect(calls.continued).toEqual([[]]);                               // continue() with NO overrides: no headers added
  expect(calls.fetched.map((f) => f.url)).toEqual([`${base}/x`]);      // the other origin was never fetched with the token
});

test("handler: other origins are passed through untouched, and endless same-origin redirects end without the token", async () => {
  const base = "https://preview.linkdown-preview.pages.dev";
  const other = fakeRoute("https://evil.example/a", {});
  await handleAccessRoute(other.route, base, CREDS);
  expect([other.calls.fetched, other.calls.fulfilled, other.calls.continued]).toEqual([[], [], [[]]]);
  const loop = fakeRoute(`${base}/loop`, { [`${base}/loop`]: { status: 302, location: "/loop" } });
  await handleAccessRoute(loop.route, base, CREDS);
  expect(loop.calls.fulfilled).toEqual([]);
  expect(loop.calls.continued).toEqual([[]]);
});
