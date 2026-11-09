import "./lib/zodConfig";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/newsreader/300.css";
import "@fontsource/newsreader/400.css";
import "@fontsource/newsreader/400-italic.css";
import "./design/tokens.css";
import { lazy, StrictMode, Suspense, type ComponentType } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Layout } from "./components/Layout";
import { Landing } from "./pages/Landing";
import { NotFound } from "./pages/NotFound";
import { Loading } from "./components/StateViews";

// Route pages are split from the main chunk. The page a visitor lands on is loaded before the first
// render, so the prerendered shell (see prerender.tsx) is never replaced by a loading screen.
type PageName = "replay" | "audit" | "walkthrough";
const loaders: Record<PageName, () => Promise<ComponentType>> = {
  replay: () => import("./pages/Replay").then((m) => m.Replay),
  audit: () => import("./pages/Audit").then((m) => m.Audit),
  walkthrough: () => import("./pages/Walkthrough").then((m) => m.Walkthrough),
};
const loaded: Partial<Record<PageName, ComponentType>> = {};
const lazyPage = (n: PageName) => lazy(() => loaders[n]().then((C) => { loaded[n] = C; return { default: C }; }));
const lazies: Record<PageName, ComponentType> = { replay: lazyPage("replay"), audit: lazyPage("audit"), walkthrough: lazyPage("walkthrough") };

function Page({ name }: { name: PageName }) {
  const Ready = loaded[name];
  if (Ready) return <Ready />;
  const Lazy = lazies[name];
  return <Suspense fallback={<Loading progress={null} label="Loading" />}><Lazy /></Suspense>;
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Landing /> },
      { path: "replay", element: <Page name="replay" /> },
      { path: "replay/:bundleId", element: <Page name="replay" /> },
      { path: "audit", element: <Page name="audit" /> },
      { path: "walkthrough", element: <Page name="walkthrough" /> },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

async function start() {
  const container = document.getElementById("root")!;
  const first = location.pathname.split("/")[1] as PageName;
  if (first in loaders) {
    try { loaded[first] = await loaders[first](); } catch { /* fall back to the lazy path, which shows its own error */ }
  }
  // Let the browser paint the prerendered shell before the app takes over the same markup.
  if (container.childElementCount > 0) await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
  createRoot(container).render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  );
}
void start();
