"""Full-role demonstration, separate from the frozen benchmark's Exercise.

Lives outside the frozen `linkdown/` package and only imports from it.
Neutral controller check-ins ensure participation, not shared information. Each
role still receives only its own state view, inbox, tools and retrieved sources.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from linkdown.audit import verify
from linkdown.orchestrator import Exercise
from linkdown.gate import Gate, PROHIBITED, APPROVAL_AUTHORITY
from linkdown.scenario import apply_variation, load_yaml
from linkdown.sim import Topology
from linkdown.state import ExerciseState

ROOT = Path(__file__).resolve().parent.parent

ROLES = ("operator", "service", "regulator", "adviser")
EVENTS = ("E1", "E2", "E3")
INTERACTIVE = "human:interactive"


def max_model_turns(scenario: dict, max_rounds: int) -> int:
    """Structural ceiling on model turns: every role in every round of every
    event, plus the adviser's gap review. A live run's shared request cap must
    be at least this, or the run can be cut off part-way after paid requests."""
    return len(scenario["events"]) * max_rounds * len(ROLES) + 1


class FullExercise(Exercise):
    def __init__(self, scenario, clients, retriever, human, out_root, **kwargs):
        if set(clients) != set(ROLES):
            raise ValueError("Exactly four role clients are required")
        if len({id(c) for c in clients.values()}) != 4:
            raise ValueError("Each role requires a separate client")
        if len({c.is_ai for c in clients.values()}) != 1:
            raise ValueError("Mixed live and scripted roles are not a live demonstration")
        self.clients = clients
        # The original constructor uses second-resolution names and can overwrite
        # another run. An isolated parent also preserves interrupted attempts.
        super().__init__(scenario, clients["operator"], retriever, human,
                         out_root=Path(out_root) / uuid.uuid4().hex, **kwargs)

    def _log(self, kind, actor, payload, sim_min=None, **meta):
        if kind == "RUN_START":
            payload = {**payload, "demonstration_version": "full-exercise-1",
                       "role_models": {r: c.label for r, c in self.clients.items()}}
        rec = super()._log(kind, actor, payload, sim_min, **meta)
        if kind == "EVENT":
            for role in ROLES:
                self.inbox[role].append({"at_min": sim_min, "from": "exercise_controller",
                                        "text": "Scheduled role check-in. Use only your available information; unknown facts remain unknown."})
        return rec

    def _model_turn(self, role, sim_min, event, task, extra_query="", evidence=None):
        self.llm = self.clients[role]
        turn = super()._model_turn(role, sim_min, event, task, extra_query, evidence)
        path = self.out / "turns" / f"{self.turn_seq:03d}_{role}.json"
        # Usable = parsed, nothing malformed in actions/messages/options, and a
        # non-empty assessment: exactly what inspect_demonstration requires.
        usable = turn is not None and not turn.malformed and bool(turn.assessment.strip())
        payload = {"event": event["id"], "turn_file": path.name,
                   "turn_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "parsed": turn is not None, "usable": usable}
        serving = getattr(self.clients[role], "last_serving", None)
        if serving is not None:
            # Live only: who served this reply (OpenRouter generation record, or direct).
            payload["serving"] = serving
        self._log("DEMO_TURN", role, payload, sim_min)
        if usable:
            return turn
        stop = getattr(self.clients[role], "stop_live_requests", None)
        if stop is not None:
            # A live run can no longer pass: send no further paid request (all roles).
            stop(f"Unusable turn {path.name}: unparsed, malformed or empty assessment")
        # Fail closed: an unusable turn is discarded whole, so none of its messages
        # or actions (valid or not) reach the gate, the state or another role.
        return None


def live_problems(records: list[dict], agents: dict) -> list[str]:
    """--require-live: every turn must come from one reviewed live profile, with a
    provider request id, provider usage and serving evidence: through OpenRouter, a
    generation record proving the pinned host served it. Labels alone never qualify."""
    from .demo_provider import PROFILES

    start = next(r for r in records if r["kind"] == "RUN_START")["payload"]
    if start.get("is_ai") is not True:
        return ["Required a live AI run; this evidence is scripted (NOT AI)"]
    problems = []
    labels = set((start.get("role_models") or {}).values())
    label = next(iter(labels)) if len(labels) == 1 else ""
    profile = PROFILES.get(label)
    if set(start.get("role_models") or {}) != set(ROLES) or profile is None:
        problems.append("Roles do not all use one reviewed live provider/model profile")
        return problems
    provider, model = profile["provider"], profile["model"]
    demos = {r["payload"]["turn_file"]: r["payload"] for r in records if r["kind"] == "DEMO_TURN"}
    for name, a in sorted(agents.items()):
        u = a.get("usage") or {}
        sv = (demos.get(name) or {}).get("serving") or {}
        if a.get("is_ai") is not True or a.get("provider") != provider or a.get("model") != model:
            problems.append(f"Turn not served by the reviewed provider/model: {name}")
        elif not (a.get("request_id") or a.get("response_id")):
            problems.append(f"Turn lacks a provider request id: {name}")
        elif not all(isinstance(u.get(k), int) and not isinstance(u.get(k), bool)
                     for k in ("prompt_tokens", "completion_tokens")):
            problems.append(f"Turn lacks provider token usage: {name}")
        elif profile["serving"] == "pinned" and (
                sv.get("state") != "verified" or sv.get("generation_id") != a.get("response_id")
                or str(sv.get("provider_name") or "").lower() != profile["upstream"].lower()):
            problems.append(f"Serving host not verified as {profile['upstream']}: {name}")
        elif profile["serving"] == "direct" and sv.get("state") != "direct":
            problems.append(f"Turn lacks direct-serving evidence: {name}")
    return problems


def interactive_problems(records: list[dict]) -> list[str]:
    """--require-interactive-human: the run's controller and every recorded human
    decision must be the interactive terminal controller, never a simulated policy."""
    start = next(r for r in records if r["kind"] == "RUN_START")["payload"]
    problems = []
    if start.get("human") != INTERACTIVE:
        problems.append(f"Required {INTERACTIVE}; run controller is {start.get('human')}")
    if any(r["actor"] != INTERACTIVE for r in records if r["kind"] == "HUMAN_DECISION"):
        problems.append("A human decision was not made by the interactive controller")
    return problems


def inspect_demonstration(run_dir: Path, expected_head: str, *, require_live: bool = False,
                          require_interactive_human: bool = False) -> dict:
    """Fail-closed coverage and evidence checks, in addition to independent replay.

The caller must retain the head outside this directory. This does not establish
provider authenticity, citation relevance, legal correctness or model quality.
require_live / require_interactive_human make scripted or simulated evidence fail.
"""
    from scripts.replay import replay

    problems = []
    try:
        ok, detail = verify(run_dir / "audit.jsonl", expected_head)
        if not ok:
            problems.append(detail)
        records = [json.loads(s) for s in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
        replay_ok, replay_notes = replay(run_dir)
        if not replay_ok:
            problems.extend(replay_notes)
        starts = [r for r in records if r["kind"] == "RUN_START"]
        ends = [r for r in records if r["kind"] == "RUN_END"]
        if len(starts) != 1 or len(ends) != 1 or records[-1]["kind"] != "RUN_END":
            raise ValueError("Exactly one complete run is required")
        if starts[0]["payload"].get("demonstration_version") != "full-exercise-1":
            problems.append("Not a full-exercise demonstration")
        # Re-derive full decisions, check approval/action bindings, and replay
        # recorded results as well as state changes through the final digest.
        sc = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), starts[0]["payload"].get("variation"))
        st = ExerciseState.from_scenario(Topology.load(ROOT / "config/topology.yaml"), sc)
        gate, decisions, approvals, executed = Gate.load(ROOT / "config/rules.yaml"), {}, {}, set()
        for rec in records:
            p, kind = rec["payload"], rec["kind"]
            st.clock_min = max(st.clock_min, rec.get("sim_min") or 0)
            if kind == "EVENT":
                if p.get("state_before") != st.digest():
                    problems.append(f"Event starting state differs at seq {rec['seq']} (clock {st.clock_min})")
                if (p.get("effect") or {}).get("fail_links"):
                    st.fail_links(p["effect"]["fail_links"])
                if p.get("state_after") != st.digest():
                    problems.append(f"Event resulting state differs at seq {rec['seq']} (clock {st.clock_min})")
            elif kind == "GATE_DECISION":
                d = gate.decide(p["role"], p["tool"], p["args"], st)
                if p.get("action_id") != d.action_id:
                    raise ValueError(
                        f"Action ID mismatch at seq {rec['seq']}: recorded={p.get('action_id')}, "
                        f"reconstructed={d.action_id}; recorded state version={p.get('state_version')}, "
                        f"digest={p.get('state_digest')}; reconstructed state version={st.version}, "
                        f"digest={st.digest()}, clock={st.clock_min}")
                if any(p.get(k) != v for k, v in d.as_dict().items()):
                    problems.append(f"Decision differs at seq {rec['seq']}")
                decisions[d.action_id] = (d, p)
            elif kind == "HUMAN_DECISION":
                approvals[p["action_id"]] = p
            elif kind in ("STATE_CHANGE", "ACTION_RESULT"):
                if p.get("action_id") not in decisions:
                    raise ValueError(
                        f"No reconstructed gate decision for action {p.get('action_id')} at seq {rec['seq']}; "
                        f"state version={st.version}, digest={st.digest()}, clock={st.clock_min}")
                d, proposed = decisions[p["action_id"]]
                if d.outcome == PROHIBITED or d.state_digest != st.digest() or p["action_id"] in executed:
                    problems.append(f"Unauthorized, stale or duplicate action at seq {rec['seq']}")
                if proposed["tool"] != p["tool"] or proposed["args"] != p["args"]:
                    problems.append("Executed action differs from gated proposal")
                if d.requires_human:
                    h = approvals.get(d.action_id, {})
                    if (h.get("approved") is not True or h.get("state_digest") != st.digest()
                            or h.get("approval_class") != d.approval
                            or (d.approval == APPROVAL_AUTHORITY and not h.get("basis"))):
                        problems.append("Missing matching human approval")
                if p["state_before"] != st.digest():
                    problems.append("Action starting state differs")
                change = st.apply(p["tool"], p["args"])
                did_execute = change.get("changed") is not None or bool(change.get("recorded"))
                if p["state_after"] != st.digest() or p["change"] != change or p["executed"] != did_execute:
                    problems.append("Action result differs")
                if did_execute:
                    executed.add(d.action_id)
        if st.digest() != ends[0]["payload"]["final_state_digest"]:
            problems.append(
                f"Independently replayed final state differs: recorded={ends[0]['payload']['final_state_digest']}, "
                f"reconstructed={st.digest()}, version={st.version}, clock={st.clock_min}")
        if [r["payload"]["id"] for r in records if r["kind"] == "EVENT"] != list(EVENTS):
            problems.append("Expected E1, E2, E3 in order")
        coverage = {e: {r: 0 for r in ROLES} for e in EVENTS}
        agents = {r["payload"]["turn_file"]: r for r in records if r["kind"] == "AGENT_TURN"}
        demos = [r for r in records if r["kind"] == "DEMO_TURN"]
        if len(demos) != len(agents):
            problems.append("Turn evidence is incomplete")
        for r in demos:
            p = r["payload"]
            name = p["turn_file"]
            if Path(name).name != name:
                raise ValueError("Invalid turn filename")
            path = run_dir / "turns" / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != p["turn_sha256"]:
                problems.append(f"Altered turn: {name}")
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved.get("response_json"), dict) or not str(saved["response_json"].get("assessment", "")).strip():
                problems.append(f"Missing substantive assessment: {name}")
            a = agents.get(name)
            if not a or a["actor"] != r["actor"] or not a["payload"]["ok"] or not p["parsed"]:
                problems.append(f"Failed or unmatched turn: {name}")
            elif p["event"] in coverage:
                coverage[p["event"]][r["actor"]] += 1
        if any(n == 0 for roles in coverage.values() for n in roles.values()):
            problems.append("Missing successful role/event turns")
        m = ends[0]["payload"]["metrics"]
        if m["model_failed"] or m["unsafe_executed"] or m["malformed_outputs"]:
            problems.append("Failed model calls, malformed outputs or unsafe execution")
        if not any(r["kind"] == "STATE_CHANGE" for r in records):
            problems.append("No observable synthetic state change")
        rep = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        if rep["metrics"] != m or rep["audit_head"] != expected_head:
            problems.append("Report does not match anchored audit")
        digest = hashlib.sha256(json.dumps(rep["final_state"], sort_keys=True,
                                          separators=(",", ":"), default=str).encode()).hexdigest()[:16]
        if digest != ends[0]["payload"]["final_state_digest"]:
            problems.append("Final state differs from audit")
        live = starts[0]["payload"]["is_ai"] is True
        if any(a.get("is_ai") is not live for a in agents.values()):
            problems.append("Inconsistent AI labels")
        if require_live:
            problems.extend(live_problems(records, agents))
        if require_interactive_human:
            problems.extend(interactive_problems(records))
        return {"passed": not problems, "mode": "live" if live else "offline-NOT-AI",
                "required": {"live": require_live, "interactive_human": require_interactive_human},
                "coverage": coverage, "problems": problems, "audit_head": expected_head,
                "metrics": m, "replay": replay_notes,
                "independent_final_state": {"version": st.version, "clock_min": st.clock_min,
                                            "digest": st.digest()},
                "human": starts[0]["payload"]["human"],
                "human_decisions": sum(1 for r in records if r["kind"] == "HUMAN_DECISION"),
                "served_by": sorted({f"{a.get('provider')}:{a.get('model')}" for a in agents.values()}),
                "limitations": ["Offline outputs are scripted, not AI evidence." if not live else
                                "Live integration is not a reliability or quality evaluation.",
                                "Citation relevance and legal applicability require human review.",
                                "Hash integrity requires an externally retained head; it is not provider attestation."]}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as e:
        return {"passed": False, "problems": problems + [f"Incomplete or invalid evidence: {e}"]}
