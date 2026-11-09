// Build-time prerender of each route's static shell (vite.config.ts runs this once per build).
//
// What it renders is only what the page shows before any data arrives: the header, the hero text,
// a page's static heading, and the honest "loading" or "fetching" state. Nothing from a bundle is
// rendered here: data pages always show their verified content only after the browser has rehashed
// it. In the browser, main.tsx renders the app over this markup (no hydration), so the shell is
// simply the first paint.
import { renderToString } from "react-dom/server";
import { Route, Routes, StaticRouter } from "react-router";
import { Layout } from "./components/Layout";
import { Audit } from "./pages/Audit";
import { Landing } from "./pages/Landing";
import { Replay } from "./pages/Replay";
import { Walkthrough } from "./pages/Walkthrough";
export { TITLES } from "./lib/wording";

export const ROUTES = { "/": "index.html", "/replay": "replay.html", "/audit": "audit.html", "/walkthrough": "walkthrough.html" } as const;

export function render(url: keyof typeof ROUTES): string {
  return renderToString(
    <StaticRouter location={url}>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Landing />} />
          <Route path="replay" element={<Replay />} />
          <Route path="audit" element={<Audit />} />
          <Route path="walkthrough" element={<Walkthrough />} />
        </Route>
      </Routes>
    </StaticRouter>,
  );
}
