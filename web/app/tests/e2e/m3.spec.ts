// M3: five-act story, two paths, the Decision Gate, the judge walkthrough, cross-links that keep context,
// and the original sound layer (never audible before a click; real playback verified in the browser).
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixtures";
import { audioCapability, expectUnavailableFallback } from "./audio";

async function noSeriousAxeViolations(page: Page, where: string) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${where} ${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

// After an activation the engine must be on, or paused when the engine has no audio output; never still off.
// On failure, report the engine's own view, the page's errors and (if given) the key/click log.
async function expectSoundStarted(page: Page, what: string, log?: () => Promise<string[]>) {
  for (const until = Date.now() + 4000; Date.now() < until; await page.waitForTimeout(100)) {
    if (/^(on|paused)$/.test((await page.locator("html").getAttribute("data-sound")) ?? "")) return;
  }
  const debug = await page.evaluate(() => (window as unknown as { __linkdownSound?: { debug?: () => unknown } }).__linkdownSound?.debug?.() ?? null);
  throw new Error(`${what}: data-sound is "${await page.locator("html").getAttribute("data-sound")}". Engine: ${JSON.stringify(debug)}. Events: ${JSON.stringify(log ? await log() : [])}`);
}

async function countAudioContexts(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __acCount: number; AudioContext: typeof AudioContext };
    const AC = w.AudioContext;
    w.__acCount = 0;
    w.AudioContext = class extends AC { constructor(o?: AudioContextOptions) { super(o); w.__acCount++; } };
  });
}

test.describe("story paths", () => {
  test("Experience the story moves to Act I; the act wayfinder follows the reader", async ({ page, isMobile }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    await expect(page.locator("#act-1 h2")).toBeFocused();
    await expect(page.getByText("Act I, The world beneath").first()).toBeVisible();
    if (!isMobile) {
      const nav = page.getByRole("navigation", { name: "Story progress" });
      await expect(nav.locator('[aria-current="step"]')).toContainText("The world beneath");
      await nav.getByRole("link", { name: /The proof/ }).click();
      await expect(nav.locator('[aria-current="step"]')).toContainText("The proof", { timeout: 5000 });
    }
    await expect(page.getByText("What this run establishes, and what it does not")).toBeAttached();
  });

  test("Experience the story still reaches Act I when the run arrives after the click", async ({ page }) => {
    // Regression: the button works before the verified run has loaded; focus used to stay on the button.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.route("**/bundles/*.json", async (route) => {
      if (!route.request().url().endsWith("/manifest.json") && !route.request().url().endsWith("/anchors.json")) await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    await expect(page.locator("#act-1 h2")).toBeFocused({ timeout: 15000 });
    await expect(page.locator("#act-1 h2")).toBeInViewport();
  });

  test("Act II shows only the recorded failed links and the recorded traffic", async ({ page }) => {
    await page.goto("/");
    const brk = page.locator('[data-chapter="break"]');
    await expect(brk).toContainText("These are the only links the record shows failing");
    await expect(brk).toContainText("Westbound system 1 (Red Sea route) and Westbound system 2 (Red Sea route)");
    await expect(brk.getByRole("definition").first()).toContainText("4 of 6 cu, degraded");     // hospitals at event 1, from the EVENT record
  });

  test("the role chapter's 'not given' list never names data the role receives", async ({ page }) => {
    await page.goto("/");
    const ch = page.locator('[data-chapter="roles"]');
    await ch.scrollIntoViewIfNeeded();
    await ch.getByRole("button", { name: "Network operator", exact: true }).click();
    const notGiven = ch.locator("dt", { hasText: "Not given" }).locator("xpath=following-sibling::dd[1]");
    await expect(notGiven).not.toContainText("Traffic for the government AI service only");
    await expect(notGiven).not.toContainText("Names of the demand classes");
    await ch.getByRole("button", { name: "Regulator", exact: true }).click();
    await expect(notGiven).toContainText("Traffic for every demand class");
  });
});

test.describe("the Decision Gate", () => {
  test("an escalated proposal stops at the gate and is never drawn as carried out", async ({ page }) => {
    await page.goto("/");
    const gate = page.getByTestId("gate-explainer");
    await gate.scrollIntoViewIfNeeded();
    await expect(gate).toHaveAttribute("data-outcome", "INSUFFICIENT_AUTHORITY_OR_EVIDENCE");
    const diagram = gate.getByRole("img");
    await expect(diagram).toHaveAttribute("data-pos", "start");
    await expect(gate.getByTestId("gate-stage")).toContainText("transfer case files");
    await expect(gate.getByTestId("gate-stage")).toContainText("nothing has happened yet");
    const next = gate.getByRole("button", { name: /^Next:/ });
    await next.click();                                                     // 2 what it rests on
    await next.click();                                                     // 3 the limits
    await expect(gate.getByTestId("gate-stage")).toContainText("would prohibit, but its source is not verified");
    await next.click();                                                     // 4 conclusion
    await expect(diagram).toHaveAttribute("data-pos", "authority");
    await expect(gate.getByTestId("gate-stage")).toContainText("Needs a competent authority");
    await next.click();                                                     // 5 what happened next
    await expect(diagram).toHaveAttribute("data-pos", "held");
    await expect(gate.getByTestId("gate-stage")).toContainText("simulated controller");
    await expect(gate.getByTestId("gate-stage")).toContainText("did not approve it");
    await expect(gate.getByTestId("gate-stage")).toContainText("never decides authority questions");
    await expect(gate.getByTestId("gate-stage")).toContainText("Nothing was carried out");
    await next.click();                                                     // 6 uncertain
    await expect(gate.getByTestId("gate-stage")).toContainText("does not show that the decision is legally correct");
    await expect(diagram).not.toHaveAttribute("data-pos", "through");
    await expect(diagram).toHaveAttribute("aria-label", /nothing was carried out/);
    await gate.getByRole("button", { name: "Show every stage at once" }).click();
    await expect(gate.locator("h4")).toHaveCount(6);
    await noSeriousAxeViolations(page, "gate");
  });

  test("the evidence drawer shows the same gate diagram for the decision it explains", async ({ page }) => {
    await page.goto("/replay?step=1");
    await page.getByRole("button", { name: /^Jump to event 2/ }).click();
    await page.getByRole("button", { name: /transfer case files: Needs a competent authority/ }).click();
    await page.getByRole("button", { name: "Open the evidence for this decision" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("img", { name: /Needs a competent authority/ })).toBeVisible();
    await expect(dialog.getByRole("img", { name: /Needs a competent authority/ })).toHaveAttribute("data-pos", "held");
  });
});

test.describe("judge walkthrough", () => {
  // One full-page axe scan per test: six scans in one test exceeded its 30 s budget in slower engines
  // (Firefox and WebKit on Windows), with no violation found. Each step is still reached by its buttons.
  const WALK = ["The crisis", "Four roles, four realities", "A proposal meets the gate", "An authority gap", "Check the record", "What this does not prove"];
  for (let n = 1; n <= WALK.length; n++) {
    test(`six steps, by button, keyboard and address; each step passes axe: step ${n}`, async ({ page }) => {
      await page.goto("/walkthrough");
      const step = page.getByTestId("walkthrough-step");
      await expect(step).toHaveAttribute("data-step", "1");
      for (let k = 2; k <= n; k++) {
        await page.getByRole("button", { name: `Next: ${WALK[k - 1]}` }).click();
        await expect(step).toHaveAttribute("data-step", String(k));
      }
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(WALK[n - 1]!);
      await noSeriousAxeViolations(page, `walkthrough ${n}`);
    });
  }

  test("six steps, by button, keyboard and address", async ({ page }) => {
    await page.goto("/walkthrough");
    const step = page.getByTestId("walkthrough-step");
    await expect(step).toHaveAttribute("data-step", "1");
    await expect(page.getByText("TEST-DOUBLE-NOT-AI").first()).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("The crisis");
    const names = WALK.slice(1);
    for (const [k, name] of names.entries()) {
      await page.getByRole("button", { name: `Next: ${name}` }).click();
      await expect(step).toHaveAttribute("data-step", String(k + 2));
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(name);
      await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
      await expect(page).toHaveURL(new RegExp(`s=${k + 2}`));
    }
    await expect(page.getByText("A run with an AI model in all four roles has not been completed or published here")).toBeVisible();
    await expect(page.getByText(/first attempt, on 6 November 2026, reached 5 of the 12 role and event combinations and did not pass verification/)).toBeVisible();
    await page.keyboard.press("ArrowLeft");
    await expect(step).toHaveAttribute("data-step", "5");
    await expect(step).toContainText("127 of 127 agree with the chain");
    await page.goto("/walkthrough?s=4");
    await expect(step).toContainText("No publicly verified power for a binding national priority order");
    await expect(step).toContainText("G1");
  });

  test("role links keep context: they open that role's view at event 1 in the replay", async ({ page }) => {
    await page.goto("/walkthrough?s=2");
    await page.locator("article", { hasText: "Regulator" }).getByRole("link", { name: "See its view at event 1" }).click();
    await expect(page).toHaveURL(/\/replay\?step=2&role=regulator/);
    await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", "regulator");
    await page.getByRole("button", { name: "All roles (exercise controller)" }).click();
    await expect(page).not.toHaveURL(/role=/);
  });

  test("malformed step addresses fall back to step 1", async ({ page }) => {
    for (const v of ["0", "7", "abc", "2.5", "-1"]) {
      await page.goto(`/walkthrough?s=${v}`);
      await expect(page.getByTestId("walkthrough-step")).toHaveAttribute("data-step", v === "2.5" ? "2" : "1");
    }
  });
});

test.describe("evidence cross-links", () => {
  test("a replay step links to its record in the audit, which links back and to related records", async ({ page }) => {
    await page.goto("/replay?step=1");
    await page.getByRole("button", { name: /^Jump to event 2/ }).click();
    await page.getByRole("button", { name: /transfer case files: Needs a competent authority/ }).click();
    const seq = (await page.getByRole("link", { name: /in the audit/ }).innerText()).match(/#(\d+)/)![1];
    await page.getByRole("link", { name: /in the audit/ }).click();
    await expect(page).toHaveURL(new RegExp(`/audit\\?record=${seq}`));
    const rec = page.locator(`#record-${seq}`);
    await expect(rec.locator("details")).toHaveAttribute("open", "");
    const rel = rec.getByRole("link", { name: /Controller decision #\d+/ });
    await expect(rel).toBeVisible();
    const relSeq = (await rel.innerText()).match(/#(\d+)/)![1];
    await rel.click();
    await expect(page).toHaveURL(new RegExp(`record=${relSeq}$`));
    const relRec = page.locator(`#record-${relSeq}`);
    await expect(relRec).toHaveAttribute("data-focus", "true");
    await expect(relRec.locator("details")).toHaveAttribute("open", "");
    await relRec.getByRole("link", { name: /^Step \d+ in the replay$/ }).click();
    await expect(page.locator("h1")).toContainText("controller does not approve, by policy");
  });
});

test.describe("evidence cross-links: a linked record stays where it was scrolled to", () => {
  // Safari has no scroll anchoring: content that grows above a record after it was scrolled into view pushes
  // it away, and a tap then lands on something else (CI: WebKit mobile clicked "Controller decision #53" and
  // stayed on #52). Reproduced in every engine by turning scroll anchoring off and delaying anchors.json,
  // whose arrival makes the anchor panel above the record list about 130 px taller on a phone.
  test("arriving at a record waits for the page above it to settle, so it never moves afterwards", async ({ page }) => {
    // Through the CSSOM: the site's CSP (style-src 'self') rightly blocks an injected <style> element.
    await page.addInitScript(() => {
      document.addEventListener("DOMContentLoaded", () => {
        document.documentElement.style.overflowAnchor = "none";
        document.body.style.overflowAnchor = "none";
      });
    });
    await page.route("**/bundles/anchors.json", async (route) => { await new Promise((r) => setTimeout(r, 1200)); await route.continue(); });
    await page.goto("/audit?record=52");
    const link = page.locator("#record-52").getByRole("link", { name: /Controller decision #53/ });
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowAnchor)).toBe("none");
    await expect(link).toBeInViewport({ timeout: 10000 });
    const y0 = (await link.boundingBox())!.y;
    // The anchor panel has filled in. A build without an anchor list (the public repository: its fresh history has
    // no bundle-adding commits) settles on "Not available in this build." instead; the layout check is the same.
    const anchors = (await (await page.request.get("/bundles/anchors.json")).json()).anchors as Record<string, unknown>;
    if (Object.keys(anchors).length > 0) await expect(page.getByTestId("anchor-note")).toBeAttached();
    else await expect(page.getByText("Not available in this build.")).toBeAttached();
    await page.waitForTimeout(300);
    const y1 = (await link.boundingBox())!.y;
    expect(Math.abs(y1 - y0), `the linked record moved by ${Math.round(y1 - y0)} px after it was reached`).toBeLessThanOrEqual(1);
    await link.click();
    await expect(page).toHaveURL(/record=53$/);
    await expect(page.locator("#record-53")).toHaveAttribute("data-focus", "true");
  });
});

test.describe("sound", () => {
  test("silent and unbuilt until clicked; then really plays; off stops it; navigation never stacks tracks", async ({ page, browserName }) => {
    test.skip(browserName !== "chromium", "Web Audio playback is verified in Chromium here");
    await countAudioContexts(page);
    await page.goto("/");
    await page.waitForTimeout(800);
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(0);
    await expect(page.locator("html")).toHaveAttribute("data-sound", "off");
    const toggle = page.getByTestId("sound-toggle");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-sound", "on");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => page.evaluate(() => (window as unknown as { __linkdownSound: { level: () => number } }).__linkdownSound.level()), { timeout: 6000 }).toBeGreaterThan(0.002);
    const vol = page.getByRole("slider", { name: "Volume" });
    await vol.fill("20");
    await expect(vol).toHaveAttribute("aria-valuetext", "20 percent");
    // Moods follow the page: verification on the audit page, reading a role view on the replay.
    await page.getByRole("link", { name: /Audit/ }).first().click();
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "verify");
    await page.goto("/replay?step=2&role=adviser");               // full reload: the session remembers, but never resumes on its own
    await expect(page.locator("html")).toHaveAttribute("data-sound", "paused");
    await expect(page.getByTestId("sound-toggle")).toContainText("Resume sound");
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(0);
    await page.getByTestId("sound-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "focus");
    await page.getByRole("link", { name: /^Walkthrough$/ }).click();     // client-side navigation keeps one engine
    await page.getByRole("link", { name: /^Replay$/ }).click();
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(1);
    await page.getByTestId("sound-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("data-sound", "off");
    await expect.poll(() => page.evaluate(() => (window as unknown as { __linkdownSound: { level: () => number } }).__linkdownSound.level()), { timeout: 6000 }).toBeLessThan(0.0005);
  });

  test("the sound control is reachable by keyboard and named for screen readers", async ({ page, browserName }) => {
    await page.goto("/audit");
    const toggle = page.getByTestId("sound-toggle");
    await expect(page.locator("html")).toHaveAttribute("data-app", "ready");
    if (!(await audioCapability(page)).live) {
      // This engine has no Web Audio API (Playwright's WebKit on Windows): the control must say so, stay in
      // the keyboard path, ignore Enter and Space, and the page must stay free of serious violations.
      await expectUnavailableFallback(page, toggle);
      await noSeriousAxeViolations(page, "audit with sound unavailable");
      return;
    }
    await expect(toggle).toHaveAccessibleName("Sound");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await expect(toggle).toBeEnabled();      // the app has taken over the prerendered shell (its buttons are disabled)
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toBeFocused();
    // A supported context can move from paused to running between Playwright calls.
    // Read the component's rendered state, accessible label, pressed state and visible
    // volume control in one browser task; never assert against an earlier html state.
    await expect.poll(() => toggle.evaluate((button) => {
      const control = button.parentElement!;
      const volume = control.querySelector<HTMLInputElement>('input[type="range"]');
      const visible = !!volume && volume.getClientRects().length > 0 && getComputedStyle(volume).visibility !== "hidden";
      return [control.getAttribute("data-state"), button.getAttribute("aria-label"),
        button.getAttribute("aria-pressed"), String(visible), volume?.labels?.[0]?.textContent?.trim() ?? ""].join("|");
    })).toMatch(browserName === "chromium"
      ? /^on\|Sound\|true\|true\|Volume$/
      : /^(on\|Sound\|true\|true\|Volume|paused\|Resume sound\|false\|false\|)$/);
    // Paused audio must meet the same accessibility contract as playing audio.
    await noSeriousAxeViolations(page, "audit after keyboard sound activation");
  });
});

test.describe("audit proof strand", () => {
  test("every cell is marked rehashed after a pass; a tamper marks earlier cells checked, the edit changed, later ones unchecked", async ({ page }) => {
    await page.goto("/audit");
    const result = page.getByTestId("audit-result");
    await expect(result).toContainText("127 of 127", { timeout: 15000 });
    const cells = page.locator('[role="img"] > i');
    await expect(cells).toHaveCount(127);
    await expect(page.locator('[role="img"] > i[data-c="ok"]')).toHaveCount(127);
    await page.getByRole("button", { name: "Change it and verify" }).click();
    await expect(result).toContainText("The edit was caught at record #52", { timeout: 15000 });
    // The default target is the featured gate decision, #52: 51 earlier cells checked, #52 changed, 75 unchecked.
    await expect(page.locator('[role="img"] > i[data-c="ok"]')).toHaveCount(51);
    await expect(cells.nth(51)).toHaveAttribute("data-c", "bad");
    await expect(page.locator('[role="img"] > i[data-c="unchecked"]')).toHaveCount(75);
    await page.getByRole("button", { name: "Restore the original" }).click();
    await expect(page.locator('[role="img"] > i[data-c="ok"]')).toHaveCount(127, { timeout: 15000 });
  });
});

test.describe("sound control keyboard activation", () => {
  // A native button must activate with Enter and with Space. This counts real click events on the button,
  // so it does not depend on whether the engine has an audio device; the log explains any failure.
  test("Enter and Space each activate the sound button exactly once, in every engine", async ({ page }) => {
    await page.goto("/audit");
    const toggle = page.getByTestId("sound-toggle");
    await expect(page.locator("html")).toHaveAttribute("data-app", "ready");
    const live = (await audioCapability(page)).live;
    await expect(toggle).toHaveAccessibleName(live ? "Sound" : "Sound unavailable");
    await page.evaluate(() => {
      const w = window as unknown as { __kb: string[] };
      w.__kb = [];
      const isToggle = (t: EventTarget | null) => !!(t instanceof Element && t.closest('[data-testid="sound-toggle"]'));
      // Bubble phase on document runs after the app's own handlers, so defaultPrevented shows any interference.
      document.addEventListener("keydown", (e) => w.__kb.push(`keydown ${e.key} onToggle=${isToggle(e.target)} prevented=${e.defaultPrevented}`));
      document.addEventListener("keyup", (e) => w.__kb.push(`keyup ${e.key} onToggle=${isToggle(e.target)} prevented=${e.defaultPrevented}`));
      document.addEventListener("click", (e) => w.__kb.push(`click onToggle=${isToggle(e.target)} detail=${(e as MouseEvent).detail}`));
    });
    const log = () => page.evaluate(() => (window as unknown as { __kb: string[] }).__kb);
    const clicks = async () => (await log()).filter((x) => x.startsWith("click onToggle=true")).length;
    const waitForClicks = async (n: number, key: string) => {
      for (const until = Date.now() + 2000; Date.now() < until; await page.waitForTimeout(100)) if ((await clicks()) === n) return;
      throw new Error(`${key} did not activate the sound button (expected ${n} click(s) in total). Events: ${JSON.stringify(await log())}`);
    };
    if (live) await expect(toggle).toBeEnabled();      // the app has taken over the prerendered shell (its buttons are disabled)
    else await expect(toggle).toHaveAttribute("aria-disabled", "true");   // focusable, inert: no Web Audio here
    await toggle.focus();
    await page.keyboard.press("Enter");
    await waitForClicks(1, "Enter");
    if (live) await expectSoundStarted(page, "Enter (diagnostic)", log);
    else await expect(page.locator("html")).toHaveAttribute("data-sound", "unavailable");
    await expect(toggle).toBeFocused();
    await page.keyboard.press("Space");
    await waitForClicks(2, "Space");
    await expect(toggle).toBeFocused();
  });
});
