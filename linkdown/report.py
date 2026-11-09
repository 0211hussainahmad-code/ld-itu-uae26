"""Human-readable run report (Markdown) built only from the audit log and report.json."""
from __future__ import annotations

import json
from pathlib import Path

from .audit import verify

LEGAL_LABEL = "UNVERIFIED LEGAL WORDING (model text, not a legal finding)"
REVIEW_LABEL = "NEEDS HUMAN LEGAL REVIEW (cites a verified source; clause applicability not checked)"


def _fmt_args(a: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in (a or {}).items())


def write_markdown(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    recs = [json.loads(l) for l in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ok, msg = verify(run_dir / "audit.jsonl", rep.get("audit_head"))
    m = rep["metrics"]
    L: list[str] = []
    if not rep["is_ai"]:
        L += ["> **TEST DOUBLE - NOT AI.** This run used scripted responses to test the plumbing "
              "(gate, state, audit). It is not evidence of model behaviour.", ""]
    L += [f"# LinkDown run {rep['run_id']}", "",
          f"- Scenario: `{rep['scenario']}` (synthetic)",
          f"- Model: `{rep['model']}` (is_ai={rep['is_ai']})",
          f"- Approvals by: `{rep['human']}`",
          f"- Audit log: {'VERIFIED' if ok else 'FAILED'} ({msg})", "",
          "## Outcome", "",
          f"- Proposals: {m['proposals']} | PERMITTED {m['by_outcome']['PERMITTED']} | "
          f"PROHIBITED {m['by_outcome']['PROHIBITED']} | INSUFFICIENT {m['by_outcome']['INSUFFICIENT_AUTHORITY_OR_EVIDENCE']}",
          f"- Executed: {m['executed']} | human approved {m['human_approved']} | human rejected {m['human_rejected']}",
          f"- Unsafe actions executed: **{m['unsafe_executed']}**",
          f"- Cross-border transfers proposed / executed: {m['cross_border_proposals']} / {m['cross_border_executed']}",
          f"- Citations: source text {m['primary_text_citations']} / analyst notes {m['analyst_note_citations']} / "
          f"unsupported {m['unsupported_citations']}",
          f"- Model sentences with unverified legal wording: {m.get('unverified_legal_wording', 0)} "
          "(listed below; model text, not legal findings)",
          f"- Model calls: {m['model_calls']} (failed {m['model_failed']}), tokens {m['tokens']}, "
          f"latency {m['latency_ms']} ms total",
          f"- Final service: {m.get('final_service')}",
          f"- Final traffic health: {m.get('final_traffic')}", "",
          "## Timeline", "",
          "| seq | T+min | Who | What |", "|---|---|---|---|"]
    for r in recs:
        k, p = r["kind"], r["payload"]
        if k == "EVENT":
            what = f"**EVENT {p['id']}**: {p['title']}"
        elif k == "DELIVERY":
            what = f"delivered to {p['to']} ({p['kind']})"
        elif k == "GATE_DECISION":
            what = f"gate: {p['role']} `{p['tool']}`({_fmt_args(p['args'])}) -> **{p['outcome']}**"
            lead = next((h for h in p["trail"] if h.get("effect") != "note"), None)
            if lead:
                what += f" [{lead['rule_id']}]"
        elif k == "HUMAN_DECISION":
            what = f"{'APPROVED' if p['approved'] else 'REJECTED'} `{p['tool']}` ({p['reason']})"
        elif k in ("STATE_CHANGE", "ACTION_RESULT"):
            what = f"{'state' if k == 'STATE_CHANGE' else 'no state change'}: {p['change']}"
        elif k == "MESSAGE":
            what = f"to {p['to']}: {p['text'][:140]}"
        elif k == "TURN_PARSED" and (p.get("unsupported_citations") or p.get("unverified_legal_wording")):
            parts = []
            if p.get("unsupported_citations"):
                parts.append(f"unsupported citations flagged: {p['unsupported_citations']}")
            if p.get("unverified_legal_wording"):
                parts.append(f"{LEGAL_LABEL}: {len(p['unverified_legal_wording'])} sentence(s)")
            what = "; ".join(parts)
        elif k == "GAP_OBSERVATION":
            what = f"gap {p.get('gap_id')}: {p.get('status')} (draft, needs human review)"
        else:
            continue
        L.append(f"| {r['seq']} | {r['sim_min']} | {r['actor']} | {what.replace('|', '/')} |")
    flagged = [(r, f) for r in recs if r["kind"] == "TURN_PARSED"
               for f in r["payload"].get("unverified_legal_wording") or []]
    L += ["", "## Model statements with legal wording", "",
          "Each line is model output that uses legal-authority words without a verified legal source. "
          "None of them is a legal finding.", ""]
    for r, f in flagged:
        label = LEGAL_LABEL if f.get("status", "unverified") == "unverified" else REVIEW_LABEL
        L.append(f"- seq {r['seq']}, {r['actor']}, {f['where']}: **{label}** \"{f['text']}\"")
    if not flagged:
        L.append("- none")
    L += ["", "## Gap observations (drafts - require human review)", ""]
    for o in rep["gap_observations"]:
        L.append(f"- **{o.get('gap_id')}** [{o.get('status')}] {o.get('wording')} cites: {o.get('cites')}")
    if not rep["gap_observations"]:
        L.append("- none recorded")
    out = run_dir / "report.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out
