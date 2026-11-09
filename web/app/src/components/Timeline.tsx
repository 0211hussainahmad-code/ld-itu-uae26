import { useEffect } from "react";
import { formatSimTime, type Replay } from "../lib/replay";
import { Term } from "./Term";
import s from "./Timeline.module.css";

export const SPEEDS = [1, 2, 4] as const;

interface Props {
  replay: Replay;
  index: number;
  playing: boolean;
  speed: number;
  onIndex: (i: number) => void;
  onPlaying: (p: boolean) => void;
  onSpeed: (s: number) => void;
}

export function Timeline({ replay, index, playing, speed, onIndex, onPlaying, onSpeed }: Props) {
  const last = replay.steps.length - 1;
  const step = replay.steps[index]!;
  const total = replay.records.length;

  // Playback: one step per tick; stops at the end.
  useEffect(() => {
    if (!playing) return;
    if (index >= last) { onPlaying(false); return; }
    const t = setTimeout(() => onIndex(index + 1), 1400 / speed);
    return () => clearTimeout(t);
  }, [playing, index, speed, last, onIndex, onPlaying]);

  // Keyboard: arrows step, space plays or pauses, Home/End jump. Ignored while typing or in dialogs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, select, textarea, dialog, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (el.getAttribute("role") === "button" && (e.key === " " || e.key === "Enter")) return;
      if (e.repeat && e.key === " ") return;
      if (el.closest('[role="group"], [role="tablist"], details, summary')) return;
      if (e.key === "ArrowRight") { e.preventDefault(); onPlaying(false); onIndex(Math.min(last, index + 1)); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); onPlaying(false); onIndex(Math.max(0, index - 1)); }
      else if (e.key === "Home") { e.preventDefault(); onPlaying(false); onIndex(0); }
      else if (e.key === "End") { e.preventDefault(); onPlaying(false); onIndex(last); }
      else if (e.key === " " && el.tagName !== "BUTTON") { e.preventDefault(); onPlaying(!playing); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, last, playing, onIndex, onPlaying]);

  const pct = (i: number) => (last ? (i / last) * 100 : 0);
  return (
    <section className={s.bar} aria-label="Replay timeline">
      <div className={s.controls}>
        <button type="button" className="icon-btn" onClick={() => { onPlaying(false); onIndex(0); }} aria-label="Go to start" disabled={index === 0}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 4v12M16 4l-8 6 8 6z" /></svg>
        </button>
        <button type="button" className="icon-btn" onClick={() => { onPlaying(false); onIndex(Math.max(0, index - 1)); }} aria-label="Previous step" disabled={index === 0}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M13 4l-7 6 7 6z" /></svg>
        </button>
        <button type="button" className={`icon-btn ${s.play}`} onClick={() => { if (index >= last) onIndex(0); onPlaying(!playing); }}
          aria-label={playing ? "Pause" : "Play"} aria-pressed={playing}>
          {playing ? <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 4h3v12H6zM11 4h3v12h-3z" /></svg>
            : <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 4l10 6-10 6z" /></svg>}
        </button>
        <button type="button" className="icon-btn" onClick={() => { onPlaying(false); onIndex(Math.min(last, index + 1)); }} aria-label="Next step" disabled={index === last}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 4l7 6-7 6z" /></svg>
        </button>
        <button type="button" className="icon-btn" onClick={() => { onPlaying(false); onIndex(last); }} aria-label="Go to end" disabled={index === last}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15 4v12M4 4l8 6-8 6z" /></svg>
        </button>
        <label className={s.speed}>
          <span className="visually-hidden">Playback speed</span>
          <select value={speed} onChange={(e) => onSpeed(Number(e.target.value))}>
            {SPEEDS.map((v) => <option key={v} value={v}>{v}×</option>)}
          </select>
        </label>
      </div>

      <div className={s.trackWrap}>
        <div className={s.events}>
          {replay.events.map((e) => (
            <button key={e.id} type="button" className={s.eventBtn} style={{ left: `${pct(e.stepIndex)}%` }}
              data-active={step.eventId === e.id || undefined}
              onClick={() => { onPlaying(false); onIndex(e.stepIndex); }}
              aria-label={`Jump to event ${e.id.replace("E", "")}: ${e.title}`}>
              <span>Event {e.id.replace("E", "")}</span>
            </button>
          ))}
        </div>
        <div className={s.track} aria-hidden="true">
          {replay.steps.map((st) => <i key={st.seq} data-k={st.kind} style={{ left: `${pct(st.index)}%` }} data-past={st.index <= index || undefined} />)}
          <b className={s.fill} style={{ width: `${pct(index)}%` }} />
        </div>
        <input className={s.range} type="range" min={0} max={last} step={1} value={index}
          onChange={(e) => { onPlaying(false); onIndex(Number(e.target.value)); }}
          aria-label="Replay position" aria-valuetext={`Step ${index + 1} of ${last + 1}, record ${step.seq} of ${total}: ${step.title}`} />
      </div>

      <p className={s.readout}>
        <code>{formatSimTime(step.simMin)}</code>
        <span>Step {index + 1} of {last + 1}</span>
        <span className={s.keys}>
          record #{step.seq} of {total}{" "}
          <Term tip={`The replay shows ${last + 1} of the ${total} audit records as steps. The other ${total - last - 1} are bookkeeping kept for every scripted turn (a call record and a turn-file check). They are verified in the same chain and listed on the audit page.`}>Why two counts</Term>
        </span>
      </p>
    </section>
  );
}
