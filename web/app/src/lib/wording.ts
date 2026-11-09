// Wording shared by several pages, so a claim is phrased the same way everywhere.

export const AI_RUN_STATUS = "A run with an AI model in all four roles has not been completed or published here. A first attempt, on 6 November 2026, reached 5 of the 12 role and event combinations and did not pass verification, so it is not shown. A further run needs separate authorisation and will be published only after independent verification, under its own label.";

/** Page titles: each page names itself (WCAG 2.4.2). Also written into the prerendered HTML. */
export const TITLES: Record<string, string> = {
  "/": "LinkDown: when the cables go dark, who decides?",
  "/walkthrough": "Judge walkthrough · LinkDown",
  "/replay": "Replay · LinkDown",
  "/audit": "Audit record · LinkDown",
  "404": "Link not found · LinkDown",
};
export function titleFor(pathname: string): string {
  if (pathname === "/") return TITLES["/"]!;
  const first = "/" + (pathname.split("/")[1] ?? "");
  return TITLES[first] ?? TITLES["404"]!;
}

/** The gate's recorded wording sometimes says "human exercise controller"; in a run with the simulated
 *  controller that role is a fixed policy. Returns the note to show beside such recorded text, or null. */
export function simulatedControllerNote(text: string | undefined, simulated: boolean): string | null {
  return simulated && /\bhuman\b/i.test(text ?? "") ? " (Recorded wording. In this run the exercise controller is a simulated policy, not a person.)" : null;
}

/** Flagged citations, described from the records: if every flag is the same planted citation, say so. */
export function flaggedCitations(records: Array<{ kind: string; payload: any }>): string {
  const ids = records.filter((r) => r.kind === "TURN_PARSED").flatMap((r) => (r.payload?.unsupported_citations ?? []) as string[]);
  if (ids.length === 0) return "No citation was flagged as not matching a retrieved passage.";
  const distinct = [...new Set(ids)];
  if (distinct.length === 1 && distinct[0]!.startsWith("made-up")) {
    return `${ids.length} citations did not match a retrieved passage. All ${ids.length} are the same citation, ${distinct[0]}, which is not in the knowledge base: the scripted client is written to cite it, to test the check. They stay visible.`;
  }
  return `${ids.length} citations did not match a retrieved passage (${distinct.join(", ")}). They stay visible.`;
}
