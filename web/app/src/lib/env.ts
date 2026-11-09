// True only while src/prerender.tsx renders the static shells at build time (no window in Node).
// Buttons rendered then have no handlers until the app mounts, so the shells render them disabled:
// nothing on the page can be pressed and silently ignored. Links work natively and stay enabled.
export const PRERENDER = typeof window === "undefined";
