// M3.1: correctness and usability fixes, the Audit performance rework (prerendered shell, the page's
// own rehash shown honestly), and consistency checks the review asked for.
import { expect, test } from "./fixtures";
import { audioCapability, expectUnavailableFallback } from "./audio";

test.describe("audit verification is never shown early", () => {
  test("the prerendered audit page contains no verified state and no bundle data", async ({ request }) => {
    const html = await (await request.get("/audit")).text();
    expect(html).toContain("Every record, sealed to the one before.");
    expect(html).toContain("TEST-DOUBLE-NOT-AI");
    expect(html).not.toMatch(/data-c="ok"/);
    expect(html).not.toMatch(/records (verified|rehashed)/);
    expect(html).not.toMatch(/[0-9a-f]{64}/);      // no hash from the bundle before the browser has checked it
  });

  test("while the browser is still rehashing, no cell is green ahead of its own check and no result is claimed", async ({ page }) => {
    // Slow every SHA-256 so the run can be observed midway.
    await page.addInitScript(() => {
      const digest = crypto.subtle.digest.bind(crypto.subtle);
      let calls = 0;
      (window as unknown as { __digests: () => number }).__digests = () => calls;
      crypto.subtle.digest = (async (alg: AlgorithmIdentifier, data: BufferSource) => {
        await new Promise((r) => setTimeout(r, 25));
        calls++;
        return digest(alg, data);
      }) as typeof crypto.subtle.digest;
    });
    await page.goto("/audit");
    const result = page.getByTestId("audit-result");
    await expect(page.locator('[data-testid="audit-chain"] i[data-c="ok"]').first()).toBeVisible({ timeout: 15_000 });
    // Midway: green cells never outnumber the record hashes the page has actually computed (the first digest is the bundle file's).
    const [ok, digests] = await page.evaluate(() => [
      document.querySelectorAll('[data-testid="audit-chain"] i[data-c="ok"]').length,
      (window as unknown as { __digests: () => number }).__digests(),
    ]);
    expect(ok).toBeGreaterThan(0);
    expect(ok).toBeLessThan(127);
    expect(ok).toBeLessThanOrEqual(digests - 1);
    await expect(result).not.toContainText("records rehashed");
    await expect(result).toContainText("127 / 127 records rehashed", { timeout: 20_000 });
    await expect(page.locator('[data-testid="audit-chain"] i[data-c="ok"]')).toHaveCount(127);
  });

  test("arriving from the replay, the audit page reruns the check visibly instead of reusing the earlier result", async ({ page }) => {
    await page.goto("/replay?step=1");
    await expect(page.getByTestId("verification")).toContainText("127 of 127");
    await page.getByRole("link", { name: "Audit", exact: true }).click();
    await expect(page.getByTestId("audit-result")).toContainText("127 / 127 records rehashed");
    await expect(page.locator('[data-testid="audit-chain"] i[data-c="ok"]')).toHaveCount(127);
  });
});

test.describe("the record and the replay explain each other", () => {
  test("the replay pairs its step count with the record count and explains the difference", async ({ page }) => {
    await page.goto("/replay?step=40");
    const bar = page.getByRole("region", { name: "Replay timeline" });
    await expect(bar.getByRole("slider", { name: "Replay position" })).toHaveAttribute("aria-valuetext", /^Step 40 of 81, record \d+ of 127: /);
    const tip = bar.getByRole("button", { name: "Why two counts" });
    if (await tip.isVisible()) {
      await tip.click();
      await expect(page.getByRole("tooltip").filter({ hasText: "81 of the 127 audit records" })).toBeVisible();
    }
  });

  test("the audit page states which records are replay steps and which are bookkeeping, and filters by it", async ({ page }) => {
    await page.goto("/audit");
    const mapping = page.getByTestId("record-mapping");
    await expect(mapping).toContainText("The replay walks through 81 of these 127 records");
    await expect(mapping).toContainText("The other 46 are bookkeeping");
    await expect(mapping).toContainText("23 AGENT_TURN");
    await expect(mapping).toContainText("23 DEMO_TURN");
    await page.getByRole("combobox", { name: "Show" }).selectOption("bookkeeping");
    await page.getByRole("button", { name: /Show all \d+ records/ }).click();
    await expect(page.locator("#records-title + * li, ol li[id^=record-]")).toHaveCount(46);
    const row = page.locator("li[id^=record-]").first();
    await row.locator("summary").click();
    await expect(row.getByText("Bookkeeping record: not a step in the replay")).toBeVisible();
  });
});

test.describe("presentation consistency", () => {
  test("full hashes wrap only between groups and still copy as the exact hash", async ({ page }) => {
    await page.goto("/audit");
    await expect(page.getByTestId("audit-result")).toContainText("records rehashed");
    const manifest = await (await page.request.get("/bundles/manifest.json")).json();
    const head = manifest.bundles.at(-1).audit_head as string;
    const el = page.locator("dt", { hasText: "Audit head" }).locator("xpath=following-sibling::dd[1]").locator("code.hash-groups");
    expect(await el.evaluate((n) => n.textContent)).toBe(head);
    const groups = await el.locator("span").allInnerTexts();
    expect(groups.every((g) => g.length === 8)).toBe(true);
  });

  test("the main navigation uses the same three names at every width", async ({ page }) => {
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/audit");
      const nav = page.getByRole("navigation", { name: "Main" });
      expect(await nav.getByRole("link").allInnerTexts()).toEqual(["Walkthrough", "Replay", "Audit"]);
    }
  });

  test("event markers are not red: red is kept for failure, prohibition and a broken chain", async ({ page }) => {
    await page.goto("/replay?step=1");
    const flare = "rgb(255, 107, 91)";
    const ev = page.getByRole("button", { name: /^Jump to event 1/ });
    expect(await ev.evaluate((n) => getComputedStyle(n).borderLeftColor)).not.toBe(flare);
    await page.goto("/audit?record=2");
    const kind = page.locator("#record-2 [data-k=EVENT]");
    expect(await kind.evaluate((n) => getComputedStyle(n).color)).not.toBe(flare);
  });

  test("on a phone, the replay's map is on screen above the timeline without scrolling", async ({ page, isMobile }) => {
    test.skip(!isMobile, "phone layout");
    await page.goto("/replay?step=40");
    const chart = page.locator("[data-replay] figure").first();
    const bar = page.getByRole("region", { name: "Replay timeline" });
    const [c, b] = [await chart.boundingBox(), await bar.boundingBox()];
    expect(c && b).toBeTruthy();
    expect(c!.y).toBeLessThan(b!.y - 120);      // at least 120px of the map shows above the sticky timeline
  });

  test("the walkthrough paints its frame before the data and shows step content only after verification", async ({ page, request }) => {
    const html = await (await request.get("/walkthrough")).text();
    expect(html).toContain("The crisis");
    expect(html).toContain("walkthrough-pending");
    expect(html).not.toMatch(/cu, (degraded|ok|down)/);
    await page.goto("/walkthrough");
    await expect(page.getByTestId("walkthrough-pending")).toHaveCount(0);
    await expect(page.getByText(/cu, degraded/).first()).toBeVisible();
  });
});

test.describe("sound: fallback and voicing for real speakers", () => {
  test("without the Web Audio API the control says so, and nothing else breaks", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.addInitScript(() => {
      const w = window as unknown as Record<string, unknown>;
      delete w.AudioContext; delete w.webkitAudioContext;
      Object.defineProperty(window, "AudioContext", { value: undefined, configurable: true });
    });
    await page.goto("/audit");
    const toggle = page.getByTestId("sound-toggle");
    await expect(toggle).toHaveAccessibleName("Sound unavailable");
    await expect(toggle).toHaveAttribute("aria-disabled", "true");
    await toggle.click({ force: true });      // a visitor can still press it: nothing happens, nothing breaks
    await expect(page.getByTestId("audit-result")).toContainText("127 / 127 records rehashed");
    await expect(page.locator("html")).toHaveAttribute("data-sound", "unavailable");
    expect(errors).toEqual([]);
  });

  test("if the browser refuses to create an audio context, the click fails safely into 'unavailable'", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      (window as unknown as { AudioContext: unknown }).AudioContext = class { constructor() { throw new Error("blocked"); } };
    });
    await page.goto("/");
    const toggle = page.getByTestId("sound-toggle");
    await expect(toggle).toHaveAccessibleName("Sound");
    await toggle.click();
    await expect(toggle).toHaveAccessibleName("Sound unavailable");
    expect(errors).toEqual([]);
  });

  test("every mood keeps the chord within 8 dB on a phone-sized speaker band, understated and well below clipping", async ({ page }) => {
    await page.goto("/audit");
    await page.waitForFunction(() => (window as unknown as { __linkdownSound?: { preview?: unknown } }).__linkdownSound?.preview);
    const cap = await audioCapability(page);
    // An engine that can play the score must also let us measure it; only an engine with no Web Audio API at all
    // has nothing to measure (it plays nothing, and its fallback is asserted in the tests above and below).
    if (cap.live) expect(cap.offline, "this engine plays audio but has no OfflineAudioContext: voicing cannot be verified").toBe(true);
    test.skip(!cap.live && !cap.offline, "No Web Audio API in this engine (recorded in the audio-capability annotation): no sound can play, so there is no voicing to measure");
    const results = await page.evaluate(async () => {
      type Preview = (ev: Array<{ at: number; mood: string }>, s: number) => Promise<AudioBuffer>;
      const preview = (window as unknown as { __linkdownSound: { preview: Preview } }).__linkdownSound.preview;
      const db = (x: number) => 20 * Math.log10(Math.max(x, 1e-9));
      const rms = (b: AudioBuffer, from: number) => {
        let s = 0, n = 0;
        for (let c = 0; c < b.numberOfChannels; c++) { const d = b.getChannelData(c); for (let i = from; i < d.length; i++) { s += d[i]! * d[i]!; n++; } }
        return Math.sqrt(s / n);
      };
      const peak = (b: AudioBuffer) => { let p = 0; for (let c = 0; c < b.numberOfChannels; c++) for (const x of b.getChannelData(c)) p = Math.max(p, Math.abs(x)); return p; };
      // A phone-sized speaker: nothing below about 350 Hz (two cascaded second-order high-pass filters).
      const phone = async (b: AudioBuffer) => {
        const ctx = new OfflineAudioContext(b.numberOfChannels, b.length, b.sampleRate);
        const src = ctx.createBufferSource(); src.buffer = b;
        const f1 = ctx.createBiquadFilter(); f1.type = "highpass"; f1.frequency.value = 350;
        const f2 = ctx.createBiquadFilter(); f2.type = "highpass"; f2.frequency.value = 350;
        src.connect(f1).connect(f2).connect(ctx.destination); src.start();
        return ctx.startRendering();
      };
      const out: Record<string, { full: number; phone: number; peak: number }> = {};
      for (const mood of ["calm", "disrupted", "focus", "tension", "verify"]) {
        const b = await preview([{ at: 0, mood }], 12);
        const skip = b.sampleRate * 3;
        out[mood] = { full: db(rms(b, skip)), phone: db(rms(await phone(b), skip)), peak: db(peak(b)) };
      }
      return out;
    });
    for (const [mood, r] of Object.entries(results)) {
      expect(r.phone - r.full, `${mood}: phone band vs full`).toBeGreaterThan(-8);
      expect(r.full, `${mood}: loudness`).toBeGreaterThan(-34);
      expect(r.full, `${mood}: loudness`).toBeLessThan(-20);
      expect(r.peak, `${mood}: peak`).toBeLessThan(-6);
    }
  });

  test("in every engine: no audio context before the click, exactly one after it, and switching off works", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.addInitScript(() => {
      const w = window as unknown as { __acCount: number; AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
      const AC = w.AudioContext ?? w.webkitAudioContext;
      w.__acCount = 0;
      if (!AC) return;                       // no Web Audio API in this engine: nothing to count (checked below)
      w.AudioContext = class extends AC { constructor(o?: AudioContextOptions) { super(o); w.__acCount++; } };
    });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-app", "ready");
    if (!(await audioCapability(page)).live) {
      // No Web Audio API: no context can exist; the control must give the accessible fallback, a press changes
      // nothing, navigation keeps working, and nothing throws.
      await expectUnavailableFallback(page, page.getByTestId("sound-toggle"));
      await page.getByRole("link", { name: "Audit", exact: true }).click();
      await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "verify");
      await expect(page.locator("html")).toHaveAttribute("data-sound", "unavailable");
      expect(errors).toEqual([]);
      return;
    }
    await page.waitForTimeout(800);
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(0);
    await expect(page.locator("html")).toHaveAttribute("data-sound", "off");
    await page.getByTestId("sound-toggle").click();
    // A headless engine may have no audio output, so "paused" is acceptable here; real playback level is
    // measured in Chromium (m3.spec.ts). What must hold everywhere: one context, created by the click.
    await expect(page.locator("html")).toHaveAttribute("data-sound", /^(on|paused)$/);
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(1);
    await page.getByRole("link", { name: "Audit", exact: true }).click();
    await expect(page.locator("html")).toHaveAttribute("data-sound-mood", "verify");
    expect(await page.evaluate(() => (window as unknown as { __acCount: number }).__acCount)).toBe(1);
    if ((await page.locator("html").getAttribute("data-sound")) === "on") {
      await page.getByTestId("sound-toggle").click();
      await expect(page.locator("html")).toHaveAttribute("data-sound", "off");
    }
    expect(errors).toEqual([]);
  });
});

test.describe("M3.1 review fixes: truthfulness, story consequences, deep links", () => {
  test("Act IV draws the recorded consequences on the map and shows every proposal as a token", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    const e2 = page.locator('article[data-chapter="e2"]');
    await e2.scrollIntoViewIfNeeded();
    await e2.evaluate((el) => el.scrollIntoView({ block: "center" }));
    const chart = page.locator("section[aria-label='How the exercise unfolds'] figure").first();
    await expect(chart.locator('[data-overlay="moved"]')).toHaveCount(1);
    await expect(chart.locator('[data-overlay="held"]')).toHaveCount(1);
    const lanes = page.getByRole("definition").filter({ has: page.locator("i") });
    expect(await lanes.count()).toBeGreaterThan(0);
    const outcomes = page.locator('article[data-chapter="outcomes"]');
    await expect(outcomes).toContainText("Nothing was prohibited, and that is the point");
    await expect(outcomes.locator("[data-o=PERMITTED] i")).toHaveCount(15);
    await expect(outcomes.locator("[data-o=INSUFFICIENT_AUTHORITY_OR_EVIDENCE] i")).toHaveCount(4);
  });

  test("before the first event, the map shows no consequence overlays", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    const chart = page.locator("section[aria-label='How the exercise unfolds'] figure").first();
    await expect(chart).toBeVisible();
    await expect(chart.locator("[data-overlay]")).toHaveCount(0);
  });

  test("on a phone, Experience the story lands the act heading below the sticky map, not under it", async ({ page, isMobile }) => {
    test.skip(!isMobile, "phone layout");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    const h2 = page.locator("#act-1 h2");
    await expect(h2).toBeFocused();
    await page.waitForTimeout(400);
    const sticky = await page.locator("section[aria-label='How the exercise unfolds'] figure").first().evaluate((el) => el.closest("div")!.parentElement!.getBoundingClientRect().bottom);
    const top = (await h2.boundingBox())!.y;
    expect(top).toBeGreaterThanOrEqual(sticky - 2);
  });

  test("the simulated controller's refusals are labelled as its policy, not a judgement, wherever they appear", async ({ page }) => {
    await page.goto("/walkthrough?s=4");
    await expect(page.getByTestId("walkthrough-step")).toContainText("by policy it never decides authority questions");
    await expect(page.getByTestId("walkthrough-step")).toContainText(/recommendation, proposed just before the order, stays recorded \(record #\d+\)/);
    await expect(page.getByTestId("walkthrough-step")).not.toContainText("recommendation stands");
    await page.goto("/walkthrough?s=3");
    const gate = page.getByTestId("gate-explainer");
    await expect(gate.getByTestId("gate-stage")).toBeVisible();              // stepped, not all at once
    for (let k = 0; k < 2; k++) await gate.getByRole("button", { name: /^Next:/ }).click();
    await expect(gate.getByTestId("gate-stage")).toContainText("Permitted, but needs the controller");
    await expect(gate.getByTestId("gate-stage")).toContainText("note only");
  });

  test("a record-only action reads as recorded, never as carried out", async ({ page }) => {
    // Record #86 is the regulator's recommendation being recorded (ACTION_RESULT, "recorded": true).
    // Follow it to the gate decision it follows, then open that decision's evidence from the replay.
    await page.goto("/audit?record=86");
    const rec = page.locator("#record-86");
    await expect(rec.locator("details")).toHaveAttribute("open", "");
    const gateLink = rec.getByRole("link", { name: /Gate decision it follows #(\d+)/ });
    const gateSeq = (await gateLink.innerText()).match(/#(\d+)/)![1];
    await page.goto(`/audit?record=${gateSeq}`);
    await page.locator(`#record-${gateSeq}`).getByRole("link", { name: /^Step \d+ in the replay$/ }).click();
    await page.getByRole("button", { name: "Open the evidence for this decision" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Recorded only");
    await expect(dialog).toContainText("Nothing in the network changed");
    await expect(dialog.getByRole("img")).toHaveAttribute("aria-label", /record only; nothing in the network changed/);
    await expect(dialog.getByTestId("drawer-records").getByRole("link", { name: /gate decision #\d+/ })).toBeVisible();
  });

  test("links to a record or step that does not exist say so", async ({ page }) => {
    await page.goto("/audit?record=9999");
    await expect(page.getByTestId("bad-record")).toContainText("There is no record 9999 in this run: it has 127 records");
    await page.goto("/walkthrough?s=99");
    await expect(page.getByTestId("bad-step")).toContainText("There is no step 99");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("The crisis");
  });

  test("the audit page does not present its own anchor list as independent proof", async ({ page }) => {
    await page.goto("/audit");
    await expect(page.getByTestId("audit-result")).toContainText("records rehashed");
    const note = page.getByTestId("anchor-note");
    const anchors = (await (await page.request.get("/bundles/anchors.json")).json()).anchors as Record<string, unknown>;
    if (Object.keys(anchors).length > 0) {
      await expect(note).toContainText("is a pointer, not proof");
      await expect(note).not.toContainText("It matches.");
    } else {
      // No anchor list in this build (public repository): the page must say so and claim no anchor at all.
      await expect(page.getByText("Not available in this build.")).toBeVisible();
      await expect(note).toHaveCount(0);
      await expect(page.locator("main")).not.toContainText("It matches.");
    }
  });
});

test.describe("M3.1 final review: wording that matches what the checks show", () => {
  test("no page claims more than the in-browser check shows; simulated refusals are never a bare 'rejected'", async ({ page }) => {
    await page.goto("/replay?step=53");
    await expect(page.getByTestId("verification")).toContainText("agree with the chain");
    await expect(page.locator("body")).not.toContainText("none altered");
    await expect(page.locator("aside")).not.toContainText("simulated human rejected");
    await page.goto("/walkthrough?s=5");
    await expect(page.getByTestId("walkthrough-step")).toContainText("provided the head matches a copy kept outside this site");
    await page.goto("/audit");
    await expect(page.getByTestId("anchor-access")).toContainText("judges cannot open the anchor commit");
  });

  test("a legal note whose source is unchecked is hedged like the rules that are downgraded", async ({ page }) => {
    await page.goto("/walkthrough?s=3");
    const gate = page.getByTestId("gate-explainer");
    for (let k = 0; k < 2; k++) await gate.getByRole("button", { name: /^Next:/ }).click();
    const note = gate.locator("li", { hasText: "L-PDPL-ART2" });
    await expect(note).toContainText("Its source has not been checked against the primary text.");
    await expect(gate.getByTestId("gate-stage")).not.toContainText("escalates to a human");
  });

  test("every page names itself, in the prerendered HTML and after navigation", async ({ page, request }) => {
    for (const [path, title] of [["/", "LinkDown: when the cables go dark"], ["/audit", "Audit record · LinkDown"], ["/walkthrough", "Judge walkthrough · LinkDown"], ["/replay", "Replay · LinkDown"]] as const) {
      expect(await (await request.get(path)).text()).toContain(`<title>${title}`);
    }
    await page.goto("/audit");
    await expect(page).toHaveTitle("Audit record · LinkDown");
    await page.getByRole("link", { name: "Replay", exact: true }).click();
    await expect(page).toHaveTitle("Replay · LinkDown");
    await page.goto("/nope");
    await expect(page).toHaveTitle("Link not found · LinkDown");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("This link is down");
  });

  test("replay addresses with a step or role that does not exist say so", async ({ page }) => {
    await page.goto("/replay?step=999&role=king");
    const note = page.getByTestId("bad-address");
    await expect(note).toContainText("There is no step 999: this replay has 81 steps, so it opens at step 81.");
    await expect(note).toContainText("There is no role called king");
  });

  test("a deep link to a record puts keyboard focus on that record", async ({ page }) => {
    await page.goto("/audit?record=52");
    await expect(page.locator("#record-52 summary")).toBeFocused();
  });
});

test.describe("M3.1 truthfulness sweep: what executed actions did, and what the controller is", () => {
  test("record-only actions are never titled 'carried out', and counts separate changes from records", async ({ page }) => {
    await page.goto("/audit?record=9");
    await page.locator("#record-9").getByRole("link", { name: /^Step \d+ in the replay$/ }).click();
    await expect(page.locator("h1")).toHaveText(/^Recorded only: /);
    await expect(page.locator("article").first()).toContainText("Nothing in the network changed.");
    await page.goto("/replay?step=81");
    await expect(page.locator("article").first()).toContainText(/executed: 1 changed the exercise state, 2 recorded only/);
    await page.goto("/");
    await page.getByRole("button", { name: "Experience the story" }).click();
    await expect(page.locator('article[data-chapter="outcomes"]')).toContainText("One action changed the exercise state (the service's AI endpoint), and two were only recorded. None changed the network itself.");
  });

  test("recorded 'human controller' wording is marked as the simulated policy it was in this run", async ({ page }) => {
    await page.goto("/walkthrough?s=4");
    await expect(page.getByTestId("walkthrough-step")).toContainText("Recorded wording. In this run the exercise controller is a simulated policy, not a person.");
  });
});

test.describe("M3.1 final independent review fixes", () => {
  test("the replay side panel never shows a decision recorded after the current step", async ({ page }) => {
    // Record #52 is the escalated transfer; the controller's answer is record #53.
    await page.goto("/audit?record=52");
    await page.locator("#record-52").getByRole("link", { name: /^Step \d+ in the replay$/ }).click();
    const side = page.getByRole("complementary", { name: "Role views" });
    await expect(side).toContainText("0 decisions by the simulated controller so far");
    await expect(side).not.toContainText("simulated controller: not approved");
    await page.getByRole("button", { name: "Next step" }).click();
    await expect(side).toContainText("simulated controller: not approved, by policy");
  });

  test("flagged citations are described as the one planted citation they are", async ({ page }) => {
    await page.goto("/walkthrough?s=6");
    await expect(page.getByTestId("walkthrough-step")).toContainText("All 4 are the same citation, made-up#c999, which is not in the knowledge base: the scripted client is written to cite it");
  });

  test("arrow keys inside the Decision Gate step the gate, not the walkthrough", async ({ page }) => {
    await page.goto("/walkthrough?s=3");
    const next = page.getByTestId("gate-explainer").getByRole("button", { name: /^Next:/ });
    await next.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page).toHaveURL(/s=3/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("A proposal meets the gate");
  });

  test("the binding order is shown as escalated each time it was proposed, and nothing reads as carried out", async ({ page }) => {
    await page.goto("/walkthrough?s=4");
    await expect(page.getByTestId("walkthrough-step")).toContainText("each time it is proposed (records #87 and #112)");
    await expect(page.getByTestId("walkthrough-step")).toContainText("A fixed exercise rule (ER-REG-ORDER)");
    await expect(page.getByTestId("walkthrough-step").getByRole("img").first()).toContainText("not carried out");
  });

  test("the audit and Act V state the outside-head condition for what a valid chain shows", async ({ page }) => {
    await page.goto("/audit");
    await expect(page.locator("body")).toContainText("only the outside copy of the head catches that");
    await expect(page.locator("body")).not.toContainText("unchanged since they were written");
  });
});

test.describe("prerendered shells cannot be pressed before the app takes over", () => {
  test("no prerendered page contains an enabled button; after mount they are enabled", async ({ page, request }) => {
    for (const path of ["/", "/walkthrough", "/audit", "/replay"]) {
      const html = await (await request.get(path)).text();
      const buttons = html.match(/<button\b[^>]*>/g) ?? [];
      expect(buttons.filter((b) => !/\sdisabled(=|\s|>)/.test(b)), path).toEqual([]);
    }
    await page.goto("/walkthrough");
    await expect(page.locator("html")).toHaveAttribute("data-app", "ready");
    if ((await audioCapability(page)).live) await expect(page.getByTestId("sound-toggle")).toBeEnabled();
    else await expectUnavailableFallback(page, page.getByTestId("sound-toggle"));   // no Web Audio: focusable, inert, explained
    await expect(page.getByRole("button", { name: /^Next:/ })).toBeEnabled();
  });
});

test.describe("submitted-build review: wording the record supports", () => {
  test("no unsupported claims about speed, sequence, the network, or the law", async ({ page }) => {
    await page.goto("/walkthrough?s=3");
    await expect(page.getByTestId("walkthrough-step")).not.toContainText("at once");
    const gate = page.getByTestId("gate-explainer");
    for (let k = 0; k < 2; k++) await gate.getByRole("button", { name: /^Next:/ }).click();
    await expect(gate.locator("li", { hasText: "L-PDPL-ART2" })).toContainText("The rule records:");
    await page.goto("/walkthrough?s=4");
    await expect(page.getByTestId("walkthrough-step")).not.toContainText("recorded instead");
    await page.goto("/");
    await expect(page.locator("body")).not.toContainText("in seconds");
  });
});
