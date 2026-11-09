import { useEffect, useId, useState } from "react";
import { sound, type Mood, type SoundSnapshot } from "../lib/sound";
import s from "./SoundControl.module.css";
import { PRERENDER } from "../lib/env";

/** Sets the score's mood while the calling view is on screen. Does nothing unless sound is on. */
export function useSoundMood(mood: Mood) {
  useEffect(() => { sound().setMood(mood); }, [mood]);
}

const MOOD_TEXT: Record<Mood, string> = {
  calm: "steady signal", disrupted: "disruption", focus: "reading", tension: "authority in question", verify: "verification",
};

export function SoundControl() {
  // First render already shows the engine's real state, so a browser without Web Audio never shows an
  // enabled "Sound" button for a moment before it turns into "Sound unavailable". The prerendered shell
  // (no window) keeps the neutral state; its button is disabled until the app takes over.
  const [st, setSt] = useState<SoundSnapshot>(() => {
    if (PRERENDER) return { state: "off", volume: 0.6, mood: "calm", wanted: false };
    const e = sound();
    return { state: e.state, volume: e.volume, mood: "calm", wanted: e.wanted && e.supported };
  });
  const vid = useId();
  useEffect(() => sound().subscribe(setSt), []);
  const on = st.state === "on";
  if (st.state === "unavailable") {
    // No Web Audio API here (or the browser refused to create an audio context): say so, nothing else changes.
    return (
      <div className={s.wrap} data-state="unavailable">
        <button type="button" className={s.toggle} aria-disabled="true" data-testid="sound-toggle" aria-label="Sound unavailable"
          title="This browser does not support the Web Audio API, so the optional score cannot play. Nothing else depends on it.">
          <svg viewBox="0 0 24 24" aria-hidden="true" className={s.icon}><path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z" /><path d="M15.5 9.5l5 5M20.5 9.5l-5 5" /></svg>
          <span className={s.text}>Sound unavailable</span>
        </button>
      </div>
    );
  }
  // The name matches the visible text; the on/off state is carried by aria-pressed.
  const label = !on && st.wanted ? "Resume sound" : "Sound";
  return (
    <div className={s.wrap} data-state={st.state}>
      <button type="button" className={s.toggle} aria-pressed={on} data-testid="sound-toggle" disabled={PRERENDER || undefined}
        onClick={() => (on ? sound().disable() : sound().enable())}
        aria-label={label} title={on ? "Turn the original ambient score off" : "Play the original ambient score (optional)"}>
        <svg viewBox="0 0 24 24" aria-hidden="true" className={s.icon}>
          <path d="M4 9.5h3.2L12 5.5v13l-4.8-4H4z" />
          {on ? <><path className={s.wave} d="M15.2 9.2a4 4 0 010 5.6" /><path className={s.wave} d="M17.8 6.8a7.4 7.4 0 010 10.4" /></>
            : <path d="M15.5 9.5l5 5M20.5 9.5l-5 5" />}
        </svg>
        <span className={s.text}>{label}</span>
      </button>
      {on && (
        <label className={s.volume} htmlFor={vid}>
          <span className="visually-hidden">Volume</span>
          <input id={vid} type="range" min={0} max={100} step={5} value={Math.round(st.volume * 100)}
            onChange={(e) => sound().setVolume(Number(e.target.value) / 100)} aria-valuetext={`${Math.round(st.volume * 100)} percent`} />
        </label>
      )}
      {/* Announce only when sound is switched, never on every mood change. */}
      <span className="visually-hidden" aria-live="polite">{on ? "Sound on" : ""}</span>
      <span className="visually-hidden" data-testid="sound-mood">{on ? MOOD_TEXT[st.mood] : ""}</span>
    </div>
  );
}
