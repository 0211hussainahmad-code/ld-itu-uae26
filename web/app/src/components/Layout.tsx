import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { loadRelease, type Release } from "../lib/release";
import { SoundControl } from "./SoundControl";
import { titleFor } from "../lib/wording";
import s from "./Layout.module.css";

export function Layout() {
  const [release, setRelease] = useState<Release | null | undefined>(undefined);
  const { pathname } = useLocation();
  useEffect(() => { loadRelease().then(setRelease); }, []);
  useEffect(() => { document.title = titleFor(pathname); }, [pathname]);
  useEffect(() => { document.documentElement.dataset.app = "ready"; }, []);   // the app has taken over the static shell
  const firstPath = useRef(true);
  useEffect(() => {
    if (firstPath.current) { firstPath.current = false; return; }   // on arrival, Tab starts at "Skip to content"
    document.getElementById("main")?.focus({ preventScroll: true }); window.scrollTo(0, 0);
  }, [pathname]);
  const home = pathname === "/";
  return (
    <div className={s.shell} data-home={home || undefined}>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className={s.header}>
        <NavLink to="/" className={s.wordmark} aria-label="LinkDown, home">
          <svg viewBox="0 0 28 28" aria-hidden="true" className={s.glyph}>
            <circle cx="14" cy="14" r="5" /><path d="M2 14h7M19 14h7M14 2v7M14 19v7" />
          </svg>
          LinkDown
        </NavLink>
        <div className={s.right}>
          <nav aria-label="Main" className={s.nav}>
            <NavLink to="/walkthrough" className={({ isActive }) => (isActive ? s.active : undefined)}>Walkthrough</NavLink>
            <NavLink to="/replay" className={({ isActive }) => (isActive ? s.active : undefined)}>Replay</NavLink>
            <NavLink to="/audit" className={({ isActive }) => (isActive ? s.active : undefined)}>Audit</NavLink>
          </nav>
          <SoundControl />
        </div>
      </header>
      <main id="main" className={s.main} tabIndex={-1}>
        <Outlet />
      </main>
      <footer className={s.footer}>
        <p>The network, the service and every number in this exercise are synthetic. The records are the real record of a scripted run.</p>
        <p>The optional score is original and generated in your browser; it never plays until you turn it on.</p>
        <p>
          {release === undefined ? "Checking the release record" : release ? <>Release <code>{release.release_id}</code></> : "Local build: no release record"}
        </p>
      </footer>
    </div>
  );
}
