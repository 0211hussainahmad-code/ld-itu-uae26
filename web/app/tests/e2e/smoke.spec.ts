// End-to-end checks on the built site (served by `vite preview`): every visible control works,
// labels stay truthful, and automated accessibility checks find nothing serious.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "./fixtures";

async function noSeriousAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
}

test.describe("landing", () => {
  test("explains LinkDown, labels the run as not AI, and the primary action opens the replay", async ({ page, browserName, isMobile }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("who");
    await expect(page.getByText("TEST-DOUBLE-NOT-AI").first()).toBeVisible();
    await expect(page.getByText("It is not AI output")).toBeVisible();
    await expect(page.getByRole("button", { name: "Skip intro" })).toHaveCount(0);   // reduced motion: no intro at all
    // The decorative hero map is not in the tab order. On arrival Tab starts at "Skip to content", then the
    // header (wordmark, three links, sound), then the hero's actions.
    const cta = page.getByRole("link", { name: "Explore the evidence" });
    let presses = 0;
    const touchOnlyWebKit = browserName === "webkit" && isMobile;
    if (touchOnlyWebKit) {
      // WebKit's iPhone profile has no Tab order to walk (desktop WebKit walks it below, in its own project).
      // The action must still be focusable (e.g. with a paired keyboard); axe still runs below.
      await cta.focus();
      await expect(cta).toBeFocused();
    } else {
      // Walk the Tab order and record what receives focus. WebKit tabs to links with Option held, as Safari
      // does; a WebKit port whose policy keeps links out of the Tab order (Playwright's WebKit on Windows) is
      // detected by the walk itself, never assumed from the browser's name.
      const reached: string[] = [];
      const walk = async (key: string) => {
        for (presses = 0; presses < 10 && !(await cta.evaluate((el) => el === document.activeElement)); presses++) {
          await page.keyboard.press(key);
          reached.push(await page.evaluate(() => document.activeElement?.tagName ?? "none"));
        }
        return cta.evaluate((el) => el === document.activeElement);
      };
      let ok = await walk(browserName === "webkit" ? "Alt+Tab" : "Tab");
      if (!ok && browserName === "webkit") { await page.locator("body").focus(); ok = await walk("Tab"); }
      if (!ok && browserName === "webkit" && !reached.includes("A") && reached.includes("BUTTON")) {
        // This engine's Tab order holds buttons but no links at all (its policy, not the page's): the action must
        // still be a real, focusable link, kept out of no Tab order by the page itself.
        test.info().annotations.push({ type: "tab-to-links", description: `engine Tab order reached ${JSON.stringify(reached)}: no link is tabbable in this engine` });
        await expect(cta).toHaveAttribute("href", "/replay");
        await expect(cta).not.toHaveAttribute("tabindex", /.*/);
        await cta.focus();
      }
      await expect(cta).toBeFocused();
    }
    await noSeriousAxeViolations(page);
    await page.getByRole("link", { name: "Explore the evidence" }).click();
    await expect(page).toHaveURL(/\/replay/);
    await expect(page.getByTestId("verification")).toContainText("agree with the chain");
  });

  test("the intro can be skipped and never blocks the actions", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.goto("/");
    await expect(page.getByRole("link", { name: "Explore the evidence" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Experience the story" })).toBeVisible();
    const skip = page.getByRole("button", { name: "Skip intro" });
    await expect(skip).toBeVisible();
    await skip.click();
    await expect(skip).toHaveCount(0);
    await expect(page.getByText(/Event 1, T\+0 min/)).toBeVisible();
  });
});

test.describe("replay", () => {
  test("provenance is always visible and labelled TEST-DOUBLE-NOT-AI", async ({ page }) => {
    await page.goto("/replay");
    await expect(page.getByTestId("not-ai-label")).toHaveText("TEST-DOUBLE-NOT-AI");
    await expect(page.getByTestId("provenance")).toContainText("not AI output");
    await expect(page.getByTestId("verification")).toContainText("127 of 127");
    await noSeriousAxeViolations(page);
  });

  test("step, play, pause, keyboard and event jumps all move the replay", async ({ page }) => {
    await page.goto("/replay");
    const title = page.locator("h1");
    await expect(title).toHaveText("The exercise starts");
    await page.getByRole("button", { name: "Next step" }).click();
    await expect(title).toContainText("Event 1");
    const pos = page.getByRole("slider", { name: "Replay position" });
    await page.keyboard.press("ArrowRight");
    await expect(pos).toHaveValue("2");
    await page.keyboard.press("ArrowLeft");
    await expect(pos).toHaveValue("1");
    await page.getByRole("button", { name: /Jump to event 3/ }).click();
    await expect(title).toContainText("Event 3");
    await page.getByRole("button", { name: "Go to start" }).click();
    await page.getByRole("button", { name: "Play" }).click();
    await expect(pos).not.toHaveValue("0", { timeout: 4000 });
    await page.getByRole("button", { name: "Pause" }).click();
    const after = await pos.inputValue();
    await page.waitForTimeout(1800);
    await expect(pos).toHaveValue(after);
    await page.getByRole("button", { name: "Go to end" }).click();
    await expect(title).toHaveText("The exercise ends");
  });

  test("the evidence drawer shows the gate outcome, trail and citation warnings, and closes with Escape", async ({ page }) => {
    await page.goto("/replay");
    await page.getByRole("button", { name: /Jump to event 2/ }).click();
    for (let i = 0; i < 8; i++) await page.getByRole("button", { name: "Next step" }).click();
    await page.getByRole("button", { name: "Government AI service", exact: true }).click();
    await page.getByRole("button", { name: /transfer case files/ }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Needs a competent authority");
    await expect(dialog).toContainText("Decision trail");
    await expect(dialog).toContainText("Not approved by the simulated controller");
    await expect(dialog).toContainText("never decides authority questions");
    await expect(dialog).toContainText("Register status of this cited passage");
    await noSeriousAxeViolations(page);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("role views restrict what is shown", async ({ page }) => {
    await page.goto("/replay?step=11");
    await page.getByRole("button", { name: "Policy and legal adviser", exact: true }).click();
    await expect(page.getByText("This role receives no network or service data")).toBeVisible();
    await page.getByRole("button", { name: "Regulator", exact: true }).click();
    await expect(page.getByText("This role sees the class names only")).toBeVisible();
    await page.getByRole("button", { name: "Network operator", exact: true }).click();
    await expect(page.getByText(/As recorded at event 1/)).toBeVisible();
  });

  test("chart links explain themselves on focus", async ({ page }) => {
    await page.goto("/replay?step=2");
    await page.getByRole("button", { name: /Westbound system 1 \(Red Sea route\), link W1: failed/ }).focus();
    await expect(page.getByRole("status").filter({ hasText: "Westbound system 1" })).toContainText("Failed");
  });

  test("event steps offer key-moment jumps that land on the decision", async ({ page }) => {
    await page.goto("/replay");
    await page.getByRole("button", { name: /Jump to event 2/ }).click();
    await page.getByRole("button", { name: /transfer case files: Needs a competent authority/ }).click();
    await expect(page.locator("h1")).toContainText("proposes to transfer case files");
    await expect(page).toHaveURL(/step=\d+/);
    const n = Number(new URL(page.url()).searchParams.get("step"));
    await expect(page.getByRole("slider", { name: "Replay position" })).toHaveValue(String(n - 1));   // address is 1-based
  });

  test("explained terms open on tap", async ({ page }) => {
    await page.goto("/replay");
    await page.getByRole("button", { name: "Why the views differ" }).click();
    await expect(page.getByRole("tooltip").filter({ hasText: "Each role is shown only" })).toBeVisible();
  });

  test("malformed step parameters do not break the page", async ({ page }) => {
    for (const q of ["1.5", "-4", "abc", "99999"]) {
      await page.goto(`/replay?step=${q}`);
      await expect(page.getByTestId("not-ai-label")).toBeVisible();
      await expect(page.locator("h1")).not.toBeEmpty();
    }
  });

  test("a gap observation's evidence says it was recorded, not 'nothing carried out'", async ({ page }) => {
    await page.goto("/replay");
    await page.getByRole("button", { name: "Go to end" }).click();
    await page.getByRole("button", { name: "Policy and legal adviser", exact: true }).click();
    await page.getByRole("button", { name: /record a gap observation/ }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("was recorded as a draft for human review");
    await expect(dialog).not.toContainText("Nothing was carried out");
    await page.keyboard.press("Escape");
  });

  test("an unknown bundle id is refused, not rendered", async ({ page }) => {
    await page.goto("/replay/0000000000000000");
    await expect(page.getByTestId("verification-failed")).toBeVisible();
  });
});

test.describe("audit", () => {
  test("verifies in the browser, catches a tampered record, and restores", async ({ page }) => {
    await page.goto("/audit");
    const result = page.getByTestId("audit-result");
    await expect(result).toContainText("Fully rehashed in your browser: 127 of 127 records", { timeout: 15000 });
    await noSeriousAxeViolations(page);
    await page.getByRole("button", { name: "Change it and verify" }).click();
    await expect(result).toContainText("The edit was caught at record #52", { timeout: 15000 });
    await page.getByRole("button", { name: "Restore the original" }).click();
    await expect(result).toContainText("127 of 127", { timeout: 15000 });
    await page.getByRole("button", { name: /Show all 127 records/ }).click();
    await expect(page.locator("details")).toHaveCount(127);
  });
});

for (const width of [320, 360, 390, 768, 1024, 1440]) {
  test(`no horizontal scroll at ${width}px on every page`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/", "/walkthrough", "/walkthrough?s=2", "/walkthrough?s=3", "/walkthrough?s=4", "/replay", "/audit"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} at ${width}px`).toBeLessThanOrEqual(0);
    }
  });
}

test("pages run under the production CSP with no violations or console errors", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
  page.on("pageerror", (e) => problems.push(String(e)));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => console.error(`CSP violation: ${e.violatedDirective} ${e.blockedURI}`));
  });
  for (const path of ["/", "/walkthrough", "/replay", "/audit"]) {
    const res = await page.goto(path);
    expect(res?.headers()["content-security-policy"]).toContain("script-src 'self'");
    await page.waitForLoadState("networkidle");
  }
  expect(problems).toEqual([]);
});
