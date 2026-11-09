// M3.2 polish pass (GPT-6 approved scope): phone layout of the Decision Gate, the hero action on the first screen,
// fully visible replay role chips, readable small text and an uncut map caption; the Audit tamper default and the
// sound mood of a broken chain. Each test fails if the corresponding defect returns.
import { expect, test, type Page } from "./fixtures";

// Phone screens as visitors see them (visible area with the browser's own bars), plus desktop.
const PHONES = [
  { width: 320, height: 568 },
  { width: 360, height: 640 },
  { width: 390, height: 664 },
  { width: 430, height: 740 },
];

async function ready(page: Page, path: string) {
  await page.goto(path);
  await page.waitForSelector('html[data-app="ready"]');
}

// "ready" means the app shell has mounted. The replay's arrow keys work only once its bundle has been fetched
// and rehashed and the timeline is on screen; keys pressed before that are lost (slower engines lost all 40).
async function replayReady(page: Page, path: string) {
  await ready(page, path);
  // Up to 20 s of the test's unchanged 30 s budget: fetching and rehashing 127 records is real work in a slow
  // engine, and the default 5 s assertion wait is not a property of the site. A replay that never verifies fails here.
  await expect(page.getByRole("region", { name: "Replay timeline" })).toBeVisible({ timeout: 20_000 });
}

async function gateLayout(page: Page) {
  const gate = page.getByTestId("gate-explainer").first();
  await gate.scrollIntoViewIfNeeded();
  await gate.getByRole("button", { name: "Show every stage at once" }).click();
  const svg = gate.locator("svg").first();
  await expect(svg).toHaveAttribute("data-pos", "held");
  return svg.evaluate((el) => {
    const texts = [...el.querySelectorAll("text")].map((t) => ({ s: t.textContent ?? "", r: t.getBoundingClientRect() }));
    const overlaps: string[] = [];
    for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
      const a = texts[i]!.r, b = texts[j]!.r;
      if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5) overlaps.push(`${texts[i]!.s} / ${texts[j]!.s}`);
    }
    const box = el.getBoundingClientRect();
    const outside = texts.filter((t) => t.r.left < box.left - 1 || t.r.right > box.right + 1).map((t) => t.s);
    // Text that escapes its own box (the authority box and the outcome box).
    const escapes: string[] = [];
    for (const g of el.querySelectorAll("g")) {
      const rect = g.querySelector(":scope > rect");
      if (!rect || g.querySelector(":scope > rect + rect")) continue;      // skip the gate posts
      const rr = rect.getBoundingClientRect();
      for (const t of g.querySelectorAll(":scope > text")) {
        const tr = t.getBoundingClientRect();
        if (tr.left < rr.left - 0.5 || tr.right > rr.right + 0.5) escapes.push(t.textContent ?? "");
      }
    }
    const lanes = [...el.querySelectorAll("path")].filter((p) => (p.getAttribute("d") ?? "").includes("H"));
    const endRect = [...el.querySelectorAll("g")].find((g) => /carried out|recorded/.test(g.textContent ?? "") && g.querySelector(":scope > rect"))!.querySelector("rect")!.getBoundingClientRect();
    const laneRight = Math.max(...lanes.map((p) => p.getBoundingClientRect().right));
    const scale = box.width / (el as SVGSVGElement).viewBox.baseVal.width;
    const smallestPx = Math.min(...[...el.querySelectorAll("text")].map((t) => parseFloat(getComputedStyle(t).fontSize) * scale));
    return { overlaps, outside, escapes, laneCrossesOutcome: laneRight > endRect.left + 1, verdict: el.textContent, smallestPx };
  });
}

test.describe("M3.2 Decision Gate on phones", () => {
  for (const vp of PHONES) {
    test(`at ${vp.width}px no gate label overlaps, escapes its box or leaves the diagram, and no line crosses the outcome`, async ({ page }) => {
      await page.setViewportSize(vp);
      await ready(page, "/");
      const g = await gateLayout(page);
      expect(g.overlaps).toEqual([]);
      expect(g.outside).toEqual([]);
      expect(g.escapes).toEqual([]);
      expect(g.laneCrossesOutcome).toBe(false);
      expect(g.smallestPx, "smallest rendered label").toBeGreaterThanOrEqual(10.5);
      expect(g.verdict).toContain("not approved");            // the recorded outcome is still stated, with its reason
      expect(g.verdict).toContain("by policy");
      expect(g.verdict).toContain("not carried out");
    });
  }

  test("desktop keeps its layout, and the lane stops at the outcome box there too", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await ready(page, "/");
    const g = await gateLayout(page);
    expect(g.overlaps).toEqual([]);
    expect(g.outside).toEqual([]);
    expect(g.laneCrossesOutcome).toBe(false);
    await expect(page.getByTestId("gate-explainer").first().locator("svg").first()).not.toHaveAttribute("data-narrow", /.*/);
  });

  test("a mid-size screen (700px) keeps the desktop layout, with no oversized labels", async ({ page }) => {
    await page.setViewportSize({ width: 700, height: 900 });
    await ready(page, "/");
    const g = await gateLayout(page);
    await expect(page.getByTestId("gate-explainer").first().locator("svg").first()).not.toHaveAttribute("data-narrow", /.*/);
    expect(g.overlaps).toEqual([]);
    expect(g.smallestPx).toBeLessThanOrEqual(14);
  });

  for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 664 }]) {
    test(`in the evidence drawer at ${vp.width}px the gate labels read at drawer size (10.5-14px), never oversized`, async ({ page }) => {
      await page.setViewportSize(vp);
      await replayReady(page, "/replay?step=2");
      const open = page.getByRole("button", { name: "Open the evidence for this decision" });
      for (let i = 0; i < 40 && !(await open.count()); i++) await page.keyboard.press("ArrowRight");
      await open.click();
      const svg = page.getByRole("dialog").locator("svg[role=img]").first();
      await expect(svg).toBeVisible();
      // The drawer's diagram is about 524 px wide on desktop and narrower on phones: the small layout in both.
      // Wait for it to settle (engines report the width a frame or two apart), then hold it to 10.5-14 px.
      await expect(svg).toHaveAttribute("data-narrow", "true");
      const px = await svg.evaluate((el) => {
        const sc = el.getBoundingClientRect().width / (el as SVGSVGElement).viewBox.baseVal.width;
        return [...el.querySelectorAll("text")].map((t) => parseFloat(getComputedStyle(t).fontSize) * sc);
      });
      expect(Math.min(...px)).toBeGreaterThanOrEqual(10.5);
      expect(Math.max(...px)).toBeLessThanOrEqual(14);
    });
  }

  // WebKit's ResizeObserver missed both of these (a diagram mounted in a closed dialog, and a window resize).
  // With no ResizeObserver at all, the backups (next-frame and window-resize measurements) must still choose right.
  test("without ResizeObserver, the drawer diagram and a narrowing window still get the right layout", async ({ page }) => {
    await page.addInitScript(() => { (window as unknown as { ResizeObserver?: unknown }).ResizeObserver = undefined; });
    await page.setViewportSize({ width: 1440, height: 900 });
    await replayReady(page, "/replay?step=2");
    const open = page.getByRole("button", { name: "Open the evidence for this decision" });
    for (let i = 0; i < 40 && !(await open.count()); i++) await page.keyboard.press("ArrowRight");
    await open.click();
    const drawerSvg = page.getByRole("dialog").locator("svg[role=img]").first();
    await expect(drawerSvg).toHaveAttribute("data-narrow", "true");        // 524 px wide: the small layout
    const px = await drawerSvg.evaluate((el) => {
      const sc = el.getBoundingClientRect().width / (el as SVGSVGElement).viewBox.baseVal.width;
      return [...el.querySelectorAll("text")].map((t) => parseFloat(getComputedStyle(t).fontSize) * sc);
    });
    expect(Math.min(...px)).toBeGreaterThanOrEqual(10.5);
    expect(Math.max(...px)).toBeLessThanOrEqual(14);
    await ready(page, "/");
    const svg = page.getByTestId("gate-explainer").first().locator("svg").first();
    await svg.scrollIntoViewIfNeeded();
    await expect(svg).not.toHaveAttribute("data-narrow", /.*/);
    await page.setViewportSize({ width: 390, height: 664 });
    await expect(svg).toHaveAttribute("data-narrow", "true");
  });

  test("the diagram switches layout when the screen narrows, without a reload", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await ready(page, "/");
    const svg = page.getByTestId("gate-explainer").first().locator("svg").first();
    await svg.scrollIntoViewIfNeeded();
    await page.setViewportSize({ width: 390, height: 664 });
    await expect(svg).toHaveAttribute("data-narrow", "true");
  });
});

test.describe("M3.2 hero on phones", () => {
  for (const vp of PHONES) {
    test(`at ${vp.width}×${vp.height} the primary action and the not-AI label are on the first screen`, async ({ page }) => {
      await page.setViewportSize(vp);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await ready(page, "/");
      const cta = page.getByRole("button", { name: "Experience the story" });
      await expect(cta).toBeEnabled();
      const b = (await cta.boundingBox())!;
      expect(b.y).toBeGreaterThanOrEqual(0);
      expect(b.y + b.height).toBeLessThanOrEqual(vp.height);
      const label = (await page.locator(".not-ai").first().boundingBox())!;
      expect(label.y + label.height).toBeLessThanOrEqual(vp.height);
      // Tab order is unchanged by the visual reorder: the primary action is still the first control in the hero copy.
      const firstInCopy = await page.evaluate(() => document.querySelector("#hero-title")!.parentElement!.querySelector("a, button")!.textContent);
      expect(firstInCopy).toBe("Experience the story");
    });
  }
});

test.describe("M3.2 replay role chips", () => {
  for (const vp of PHONES) {
    test(`at ${vp.width}px every role chip is fully visible, named and pressable`, async ({ page }) => {
      await page.setViewportSize(vp);
      await ready(page, "/replay?step=2");
      const group = page.getByRole("group", { name: "Whose view to show" }).first();
      await expect(group).toBeVisible();
      const chips = group.getByRole("button");
      await expect(chips).toHaveCount(5);
      for (let i = 0; i < 5; i++) {
        const b = (await chips.nth(i).boundingBox())!;
        expect(b.x, `chip ${i} left`).toBeGreaterThanOrEqual(0);
        expect(b.x + b.width, `chip ${i} right`).toBeLessThanOrEqual(vp.width);
        expect(b.height).toBeGreaterThanOrEqual(40);
      }
      // No edge fade over the chips.
      expect(await group.evaluate((g) => getComputedStyle(g).maskImage || getComputedStyle(g).webkitMaskImage)).toMatch(/^(none|)$/);
      const adviser = group.getByRole("button", { name: "Policy and legal adviser" });
      await adviser.focus();
      await page.keyboard.press("Enter");
      await expect(adviser).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("role-view")).toHaveAttribute("data-role", "adviser");
    });
  }
});

test.describe("M3.2 readable small text and the pinned caption", () => {
  test("the faint text colour keeps at least 5:1 on every panel colour, and the smallest size is at least 12px", async ({ page }) => {
    await ready(page, "/");
    const r = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      const hex = (v: string) => v.trim().replace("#", "");
      const lum = (h: string) => {
        const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
        return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
      };
      const ratio = (a: string, b: string) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const faint = hex(css.getPropertyValue("--foam-faint"));
      const probe = document.createElement("span"); probe.style.fontSize = "var(--step--2)"; document.body.appendChild(probe);
      const px = parseFloat(getComputedStyle(probe).fontSize); probe.remove();
      return { bg: ["--abyss", "--trench", "--trench-2"].map((v) => ratio(faint, hex(css.getPropertyValue(v)))), px, dimGap: ratio(faint, hex(css.getPropertyValue("--foam-dim"))) };
    });
    for (const c of r.bg) expect(c).toBeGreaterThanOrEqual(5);
    expect(r.dimGap).toBeGreaterThanOrEqual(1.4);           // faint stays visibly below dim (text hierarchy)
    expect(r.px).toBeGreaterThanOrEqual(12);
  });

  for (const vp of PHONES) {
    test(`at ${vp.width}px the pinned map caption is shown in full`, async ({ page }) => {
      await page.setViewportSize(vp);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await ready(page, "/");
      await page.getByRole("button", { name: "Experience the story" }).click();
      const label = page.locator('[class*="stageLabel"]').first();
      // Into Act II, where the caption carries a time and is longest.
      // window.scrollBy, not mouse.wheel: mobile WebKit has no wheel events.
      for (let k = 0; k < 12 && !/T\+\d/.test(await label.innerText()); k++) {
        await page.evaluate(() => window.scrollBy(0, Math.round(window.innerHeight * 0.6)));
        await page.waitForTimeout(150);
      }
      await expect(label).toContainText(/Act II.*schematic, T\+/);
      await expect(label).toBeVisible();
      const cut = await label.evaluate((el) => ({ clipped: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1, ellipsis: getComputedStyle(el).textOverflow }));
      expect(cut.clipped).toBe(false);
      expect(cut.ellipsis).not.toBe("ellipsis");
      expect(await label.innerText()).toMatch(/T\+\d+\u00a0(min|h)/);        // a time never breaks across lines
    });
  }
});

test.describe("M3.2 audit tamper demonstration and its sound", () => {
  test("the default tamper target is the gate decision the Decision Gate features, and the broken chain changes the mood", async ({ page }) => {
    await ready(page, "/audit");
    const result = page.getByTestId("audit-result");
    await expect(result).toContainText("127 of 127", { timeout: 15000 });
    await expect(page.getByRole("combobox", { name: "Record to change" })).toHaveValue("52");
    await expect(page.getByRole("combobox", { name: "Record to change" }).locator("option:checked")).toHaveText(/^#52 /);
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "verify");
    await page.getByRole("button", { name: "Change it and verify" }).click();
    await expect(result).toContainText("The edit was caught at record #52", { timeout: 15000 });
    // The resolved "verify" chord would contradict a broken chain on screen.
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "disrupted");
    // Tampering again while broken never flips back to the resolved chord during the re-check.
    await page.evaluate(() => {
      (window as unknown as { moods: string[] }).moods = [];
      new MutationObserver(() => (window as unknown as { moods: string[] }).moods.push(document.documentElement.dataset.soundMood ?? ""))
        .observe(document.documentElement, { attributes: true, attributeFilter: ["data-sound-mood"] });
    });
    await page.getByRole("button", { name: "Change it and verify" }).click();
    await expect(result).toContainText("The edit was caught at record #52", { timeout: 15000 });
    expect(await page.evaluate(() => (window as unknown as { moods: string[] }).moods)).not.toContain("verify");
    await page.getByRole("button", { name: "Restore the original" }).click();
    await expect(result).toContainText("127 of 127", { timeout: 15000 });
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "verify");
  });
});
