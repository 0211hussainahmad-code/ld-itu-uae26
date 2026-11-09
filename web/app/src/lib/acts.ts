import type { Mood } from "./sound";

// The five acts of the story. The sequence is real (it follows the exercise's own order), so acts are numbered.
export type ActId = 1 | 2 | 3 | 4 | 5;
export const ACTS: Array<{ id: ActId; numeral: string; name: string; mood: Mood }> = [
  { id: 1, numeral: "I", name: "The world beneath", mood: "calm" },
  { id: 2, numeral: "II", name: "The break", mood: "disrupted" },
  { id: 3, numeral: "III", name: "Four minds, four realities", mood: "focus" },
  { id: 4, numeral: "IV", name: "Decisions under pressure", mood: "tension" },
  { id: 5, numeral: "V", name: "The proof", mood: "verify" },
];
