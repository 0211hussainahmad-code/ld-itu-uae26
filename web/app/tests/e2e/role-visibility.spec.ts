// Information boundaries: each role view shows exactly what linkdown/agents.py build_view() gives that role.
// These tests fail if the network schematic, node relationships, per-link capacity or latency, endpoint or
// traffic data reappear in a role view that does not receive them, including in hidden DOM, accessible names
// and keyboard focus.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixtures";

const ROLE_BUTTON = {
  operator: "Network operator",
  service: "Government AI service",
  regulator: "Regulator",
  adviser: "Policy and legal adviser",
} as const;

// Markers that only the observer schematic or its link cards produce ("(capacity units)" is the per-link
// capacity row of a link card; traffic figures say "Synthetic capacity units (cu)" and are allowed).
const SCHEMATIC = 'svg[aria-label*="schematic of the synthetic network"]';
const OBSERVER_ONLY_TEXT = ["Capacity", "Latency", "(capacity units)", "Fujairah landing", "UAE core", "Neighbour route"];

async function openRole(page: Page, role: keyof typeof ROLE_BUTTON, step = 2) {
  await page.goto(`/replay?step=${step}`);               // step 2 = event 1: W1 and W2 have failed
  await page.getByRole("button", { name: ROLE_BUTTON[role], exact: true }).click();
  await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", role);
}

async function expectNoObserverData(page: Page) {
  await expect(page.locator(SCHEMATIC)).toHaveCount(0);                       // not rendered, not hidden
  await expect(page.getByTestId("observer-note")).toHaveCount(0);
  await expect(page.locator("main figure")).toHaveCount(0);                    // no chart of any kind, labelled or not
  await expect(page.locator("main svg text")).toHaveCount(0);                  // no node or region labels drawn
  const main = await page.locator("main").innerText();
  for (const t of ["Fujairah landing", "UAE core", "Neighbour route", "(capacity units)", "Latency"]) expect(main, t).not.toContain(t);
  const html = await page.evaluate(() => document.body.innerHTML);
  expect(html).not.toMatch(/aria-label="[^"]*link W\d/);                       // no link hit-targets or their names
  expect(html).not.toMatch(/\b\d+ ms\b/);                                      // no latency figures anywhere
  const roleView = await page.getByTestId("role-view").innerText();
  for (const t of OBSERVER_ONLY_TEXT) expect(roleView, t).not.toContain(t);
  // Keyboard: nothing focusable names a link.
  const focusables = await page.evaluate(() => [...document.querySelectorAll<HTMLElement>("a, button, [tabindex]")]
    .filter((el) => el.tabIndex >= 0).map((el) => el.getAttribute("aria-label") ?? el.textContent ?? ""));
  expect(focusables.filter((n) => /link [A-Z]\d/.test(n))).toEqual([]);
}

test("network operator: international link status and all traffic; no map, capacity or latency", async ({ page }) => {
  await openRole(page, "operator");
  const v = page.getByTestId("role-view");
  await expect(v).toContainText("International link status");
  await expect(v.locator("li", { hasText: "Westbound system 1 (Red Sea route)" })).toContainText("down");
  await expect(v.locator("li", { hasText: "Westbound system 3 (Red Sea route)" })).toContainText("up");
  await expect(v).not.toContainText("Domestic backbone");                     // build_view drops domestic links
  await expect(v).toContainText("Hospital tele-consultation");
  await expect(v).toContainText("4/6 cu");                                    // traffic figures are given
  await expect(v).toContainText("Total capacity to each cloud region");       // given, but not in the record
  await expect(v).not.toContainText("AI endpoint");                           // service data is not given
  await expect(v).not.toContainText("The AI endpoint changed");
  await expectNoObserverData(page);
});

test("the endpoint-change note (service information) reaches only the controller and the service lead", async ({ page }) => {
  await page.goto("/replay?step=35");                    // after event 2's endpoint switch, before new traffic
  await expect(page.getByText("The AI endpoint changed after this measurement")).toBeVisible();
  for (const role of ["operator", "regulator", "adviser"] as const) {
    await page.getByRole("button", { name: ROLE_BUTTON[role], exact: true }).click();
    await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", role);
    await expect(page.getByText("The AI endpoint changed")).toHaveCount(0);
  }
  await page.getByRole("button", { name: ROLE_BUTTON.service, exact: true }).click();
  await expect(page.getByTestId("role-view")).toContainText("The AI endpoint changed after this measurement");
});

test("the service lead's settings follow the run step by step", async ({ page }) => {
  await openRole(page, "service", 2);                     // event 1: endpoint still abroad
  const kv = page.getByTestId("role-view").locator("dl");
  await expect(kv).toContainText("AI endpointEU-West");
  await expect(kv).toContainText("Case files stored inUAE-Central");
  await expect(kv).toContainText("Service modefull");
  await openRole(page, "service", 35);                    // after the permitted endpoint switch
  await expect(kv).toContainText("AI endpointUAE-Central");
});

test("in role mode the step narrative is labelled as the controller's record", async ({ page }) => {
  await page.goto("/replay?step=2");
  await expect(page.getByTestId("record-scope")).toHaveCount(0);
  await page.getByRole("button", { name: ROLE_BUTTON.adviser, exact: true }).click();
  await expect(page.getByTestId("record-scope")).toContainText("not what the Policy and legal adviser is given");
});

test("government AI service: its settings and its own traffic only", async ({ page }) => {
  await openRole(page, "service", 33);
  const v = page.getByTestId("role-view");
  await expect(v).toContainText("AI endpoint");
  await expect(v).toContainText("Case files stored in");
  await expect(v).toContainText("Government service AI calls");
  await expect(v).not.toContainText("Hospital tele-consultation");
  await expect(v).not.toContainText("International link status");
  await expect(v).not.toContainText("Westbound system");
  await expect(v).toContainText("Available model endpoints");                  // given, not in the record
  await expectNoObserverData(page);
});

test("regulator: names of the demand classes only, no figures", async ({ page }) => {
  await openRole(page, "regulator");
  const v = page.getByTestId("role-view");
  await expect(v).toContainText("Hospital tele-consultation");
  await expect(v).toContainText("class names only");
  await expect(v).not.toContainText(" cu");
  await expect(v).not.toContainText("Westbound system");
  await expect(v).not.toContainText("AI endpoint");
  await expectNoObserverData(page);
});

test("policy and legal adviser: no network or service data at all", async ({ page }) => {
  await openRole(page, "adviser");
  const v = page.getByTestId("role-view");
  await expect(v).toContainText("receives no network or service data");
  await expect(v).not.toContainText("Hospital tele-consultation");
  await expect(v).not.toContainText(" cu");
  await expect(v).not.toContainText("Westbound system");
  await expect(v).not.toContainText("AI endpoint");
  await expect(v.locator("ul, dl")).toHaveCount(0);
  await expectNoObserverData(page);
  await expect(page.getByText("The network as shown to")).toHaveCount(0);       // the defective heading is gone
});

test("exercise controller: the full schematic, explicitly labelled as an observer view", async ({ page }) => {
  await page.goto("/replay?step=2");
  await expect(page.locator(SCHEMATIC)).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Exercise controller's schematic" })).toBeVisible();
  await expect(page.getByTestId("observer-note")).toContainText("No AI role is given this map");
  await expect(page.getByTestId("role-view")).toHaveCount(0);
  await page.getByRole("button", { name: /link W1: failed/ }).focus();
  const card = page.getByRole("status").filter({ hasText: "Westbound system 1" });
  await expect(card).toContainText("Capacity");
  await expect(card).toContainText("no AI role is given this");
});

test("switching roles swaps the view without leaving observer data behind", async ({ page }) => {
  await page.goto("/replay?step=2");
  for (const role of ["operator", "service", "regulator", "adviser"] as const) {
    await page.getByRole("button", { name: ROLE_BUTTON[role], exact: true }).click();
    await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", role);
    await expectNoObserverData(page);
  }
  await page.getByRole("button", { name: "All roles (exercise controller)" }).click();
  await expect(page.locator(SCHEMATIC)).toHaveCount(1);
});

test("role switching works from the keyboard", async ({ page }) => {
  await page.goto("/replay?step=2");
  await page.getByRole("button", { name: ROLE_BUTTON.adviser, exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", "adviser");
  await expect(page.getByRole("button", { name: ROLE_BUTTON.adviser, exact: true })).toHaveAttribute("aria-pressed", "true");
  await expectNoObserverData(page);
});

test("the landing page's role chapter never draws the network for a role", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const chapter = page.locator('article[data-chapter="roles"]');
  await chapter.scrollIntoViewIfNeeded();
  await page.evaluate(() => { const el = document.querySelector('article[data-chapter="roles"]')!; window.scrollBy(0, el.getBoundingClientRect().top - window.innerHeight * 0.3); });
  for (const role of ["operator", "service", "regulator", "adviser"] as const) {
    await chapter.getByRole("button", { name: ROLE_BUTTON[role], exact: true }).click();
    const v = page.getByTestId("role-view");
    await expect(v).toHaveAttribute("data-role", role);
    const stage = v.locator("xpath=..");
    await expect(stage.locator("svg")).toHaveCount(0);
    for (const t of OBSERVER_ONLY_TEXT) await expect(v).not.toContainText(t);
  }
  await expect(page.getByTestId("role-view")).toContainText("receives no network or service data");
});

// One full-page axe scan per test: five scans in one test exceeded its 30 s budget in slower engines
// (Firefox and WebKit on Windows), with no violation found. Same pages, same states, same filter.
for (const role of ["operator", "service", "regulator", "adviser"] as const) {
  test(`role views have accessible names and no serious accessibility violations: ${role}`, async ({ page }) => {
    await openRole(page, role);
    await expect(page.getByRole("region", { name: `What the ${ROLE_BUTTON[role]} is given` })).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${role} ${v.id}: ${v.help}`)).toEqual([]);
  });
}

test("role views have accessible names and no serious accessibility violations: landing role chapter", async ({ page }) => {
  await page.goto("/");
  await page.locator('article[data-chapter="roles"]').scrollIntoViewIfNeeded();
  await page.evaluate(() => { const el = document.querySelector('article[data-chapter="roles"]')!; window.scrollBy(0, el.getBoundingClientRect().top - window.innerHeight * 0.3); });
  await expect(page.getByTestId("role-view")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => v.id)).toEqual([]);
});
