// Every spec imports `test` and `expect` from here. Against a protected preview (see access-auth.ts) the
// browser context and the `request` fixture authenticate to that one origin only; otherwise this is
// exactly Playwright's own `test`.
import { test as base, expect } from "@playwright/test";
import { accessCredentials, accessRequest, installAccessAuth } from "./access-auth";

const access = accessCredentials();

export const test = base.extend({
  context: async ({ context }, use) => {
    if (access) await installAccessAuth(context, access.base, access.creds);
    await use(context);
  },
  request: async ({ request }, use) => {
    await use(access ? accessRequest(request, access.base, access.creds) : request);
  },
});

export { expect };
export type { Page } from "@playwright/test";
