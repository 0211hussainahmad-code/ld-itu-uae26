"""Independent replay check of a run folder.

Rebuilds the exercise state from the scenario named in the audit log, then walks
the log in order:
  EVENT         re-applies the logged link failures; the state digest must match
  GATE_DECISION re-decides with the CURRENT rules on the rebuilt state; the outcome must match
  STATE_CHANGE  checks the digest before, re-applies the action, checks the digest after
It also verifies the hash chain against the head saved in report.json, and compares
the input fingerprints recorded at RUN_START (rules, ledger, fetch manifest, topology,
scenario) with the files used now: a mismatch FAILS, because the replay would then
check the run against different rules than it used (check out the run's commit).
A pass means: the recorded decisions and state changes follow deterministically
from the scenario, the rules and the logged actions. Model calls are NOT repeated.
SCOPE: a pass says nothing about citation relevance, legal correctness or the
quality of the model's explanations.

    python scripts/replay.py runs/<run-id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linkdown.audit import verify  # noqa: E402
from linkdown import provenance  # noqa: E402
from linkdown.gate import Gate  # noqa: E402
from linkdown.scenario import apply_variation, load_yaml  # noqa: E402
from linkdown.sim import Topology  # noqa: E402
from linkdown.state import ExerciseState  # noqa: E402


def replay(run_dir: Path, rules_path=None, ledger_path=None, manifest_path=None) -> tuple[bool, list[str]]:
    problems: list[str] = []
    recs = [json.loads(l) for l in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8")) if (run_dir / "report.json").exists() else {}
    ok, msg = verify(run_dir / "audit.jsonl", rep.get("audit_head"))
    if not ok:
        problems.append(f"audit chain: {msg}")
    start = next((r for r in recs if r["kind"] == "RUN_START"), None)
    if start is None:
        return False, problems + ["no RUN_START record"]
    sc = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), start["payload"].get("variation"))
    sc["id"] = start["payload"].get("scenario", sc["id"])          # e.g. the smoke run's "-smoke" suffix
    rules_path = Path(rules_path or ROOT / "config/rules.yaml")
    gate = Gate.load(rules_path, ledger_path, manifest_path)
    recorded = start["payload"].get("inputs")
    notes: list[str] = []
    if recorded:
        now = {"rules": provenance.file_sha(rules_path),
               "ledger": provenance.file_sha(ledger_path or ROOT / "kb/verification_ledger.yaml"),
               "fetch_manifest": provenance.file_sha(manifest_path or ROOT / "kb/build/fetch_manifest.json"),
               "topology": provenance.file_sha(ROOT / "config/topology.yaml"),
               "scenario": provenance.scenario_sha(sc)}
        changed = [k for k in provenance.GATE_SIDE if recorded.get(k) != now[k]]
        if changed:
            problems.append(f"inputs changed since the run: {', '.join(changed)}; replay at the run's commit "
                            f"{recorded.get('code_commit') or '(not recorded)'}")
    else:
        notes.append("no input fingerprints in RUN_START (run predates v0.1.6): replayed against the current files")
    if start["payload"].get("rules_version") != gate.version:
        problems.append(f"rules version changed: run used {start['payload'].get('rules_version')}, now {gate.version}")
    st = ExerciseState.from_scenario(Topology.load(ROOT / "config/topology.yaml"), sc)
    n = {"EVENT": 0, "GATE_DECISION": 0, "STATE_CHANGE": 0}
    for r in recs:
        k, p = r["kind"], r["payload"]
        if k == "EVENT":
            n[k] += 1
            st.clock_min = max(st.clock_min, r["sim_min"] or 0)      # same rule as the orchestrator
            if (p.get("effect") or {}).get("fail_links"):
                st.fail_links(p["effect"]["fail_links"])
            if p.get("state_after") and st.digest() != p["state_after"]:
                problems.append(f"seq {r['seq']}: state after event {p['id']} differs")
        elif k == "GATE_DECISION":
            n[k] += 1
            d = gate.decide(p["role"], p["tool"], p["args"], st)
            if d.outcome != p["outcome"]:
                problems.append(f"seq {r['seq']}: gate now says {d.outcome}, log says {p['outcome']} ({p['tool']})")
        elif k == "STATE_CHANGE":
            n[k] += 1
            st.clock_min = r["sim_min"]                            # the turn's simulated time
            if st.digest() != p["state_before"]:
                problems.append(f"seq {r['seq']}: state before {p['tool']} differs")
            st.apply(p["tool"], p["args"])
            if st.digest() != p["state_after"]:
                problems.append(f"seq {r['seq']}: state after {p['tool']} differs")
    if n["EVENT"] == 0:
        problems.append("no EVENT records to replay")
    return not problems, problems + notes + [
        f"replayed {n['EVENT']} events, {n['GATE_DECISION']} gate decisions, "
        f"{n['STATE_CHANGE']} state changes; final digest {st.digest()}",
        "scope: state changes, gate decisions, hash chain and inputs only; not citation relevance or legal correctness"]


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    ok, lines = replay(Path(sys.argv[1]))
    for l in lines:
        print(("  " if ok else "! ") + l)
    print("REPLAY: PASS" if ok else "REPLAY: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
