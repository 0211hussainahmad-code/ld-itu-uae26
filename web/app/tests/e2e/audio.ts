// What this engine really offers for sound, read from the page (never assumed from the browser's name),
// and the accessible fallback a visitor must get when the engine has no Web Audio API at all.
// The capability is recorded on every test that uses it (annotation "audio-capability"), so a report
// shows which branch ran and why. An engine WITH Web Audio must still play: the site may never claim
// "unavailable" there (the tests' existing "on/paused/off" assertions fail if it does).
import { expect, test, type Page } from "./fixtures";
import type { Locator } from "@playwright/test";

export interface AudioCapability {
  AudioContext: boolean; webkitAudioContext: boolean; OfflineAudioContext: boolean; webkitOfflineAudioContext: boolean;
  /** A live audio context can be created (the site's own test: AudioContext ?? webkitAudioContext). */
  live: boolean;
  /** An offline context exists, so the score can be rendered and measured without speakers. */
  offline: boolean;
}

export async function audioCapability(page: Page): Promise<AudioCapability> {
  const c = await page.evaluate(() => {
    const w = window as unknown as Record<string, unknown>;
    const has = (k: string) => typeof w[k] === "function";
    return { AudioContext: has("AudioContext"), webkitAudioContext: has("webkitAudioContext"),
      OfflineAudioContext: has("OfflineAudioContext"), webkitOfflineAudioContext: has("webkitOfflineAudioContext") };
  });
  const cap = { ...c, live: c.AudioContext || c.webkitAudioContext, offline: c.OfflineAudioContext || c.webkitOfflineAudioContext };
  test.info().annotations.push({ type: "audio-capability", description: JSON.stringify(cap) });
  return cap;
}

/** The fallback when the engine has no Web Audio: said plainly, still focusable, inert, and nothing else changes. */
export async function expectUnavailableFallback(page: Page, toggle: Locator) {
  await expect(page.locator("html")).toHaveAttribute("data-sound", "unavailable");
  await expect(toggle).toHaveAccessibleName("Sound unavailable");
  await expect(toggle).toHaveAttribute("aria-disabled", "true");         // aria-disabled, never `disabled`:
  await expect(toggle).not.toHaveAttribute("disabled", /.*/);           // it stays in the keyboard path
  await expect(toggle).not.toHaveAttribute("aria-pressed", /.*/);       // it never claims an on/off state
  await expect(toggle).toHaveAttribute("title", /Web Audio API/);
  await toggle.focus();
  await expect(toggle).toBeFocused();
  for (const key of ["Enter", "Space"]) {
    await page.keyboard.press(key);
    await expect(toggle).toBeFocused();
    await expect(page.locator("html")).toHaveAttribute("data-sound", "unavailable");
  }
}
