// Cloudflare Access service-token authentication for running the suite against a PROTECTED preview.
//
// The token is sent only to the preview's exact origin (scheme, host and port of E2E_BASE_URL):
//  - browser requests: a context route fetches same-origin requests itself, with the headers and with
//    redirects disabled; it follows same-origin redirects itself and fulfils only a final, non-redirect
//    response (every engine accepts that). A redirect that would leave the origin makes the browser repeat
//    the request without the token. Cross-origin requests are continued unchanged;
//  - API requests (the `request` fixture): headers are added per call for same-origin URLs, and those
//    calls do not follow redirects, so the headers cannot travel to another origin.
// Nothing is sent unless E2E_BASE_URL is https and both CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET
// are set. Never use Playwright's `extraHTTPHeaders` for this: it goes to every origin.
import type { APIRequestContext, BrowserContext, Route } from "@playwright/test";

export type AccessCreds = { "CF-Access-Client-Id": string; "CF-Access-Client-Secret": string };

export function accessCredentials(env: NodeJS.ProcessEnv = process.env): { base: string; creds: AccessCreds } | null {
  const base = env.E2E_BASE_URL, id = env.CF_ACCESS_CLIENT_ID, secret = env.CF_ACCESS_CLIENT_SECRET;
  if (!base || !id || !secret || !base.startsWith("https://")) return null;
  return { base, creds: { "CF-Access-Client-Id": id, "CF-Access-Client-Secret": secret } };
}

/** True only for the exact same origin (scheme, host, port). Relative URLs resolve against `base`. */
export function sameOrigin(url: string, base: string): boolean {
  try {
    return new URL(url, base).origin === new URL(base).origin;
  } catch {
    return false;
  }
}

const MAX_SAME_ORIGIN_HOPS = 5;

export async function installAccessAuth(context: BrowserContext, base: string, creds: AccessCreds): Promise<void> {
  await context.route("**/*", (route) => handleAccessRoute(route, base, creds));
}

/** The route handler, exported so its redirect rules can be tested against a WebKit-like fake route. */
export async function handleAccessRoute(route: Route, base: string, creds: AccessCreds): Promise<void> {
  const req = route.request();
  if (!sameOrigin(req.url(), base)) return route.continue();
  // NOT route.continue({ headers }): Chromium carries such headers to the target of a redirect, including
  // a cross-origin one (caught by access-auth.spec.ts). And NOT route.fulfill() with a 3xx: WebKit refuses
  // it ("Cannot fulfill with redirect status"). So: fetch with the token and redirects disabled; follow
  // same-origin redirects here, still with the token; fulfil only a final, non-redirect response. If a hop
  // would leave the origin, drop the token entirely: the browser repeats the original request WITHOUT it
  // and follows the redirect itself, so the other origin never sees the token. (A fulfilled same-origin
  // redirect chain keeps the original address in the browser: acceptable for checks against a static site.)
  let url = req.url();
  for (let hop = 0; hop <= MAX_SAME_ORIGIN_HOPS; hop++) {
    const response = await route.fetch({ url, headers: { ...req.headers(), ...creds }, maxRedirects: 0 });
    const location = response.headers()["location"];
    if (response.status() < 300 || response.status() > 399 || !location) return route.fulfill({ response });
    const next = new URL(location, url).href;
    if (!sameOrigin(next, base)) return route.continue();        // uncredentialed; the browser follows
    url = next;
  }
  return route.continue();                                         // too many hops: uncredentialed
}

const METHODS = new Set(["get", "head", "post", "put", "patch", "delete", "fetch"]);

/** An APIRequestContext that adds the token to same-origin calls only, and never follows their redirects. */
export function accessRequest(api: APIRequestContext, base: string, creds: AccessCreds): APIRequestContext {
  return new Proxy(api, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);
      if (typeof prop !== "string" || !METHODS.has(prop) || typeof value !== "function") return value;
      return (url: string | { url(): string }, options: Record<string, unknown> = {}) => {
        const target_url = typeof url === "string" ? url : url.url();
        if (!sameOrigin(target_url, base)) return value.call(target, url, options);
        const headers = { ...((options.headers as Record<string, string>) ?? {}), ...creds };
        return value.call(target, url, { ...options, headers, maxRedirects: 0 });
      };
    },
  });
}
