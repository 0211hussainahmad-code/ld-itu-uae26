"""First live-AI proof in ONE model call (protocol gate: model call -> grounded
output -> constrained tool -> state change).

Puts the exercise at Event 2 (links already cut, fallback pressure), asks the
service role's model what to do, sends its proposals through the gate, applies
whatever is allowed, and prints everything. Uses the live model from the
LINKDOWN_LLM_* environment variables (see README). There is no test-double mode.

    python scripts/smoke_live.py              # one or two calls, about 3-5k tokens each
    python scripts/smoke_live.py --ping       # only checks the endpoint answers JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linkdown.audit import verify  # noqa: E402
from linkdown.llm import LLMClient, LLMConfig  # noqa: E402
from linkdown.orchestrator import Exercise, HumanPolicy  # noqa: E402
from linkdown.retrieval import Retriever  # noqa: E402
from linkdown.scenario import apply_variation, load_yaml  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "runs"), help="folder for the run output")
    a = ap.parse_args()
    llm = LLMClient(LLMConfig.from_env())
    print(f"model: {llm.label}")
    if a.ping:
        r = llm.complete_json("Reply with JSON only.", 'Return {"status": "ok"}.')
        print(f"ok={r.ok} latency={r.latency_ms}ms usage={r.usage} error={r.error}\n{r.text[:300]}")
        return 0 if r.ok else 1

    sc = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), None)
    sc["id"] = sc["id"] + "-smoke"
    ex = Exercise(sc, llm, Retriever.load(ROOT / "kb/build/chunks.jsonl"), HumanPolicy("conservative"),
                  out_root=a.out)
    e1, e2 = sc["events"][0], sc["events"][1]
    ex._log("RUN_START", "orchestrator", {"scenario": sc["id"], "scenario_version": sc["version"],
                                          "variation": None, "mode": "smoke_live", "model": llm.label,
                                          "is_ai": llm.is_ai, "rules_version": ex.gate.version,
                                          "kb_chunks": len(ex.ret.chunks), "synthetic": True,
                                          "inputs": ex.input_hashes()}, 0)
    for ev in (e1, e2):              # E1 effect applied, E2 is the decision point
        before = ex.state.digest()
        ex.state.clock_min = ev["at_min"]
        if ev.get("effect", {}).get("fail_links"):
            ex.state.fail_links(ev["effect"]["fail_links"])
        ex._log("EVENT", "scenario", {"id": ev["id"], "title": ev["title"], "effect": ev.get("effect"),
                                      "state_before": before, "state_after": ex.state.digest(),
                                      "traffic": ex.state.traffic()}, ev["at_min"])
    for d in e2["deliver"]:
        if d["to"] == "service":
            ex.inbox["service"].append({"at_min": d["at_min"], "from": d["kind"], "text": d["text"],
                                        "scenario_delivery": True})
    # Up to two service turns: the second sees the gate's feedback on the first (the same
    # propose -> decide -> feedback loop a full run uses). It stops once state changes.
    for attempt in (1, 2):
        sim = e2["at_min"] + (attempt - 1) * 5
        ex.state.clock_min = sim
        turn = ex._model_turn("service", sim, e2, "Decide what to do next in your role.")
        if turn is None:
            print(f"model call {attempt} FAILED - see the audit log")
            break
        print(f"\n--- TURN {attempt} ---")
        print("ASSESSMENT:", turn.assessment)
        for o in turn.options:
            print(f"OPTION [{o['decision']}] {o['option']} - {o['reason']}")
        print("UNKNOWNS:", turn.unknowns)
        print("UNSUPPORTED CITATIONS:", turn.unsupported_cites or "none")
        for f in turn.unverified_legal:
            print(f"UNVERIFIED LEGAL WORDING ({f['where']}): {f['text']}")
        for msg in turn.messages:
            print(f"MESSAGE to {msg['to']}: {msg['text']}  cites={msg['cites']}")
        for act in turn.actions:
            ex._handle_action("service", act, sim, "E2", {r: [] for r in ex.inbox})
        if ex.m["executed"] > 0 or not ex.feedback["service"]:
            break
    res = ex._finish()
    for r in ex.audit.records:
        if r["kind"] == "GATE_DECISION":
            p = r["payload"]
            print(f"GATE: {p['tool']}({p['args']}) -> {p['outcome']}  [{p['trail'][0]['rule_id'] if p['trail'] else ''}]")
        if r["kind"] in ("STATE_CHANGE", "HUMAN_DECISION"):
            print(f"{r['kind']}: {json.dumps(r['payload'], ensure_ascii=False)[:200]}")
    ok, msg = verify(res.out_dir / "audit.jsonl", ex.audit.prev)
    (res.out_dir / "audit_head.txt").write_text(ex.audit.prev + "\n", encoding="utf-8")
    print(f"\naudit: {'VERIFIED' if ok else 'FAILED'} - {msg}\nrun folder: {res.out_dir}")
    print(f"AUDIT_HEAD {res.run_id} {ex.audit.prev}")
    print(f"is_ai={llm.is_ai}, model={llm.label}, tokens={res.metrics['tokens']}, latency={res.metrics['latency_ms']}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
