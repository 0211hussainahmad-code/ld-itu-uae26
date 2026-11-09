// LinkDown sound layer: an original score synthesised in the browser with the Web Audio API.
// No audio files, samples or third-party music: every sound below is generated from oscillators,
// filtered noise and short envelopes written for this project, so there is nothing to license.
//
// Rules (M3 directive, section 7):
//  - Never audible before an explicit user action: the AudioContext is created only inside enable(),
//    which is called from a click handler. A reload never resumes sound on its own.
//  - Browsers without the Web Audio API get an explicit "unavailable" state, never an exception.
//  - One engine for the whole site, so navigation never stacks tracks.
//  - Every level change is a smooth ramp; cues are short, quiet and rate-limited.
//  - Suspended while the page is hidden; resumed only if the visitor had sound on.
//  - Nothing essential depends on sound: every mood and cue mirrors something already on screen.
//
// Voicing for real speakers (M3.1). A low drone alone is close to silent on phones and thin on
// laptops, whose speakers barely reproduce anything under 150-350 Hz. So the score has three layers:
//   sub   a sine on the root, felt on headphones and good speakers;
//   body  the same chord an octave up on slightly detuned sawtooth pairs, panned apart, through a
//         slowly breathing low-pass filter: its harmonics carry the chord on small speakers
//         (and imply the root, which the ear fills in);
//   air   filtered noise with a slow swell, like distant water: the subsea setting, very quiet.
// Plus sonar pings through a soft echo, and cues for story events.
//
// Moods map to the story (one per act or replay situation):
//   calm      normal connectivity     open fifth, slow sonar ping, warm and open
//   disrupted cable failure           the fifth narrows to a minor sixth, irregular ping, a low tremor, rougher water
//   focus     reading a role's view   quieter and darker, no ping
//   tension   authority uncertainty   a soft minor second against the octave, slower and lower ping
//   verify    audit verification      a major chord, bright and still: resolved

export type Mood = "calm" | "disrupted" | "focus" | "tension" | "verify";
/** break: a link fails. hold: a proposal is stopped at the gate. ok / fail: a verification result. */
export type Cue = "break" | "hold" | "ok" | "fail";

interface MoodSpec {
  second: number; third: number;        // chord ratios above the root
  cutoff: number;                       // body filter, Hz
  sub: number; body: number; air: number; airHz: number;
  tremor: number; ping: number | null; pingHz: number; jitter: number;
}
const ROOT = 110;  // A2
const MOODS: Record<Mood, MoodSpec> = {
  calm:      { second: 1.5,   third: 2,     cutoff: 1400, sub: 0.07, body: 0.40, air: 0.022, airHz: 1700, tremor: 0,    ping: 7.5, pingHz: 660, jitter: 0 },
  disrupted: { second: 1.587, third: 1.888, cutoff: 1000, sub: 0.07, body: 0.40, air: 0.036, airHz: 1100, tremor: 0.12, ping: 5.2, pingHz: 622, jitter: 0.55 },
  focus:     { second: 1.5,   third: 2,     cutoff: 800,  sub: 0.05, body: 0.30, air: 0.012, airHz: 1400, tremor: 0,    ping: null, pingHz: 660, jitter: 0 },
  tension:   { second: 1.5,   third: 1.06,  cutoff: 1100, sub: 0.065, body: 0.37, air: 0.022, airHz: 1250, tremor: 0.04, ping: 10,  pingHz: 440, jitter: 0.2 },
  verify:    { second: 1.5,   third: 2.5,   cutoff: 2200, sub: 0.05, body: 0.34, air: 0.015, airHz: 2400, tremor: 0,    ping: 9,   pingHz: 990, jitter: 0 },
};
export const MOOD_NAMES = Object.keys(MOODS) as Mood[];

type AudioCtor = typeof AudioContext;
function audioCtor(): AudioCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { AudioContext?: AudioCtor; webkitAudioContext?: AudioCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

// ---------------------------------------------------------------------------------------------
// The graph. Built on any BaseAudioContext, so the same score renders live or offline (previews).

interface Graph {
  master: GainNode;
  analyser: AnalyserNode;
  setMood(m: Mood, tc: number, at?: number): void;
  ping(spec: MoodSpec, at: number): void;
  cue(c: Cue, at: number): void;
}

function noiseBuffer(ctx: BaseAudioContext): AudioBuffer {
  // Deterministic noise (a small linear congruential generator), so previews are reproducible.
  const len = ctx.sampleRate * 4, buf = ctx.createBuffer(1, len, ctx.sampleRate), d = buf.getChannelData(0);
  let x = 0x2545f491;
  for (let i = 0; i < len; i++) { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; d[i] = (x / 0xffffffff) * 2 - 1; }
  return buf;
}

function pan(ctx: BaseAudioContext, value: number): AudioNode {
  if (typeof ctx.createStereoPanner !== "function") return ctx.createGain();
  const p = ctx.createStereoPanner(); p.pan.value = value; return p;
}

function buildGraph(ctx: BaseAudioContext, mood: Mood): Graph {
  const spec0 = MOODS[mood];
  const master = ctx.createGain(); master.gain.value = 0;
  const hp = ctx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 32; hp.Q.value = 0.7;
  const comp = ctx.createDynamicsCompressor();
  comp.threshold.value = -22; comp.knee.value = 12; comp.ratio.value = 3; comp.attack.value = 0.02; comp.release.value = 0.5;
  const analyser = ctx.createAnalyser(); analyser.fftSize = 2048;
  master.connect(hp).connect(comp).connect(analyser).connect(ctx.destination);

  // Everything sustained goes through `bed`, which the tremor modulates.
  const bed = ctx.createGain(); bed.gain.value = 1; bed.connect(master);
  const trem = ctx.createOscillator(); trem.frequency.value = 3.1;
  const tremAmt = ctx.createGain(); tremAmt.gain.value = spec0.tremor;
  trem.connect(tremAmt).connect(bed.gain); trem.start();

  // Sub.
  const sub = ctx.createOscillator(); sub.type = "sine"; sub.frequency.value = ROOT;
  const subGain = ctx.createGain(); subGain.gain.value = spec0.sub;
  sub.connect(subGain).connect(bed); sub.start();

  // Body: root octave, chord second and third, each as a detuned sawtooth pair panned apart.
  const filter = ctx.createBiquadFilter(); filter.type = "lowpass"; filter.Q.value = 0.5; filter.frequency.value = spec0.cutoff;
  const bodyGain = ctx.createGain(); bodyGain.gain.value = spec0.body;
  filter.connect(bodyGain).connect(bed);
  const lfo = ctx.createOscillator(); lfo.frequency.value = 0.045;
  const lfoAmt = ctx.createGain(); lfoAmt.gain.value = 180;
  lfo.connect(lfoAmt).connect(filter.frequency); lfo.start();
  // Voicing: a quiet root octave, then the chord's second and third and the second an octave higher,
  // so most of the chord sits between 300 and 700 Hz, where small speakers work.
  const ratios = (s: MoodSpec) => [2, s.second * 2, s.third * 2, s.second * 4];
  const levels = [0.16, 0.32, 0.3, 0.16];
  const voices = ratios(spec0).map((r, i) => [-1, 1].map((side) => {
    const o = ctx.createOscillator(); o.type = "sawtooth"; o.frequency.value = ROOT * r; o.detune.value = side * (5 + i * 2);
    const g = ctx.createGain(); g.gain.value = levels[i]! / 2;
    o.connect(g).connect(pan(ctx, side * 0.35)).connect(filter); o.start();
    return o;
  }));

  // Air: band-passed noise with a slow swell.
  const noise = ctx.createBufferSource(); noise.buffer = noiseBuffer(ctx); noise.loop = true;
  const band = ctx.createBiquadFilter(); band.type = "bandpass"; band.Q.value = 0.6; band.frequency.value = spec0.airHz;
  const airGain = ctx.createGain(); airGain.gain.value = spec0.air;
  const swell = ctx.createOscillator(); swell.frequency.value = 0.07;
  const swellAmt = ctx.createGain(); swellAmt.gain.value = spec0.air * 0.45;
  swell.connect(swellAmt).connect(airGain.gain); swell.start();
  noise.connect(band).connect(airGain).connect(pan(ctx, -0.15)).connect(bed); noise.start();

  // Pings and cues share a soft echo.
  const fx = ctx.createGain(); fx.gain.value = 1; fx.connect(master);
  const delay = ctx.createDelay(2); delay.delayTime.value = 0.42;
  const fb = ctx.createGain(); fb.gain.value = 0.32;
  const wet = ctx.createGain(); wet.gain.value = 0.45;
  fx.connect(delay); delay.connect(fb).connect(delay); delay.connect(wet).connect(pan(ctx, 0.3)).connect(master);

  const tone = (freq: number, at: number, dur: number, peak: number, type: OscillatorType = "sine") => {
    const o = ctx.createOscillator(); o.type = type; o.frequency.value = freq;
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(peak, at + 0.025);
    g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    o.connect(g).connect(fx);
    o.start(at); o.stop(at + dur + 0.05);
  };

  return {
    master, analyser,
    setMood(m, tc, at = ctx.currentTime) {
      const s = MOODS[m];
      ratios(s).forEach((r, i) => voices[i]!.forEach((o) => o.frequency.setTargetAtTime(ROOT * r, at, tc)));
      filter.frequency.setTargetAtTime(s.cutoff, at, tc);
      subGain.gain.setTargetAtTime(s.sub, at, tc);
      bodyGain.gain.setTargetAtTime(s.body, at, tc);
      airGain.gain.setTargetAtTime(s.air, at, tc);
      swellAmt.gain.setTargetAtTime(s.air * 0.45, at, tc);
      band.frequency.setTargetAtTime(s.airHz, at, tc);
      tremAmt.gain.setTargetAtTime(s.tremor, at, tc);
    },
    ping(s, at) {
      tone(s.pingHz, at, 1.9, 0.07);
      tone(s.pingHz * 2.01, at, 0.6, 0.018);
    },
    cue(c, at) {
      if (c === "break") { tone(392, at, 0.6, 0.11, "triangle"); tone(330, at + 0.3, 1.1, 0.1, "triangle"); tone(110, at, 1.4, 0.12); }
      if (c === "hold") { tone(440, at, 0.5, 0.07, "triangle"); tone(415.3, at + 0.22, 0.9, 0.065, "triangle"); }
      if (c === "ok") { tone(587.3, at, 0.7, 0.08); tone(880, at + 0.16, 1.2, 0.07); }
      if (c === "fail") { tone(196, at, 0.5, 0.12, "triangle"); tone(185, at + 0.2, 0.7, 0.1, "triangle"); }
    },
  };
}

// ---------------------------------------------------------------------------------------------
// The live engine.

const STORE = "linkdown-sound";
type Saved = { on: boolean; volume: number };
function load(): Saved {
  try {
    const v = JSON.parse(sessionStorage.getItem(STORE) ?? "null");
    if (v && typeof v.on === "boolean" && typeof v.volume === "number") return { on: v.on, volume: Math.min(1, Math.max(0, v.volume)) };
  } catch { /* storage blocked */ }
  return { on: false, volume: 0.6 };
}
function save(s: Saved) { try { sessionStorage.setItem(STORE, JSON.stringify(s)); } catch { /* ignore */ } }

export type SoundState = "off" | "on" | "paused" | "unavailable";
export interface SoundSnapshot { state: SoundState; volume: number; mood: Mood; wanted: boolean }
type Listener = (s: SoundSnapshot) => void;

const CUE_GAP = 0.7;   // seconds between cues, so fast stepping never turns into a barrage

class SoundEngine {
  private ctx: AudioContext | null = null;
  private graph: Graph | null = null;
  private pingTimer: number | null = null;
  private mood: Mood = "calm";
  private saved = load();
  private failed = false;
  private lastCue = -Infinity;
  private listeners = new Set<Listener>();

  constructor() {
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", () => this.onVisibility());
      this.publish();
    }
  }

  /** False when this browser has no Web Audio API, or creating the audio context failed. */
  get supported() { return !this.failed && audioCtor() !== null; }
  get state(): SoundState {
    if (!this.supported) return "unavailable";
    if (!this.ctx || !this.saved.on) return this.saved.on ? "paused" : "off";
    return this.ctx.state === "running" ? "on" : "paused";
  }
  get volume() { return this.saved.volume; }
  /** True when the visitor turned sound on earlier in this session (a reload needs a new click). */
  get wanted() { return this.saved.on; }

  subscribe(f: Listener) { this.listeners.add(f); f(this.snapshot()); return () => { this.listeners.delete(f); }; }
  /** Read-only diagnostics for browser tests: what the engine believes, and the audio context's own state. */
  debug() { return { ...this.snapshot(), ctx: this.ctx ? this.ctx.state : null, failed: this.failed, enables: this.enables, disables: this.disables }; }
  private enables = 0;
  private disables = 0;
  private snapshot(): SoundSnapshot { return { state: this.state, volume: this.saved.volume, mood: this.mood, wanted: this.saved.on && this.supported }; }
  private publish() {
    const s = this.snapshot();
    if (typeof document !== "undefined") {
      document.documentElement.dataset.sound = s.state;
      document.documentElement.dataset.soundMood = s.mood;
    }
    this.listeners.forEach((f) => f(s));
  }

  /** Call only from a user action (click / key press). Returns false if sound cannot play here. */
  async enable(): Promise<boolean> {
    this.enables++;
    const AC = audioCtor();
    if (!AC || this.failed) { this.publish(); return false; }
    if (!this.ctx) {
      try {
        this.ctx = new AC();
        this.graph = buildGraph(this.ctx, this.mood);
        // The context may start (or stop) later than the click, e.g. when an output device appears.
        this.ctx.onstatechange = () => this.publish();
      } catch {
        this.ctx = null; this.graph = null; this.failed = true;
        this.saved = { ...this.saved, on: false }; save(this.saved);
        this.publish();
        return false;
      }
    }
    this.saved = { ...this.saved, on: true };
    save(this.saved);
    this.fadeMaster(this.saved.volume, 1.2);
    this.graph!.setMood(this.mood, 0.01);
    this.publish();
    // Some engines never settle resume() when there is no audio output; never wait on it indefinitely.
    await Promise.race([this.ctx.resume().catch(() => undefined), new Promise((r) => setTimeout(r, 1500))]);
    this.schedulePing();
    this.publish();
    return this.ctx.state === "running";
  }

  disable() {
    this.disables++;
    this.saved = { ...this.saved, on: false };
    save(this.saved);
    if (this.ctx) {
      this.fadeMaster(0, 0.35);
      const ctx = this.ctx;
      window.setTimeout(() => { if (!this.saved.on) ctx.suspend().catch(() => undefined).then(() => this.publish()); }, 600);
    }
    this.clearPing();
    this.publish();
  }

  setVolume(v: number) {
    this.saved = { ...this.saved, volume: Math.min(1, Math.max(0, v)) };
    save(this.saved);
    if (this.ctx && this.saved.on) this.fadeMaster(this.saved.volume, 0.25);
    this.publish();
  }

  setMood(m: Mood) {
    if (m === this.mood) return;
    this.mood = m;
    if (this.graph && this.saved.on) { this.graph.setMood(m, 1.6); this.schedulePing(); }
    this.publish();
  }

  /** A short, quiet cue that mirrors something already shown on screen. Silent unless sound is on. */
  cue(c: Cue) {
    if (!this.ctx || !this.graph || !this.saved.on || this.ctx.state !== "running") return;
    const t = this.ctx.currentTime;
    if (t - this.lastCue < CUE_GAP) return;
    this.lastCue = t;
    this.graph.cue(c, t + 0.02);
  }

  /** RMS of the output, 0..1. Used by browser tests to show that sound is actually playing. */
  level(): number {
    if (!this.graph) return 0;
    const buf = new Float32Array(this.graph.analyser.fftSize);
    this.graph.analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const x of buf) sum += x * x;
    return Math.sqrt(sum / buf.length);
  }

  private fadeMaster(v: number, seconds: number) {
    if (!this.ctx || !this.graph) return;
    const t = this.ctx.currentTime, g = this.graph.master.gain;
    g.cancelScheduledValues(t);
    g.setValueAtTime(g.value, t);
    g.linearRampToValueAtTime(v * 0.5, t + seconds);
  }

  private clearPing() { if (this.pingTimer !== null) { window.clearTimeout(this.pingTimer); this.pingTimer = null; } }
  private schedulePing() {
    this.clearPing();
    const spec = MOODS[this.mood];
    if (!this.ctx || !this.saved.on || spec.ping === null) return;
    const wait = spec.ping * (1 + (Math.random() * 2 - 1) * spec.jitter);
    this.pingTimer = window.setTimeout(() => {
      if (this.ctx && this.graph && this.saved.on && this.ctx.state === "running") this.graph.ping(spec, this.ctx.currentTime + 0.02);
      this.schedulePing();
    }, Math.max(1500, wait * 1000));
  }

  private onVisibility() {
    if (!this.ctx) return;
    if (document.hidden) { this.ctx.suspend().catch(() => undefined).then(() => this.publish()); this.clearPing(); }
    else if (this.saved.on) { this.ctx.resume().catch(() => undefined).then(() => { this.schedulePing(); this.publish(); }); }
  }
}

// ---------------------------------------------------------------------------------------------
// Offline previews: the same graph rendered silently to a buffer (for review files and tests).
// It never touches the live engine or the speakers.

export interface PreviewEvent { at: number; mood?: Mood; cue?: Cue }
export async function renderPreview(events: PreviewEvent[], seconds: number, volume = 0.6, sampleRate = 44100): Promise<AudioBuffer> {
  const ctx = new OfflineAudioContext(2, Math.round(seconds * sampleRate), sampleRate);
  let mood: Mood = events.find((e) => e.mood)?.mood ?? "calm";
  const g = buildGraph(ctx, mood);
  g.master.gain.setValueAtTime(0, 0);
  g.master.gain.linearRampToValueAtTime(volume * 0.5, 1.2);
  const sorted = [...events].sort((a, b) => a.at - b.at);
  for (const e of sorted) {
    if (e.mood && e.at > 0) g.setMood(e.mood, 1.6, e.at);
    if (e.cue) g.cue(e.cue, e.at);
  }
  // Pings on the same schedule the live engine uses (without the random jitter).
  let t = 1.5;
  while (t < seconds) {
    mood = sorted.filter((e) => e.mood && e.at <= t).at(-1)?.mood ?? mood;
    const s = MOODS[mood];
    if (s.ping !== null) g.ping(s, t);
    t += s.ping ?? 2;
  }
  return ctx.startRendering();
}

let engine: SoundEngine | null = null;
export function sound(): SoundEngine {
  if (!engine) {
    engine = new SoundEngine();
    if (typeof window !== "undefined") {
      (window as unknown as { __linkdownSound: unknown }).__linkdownSound = { level: () => engine!.level(), preview: renderPreview, debug: () => engine!.debug() };
    }
  }
  return engine;
}
