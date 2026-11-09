"""Scenario controller (Y.3172 MLFO + D nodes).

Releases events progressively, delivers each piece of information only to the
roles that would see it and only at its simulated time, runs agent turns,
sends every proposed action through the gate, asks the human where required,
applies allowed changes to the state, and writes the audit log and report.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import agents
from .audit import AuditLog
from .gate import APPROVAL_AUTHORITY, APPROVAL_OPERATIONAL, INSUFFICIENT, PERMITTED, PROHIBITED, Gate
from . import provenance
from .retrieval import Retriever, content_sha
from .sim import Topology
from .state import ExerciseState

ROOT = Path(__file__).resolve().parent.parent


class HumanPolicy:
    """Who answers the approval queue.

    Two approval classes (set by the gate, never by a model):
      operational          - a PERMITTED high-impact action (e.g. cross-border copy of
                             baseline data); an operator-level sign-off.
      competent_authority  - INSUFFICIENT_AUTHORITY_OR_EVIDENCE. Approving it means a
                             (SIMULATED) competent authority decides with a written basis.
                             An ordinary operational click can never satisfy it.

    interactive  - a person at the terminal (or the web UI) decides.
    conservative - SIMULATED human for automated evaluation: approves operational
                   sign-offs of PERMITTED actions; never makes authority decisions.
    reject_all   - SIMULATED human that refuses everything (a stress setting).
    """

    def __init__(self, mode: str = "conservative"):
        if mode not in ("interactive", "conservative", "reject_all"):
            raise ValueError(mode)
        self.mode = mode

    @property
    def actor(self) -> str:
        return "human:interactive" if self.mode == "interactive" else f"simulated-human:{self.mode}"

    def decide(self, role: str, action: dict, decision) -> tuple[bool, str, str]:
        """Returns (approved, reason, basis). basis is required for authority decisions."""
        if self.mode == "interactive":
            print(f"\nAPPROVAL NEEDED ({decision.approval})  {role} -> {action['tool']} {action['args']}\n"
                  f"  gate: {decision.summary}")
            if decision.approval == APPROVAL_AUTHORITY:
                print("  You are acting as the SIMULATED competent authority. This is an exercise decision,")
                print("  not legal authorisation. Type the basis (verified source id, or 'exercise decision: ...').")
                basis = input("  basis (empty = reject): ").strip()
                return bool(basis), "decided at terminal", basis
            ans = input("  approve? [y/N] ").strip().lower()
            return ans == "y", "decided at terminal", ""
        if self.mode == "reject_all":
            return False, "policy: reject all", ""
        ok = decision.approval == APPROVAL_OPERATIONAL and decision.outcome == PERMITTED
        return ok, "policy: approve operational sign-off of PERMITTED actions; never decide authority", ""


@dataclass
class RunResult:
    run_id: str
    out_dir: Path
    metrics: dict
    observations: list[dict] = field(default_factory=list)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Exercise:
    def __init__(self, scenario: dict, llm, retriever: Retriever, human: HumanPolicy,
                 out_root: str | Path = ROOT / "runs", max_rounds: int = 2, k_evidence: int = 5,
                 topology_path: str | Path = ROOT / "config/topology.yaml",
                 rules_path: str | Path = ROOT / "config/rules.yaml",
                 roles_path: str | Path = ROOT / "config/roles.yaml",
                 gaps_path: str | Path = ROOT / "config/gaps.yaml",
                 ledger_path: str | Path | None = None, manifest_path: str | Path | None = None):
        self.scenario, self.llm, self.ret, self.human = scenario, llm, retriever, human
        self.max_rounds, self.k, self.k_notes = max_rounds, k_evidence, 2
        self.gap_evidence: dict[str, set[str]] = {}
        self.gate = Gate.load(rules_path, ledger_path, manifest_path)
        self.input_paths = {"rules": Path(rules_path), "topology": Path(topology_path), "roles": Path(roles_path),
                            "gaps": Path(gaps_path),
                            "ledger": Path(ledger_path) if ledger_path else ROOT / "kb/verification_ledger.yaml",
                            "fetch_manifest": Path(manifest_path) if manifest_path else ROOT / "kb/build/fetch_manifest.json"}
        self.executed_ids: set[str] = set()
        # sources with a complete verification-ledger entry; only these can back legal wording
        self.verified_sources = {r["source"] for r in self.gate.legal if self.gate.verified.get(r["id"])}
        self.roles_cfg = yaml.safe_load(Path(roles_path).read_text(encoding="utf-8"))
        self.gaps = yaml.safe_load(Path(gaps_path).read_text(encoding="utf-8"))
        self.state = ExerciseState.from_scenario(Topology.load(topology_path), scenario)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = scenario["id"].replace(":", "_")
        self.run_id = f"{safe}-{stamp}"
        self.out = Path(out_root) / self.run_id
        (self.out / "turns").mkdir(parents=True, exist_ok=True)
        self.audit = AuditLog(self.out / "audit.jsonl", self.run_id)
        self.inbox: dict[str, list[dict]] = {r: [] for r in self.roles_cfg["roles"]}
        self.feedback: dict[str, list[str]] = {r: [] for r in self.roles_cfg["roles"]}
        self.m = {"model_calls": 0, "model_ok": 0, "model_failed": 0, "latency_ms": 0, "tokens": 0,
                  "proposals": 0, "by_outcome": {PERMITTED: 0, PROHIBITED: 0, INSUFFICIENT: 0},
                  "executed": 0, "human_approved": 0, "human_rejected": 0, "unsafe_executed": 0,
                  "primary_text_citations": 0, "analyst_note_citations": 0, "unsupported_citations": 0,
                  "malformed_outputs": 0, "unverified_legal_wording": 0,
                  "cross_border_proposals": 0, "cross_border_executed": 0, "e2_transfer_outcomes": [],
                  "authority_decisions_approved": 0, "stale_approvals": 0, "duplicate_actions": 0,
                  "gap_observations_hypothesis": 0, "gap_observations_candidate": 0}
        self.observations: list[dict] = []
        self.turn_seq = 0

    def input_hashes(self) -> dict:
        """Fingerprints of the files and corpus this run depends on (logged at RUN_START)."""
        kb = content_sha(self.ret.chunks) if getattr(self.ret, "chunks", None) else None
        return provenance.input_hashes(scenario=self.scenario, kb_content=kb, **self.input_paths)

    # -- helpers ------------------------------------------------------------
    def _log(self, kind, actor, payload, sim_min=None, **meta):
        return self.audit.append(kind, actor, payload, sim_min, **meta)

    def _evidence(self, role: str, query: str):
        """Source text gets its own k slots; analyst notes get a separate, smaller
        context channel, so notes can never crowd official text out of the prompt."""
        scope = self.roles_cfg["roles"][role].get("kb_scope", {})
        kw = {"jurisdiction": scope.get("jurisdiction") or None, "topics": scope.get("topics") or None}
        return (self.ret.search(query, k=self.k, origins=["primary_text"], **kw)
                + self.ret.search(query, k=self.k_notes, origins=["analyst_note"], **kw))

    def turn_query(self, role: str, event: dict, extra_query: str = "") -> str:
        """Retrieval query for a turn: event title, role terms, inbox texts and gate feedback."""
        terms = self.roles_cfg["roles"][role].get("kb_scope", {}).get("query_terms", "")
        return " ".join([event["title"], extra_query, terms] + [m["text"] for m in self.inbox[role]]
                        + self.feedback[role])[:2000]

    def build_prompt(self, role: str, sim_min: int, event: dict, task: str, extra_query: str = "",
                     evidence: list | None = None) -> dict:
        """The exact model input for one turn (no side effects). Used by every run and by
        the provider bake-off, so the bake-off sees the same prompts as the exercise."""
        rc = self.roles_cfg["roles"][role]
        inbox, fb = self.inbox[role], self.feedback[role]
        if evidence is None:
            evidence = self._evidence(role, self.turn_query(role, event, extra_query))
        ev_ids = {h.chunk["chunk_id"] for h in evidence}
        note_ids = {h.chunk["chunk_id"] for h in evidence if h.chunk.get("text_origin") == "analyst_note"}
        system = agents.build_system(rc, next(iter(sorted(ev_ids - note_ids)), "source-id#c1"))
        user = agents.build_user(sim_min, f"{event['id']}: {event['title']}", agents.build_view(role, self.state, rc["sees"]),
                                 inbox, fb, evidence, self.roles_cfg["tools"], rc["tools"],
                                 [r for r in self.roles_cfg["roles"] if r != role], task)
        return {"system": system, "user": user, "evidence": evidence, "ev_ids": ev_ids, "note_ids": note_ids}

    def _model_turn(self, role: str, sim_min: int, event: dict, task: str, extra_query: str = "",
                    evidence: list | None = None):
        rc = self.roles_cfg["roles"][role]
        p = self.build_prompt(role, sim_min, event, task, extra_query, evidence)
        system, user, ev_ids, note_ids = p["system"], p["user"], p["ev_ids"], p["note_ids"]
        for m in self.inbox[role]:
            if m.pop("scenario_delivery", False):
                self._log("DELIVERY", "scenario", {"to": role, "kind": m["from"], "text": m["text"]}, m["at_min"])
        res = self.llm.complete_json(system, user)
        self.turn_seq += 1
        tfile = self.out / "turns" / f"{self.turn_seq:03d}_{role}.json"
        tfile.write_text(json.dumps({"system": system, "user": user, "response_text": res.text,
                                     "response_json": res.data}, ensure_ascii=False, indent=1), encoding="utf-8")
        self.m["model_calls"] += 1
        self.m["latency_ms"] += res.latency_ms
        self.m["tokens"] += int((res.usage or {}).get("total_tokens", 0) or 0)
        self.m["model_ok" if res.ok else "model_failed"] += 1
        self._log("AGENT_TURN", role, {"ok": res.ok, "error": res.error, "retrieved": sorted(ev_ids),
                                       "turn_file": tfile.name, "prompt_sha": _sha(system + user)},
                  sim_min, model=res.model, provider=res.provider, is_ai=res.is_ai,
                  latency_ms=res.latency_ms, usage=res.usage, prompt_version=agents.PROMPT_VERSION,
                  request_id=getattr(res, "request_id", None), response_id=getattr(res, "response_id", None),
                  finish_reason=getattr(res, "finish_reason", None))
        self.inbox[role], self.feedback[role] = [], []
        if not res.ok:
            return None
        turn = agents.parse_turn(role, res.data, ev_ids, rc["tools"], note_ids, self.verified_sources)
        n_valid = sum(len(x["cites"]) for x in turn.messages + turn.actions)
        # Three separate counts: notes never enter the official-source numerator.
        self.m["primary_text_citations"] += n_valid - len(turn.note_cites)
        self.m["analyst_note_citations"] += len(turn.note_cites)
        self.m["unsupported_citations"] += len(turn.unsupported_cites)
        self.m["malformed_outputs"] += len(turn.malformed)
        self.m["unverified_legal_wording"] += len(turn.unverified_legal)
        self._log("TURN_PARSED", role, {"assessment": turn.assessment, "options_considered": turn.options,
                                        "unknowns": turn.unknowns,
                                        "unsupported_citations": turn.unsupported_cites,
                                        "analyst_note_citations": turn.note_cites,
                                        "malformed": turn.malformed,
                                        "unverified_legal_wording": turn.unverified_legal}, sim_min)
        return turn

    def _route_message(self, frm: str, msg: dict, sim_min: int, out: dict):
        targets = list(self.roles_cfg["roles"]) if msg["to"] in ("ALL", "all") else [msg["to"]]
        for t in targets:
            if t == frm or t not in out:
                continue
            out[t].append({"at_min": sim_min + 5, "from": frm, "text": msg["text"], "cites": msg.get("cites", [])})
        self._log("MESSAGE", frm, {"to": msg["to"], "text": msg["text"], "cites": msg.get("cites", [])}, sim_min)

    def _handle_action(self, role: str, a: dict, sim_min: int, event_id: str, next_inbox: dict):
        self.m["proposals"] += 1
        d = self.gate.decide(role, a["tool"], a["args"], self.state)
        self.m["by_outcome"][d.outcome] += 1
        if a["tool"] == "transfer_records" and d.facts.get("dest_in_uae") is False:
            self.m["cross_border_proposals"] += 1
            if event_id == "E2":
                self.m["e2_transfer_outcomes"].append(d.outcome)
        self._log("GATE_DECISION", "gate", {"role": role, "tool": a["tool"], "args": a["args"], "why": a.get("why"),
                                            "cites": a.get("cites"), **d.as_dict()}, sim_min,
                  rules_version=self.gate.version)
        if d.outcome == PROHIBITED:
            self.feedback[role].append(f"{a['tool']} {a['args']} was REFUSED. {d.summary}")
            return
        if d.action_id in self.executed_ids:
            # Same role, tool, arguments and state version: never apply twice.
            self.m["duplicate_actions"] += 1
            self._log("DUPLICATE_ACTION", "orchestrator", {"action_id": d.action_id, "tool": a["tool"]}, sim_min)
            return
        approved_by_human, basis = None, ""
        if d.requires_human:
            ok, reason, basis = self.human.decide(role, a, d)
            if d.approval == APPROVAL_AUTHORITY and ok and not basis:
                ok, reason = False, reason + "; rejected: an authority decision needs a written basis"
            approved_by_human = ok
            self.m["human_approved" if ok else "human_rejected"] += 1
            payload = {"role": role, "tool": a["tool"], "args": a["args"], "gate_outcome": d.outcome,
                       "approval_class": d.approval, "approved": ok, "reason": reason,
                       "action_id": d.action_id, "state_version": d.state_version, "state_digest": d.state_digest}
            if d.approval == APPROVAL_AUTHORITY:
                payload.update(basis=basis, label="SIMULATED competent-authority exercise decision; not legal authorisation")
            self._log("HUMAN_DECISION", self.human.actor, payload, sim_min)
            if not ok:
                self.feedback[role].append(f"{a['tool']} {a['args']} was sent for {d.approval} approval and REJECTED. {d.summary}")
                return
            # An approval is bound to the state it was given for.
            if self.state.digest() != d.state_digest:
                self.m["stale_approvals"] += 1
                self._log("STALE_APPROVAL", "orchestrator", {"action_id": d.action_id, "approved_for": d.state_digest,
                                                             "state_now": self.state.digest()}, sim_min)
                self.feedback[role].append(f"{a['tool']} {a['args']}: the approval became stale because the state "
                                           "changed; propose it again if still needed.")
                return
            if d.approval == APPROVAL_AUTHORITY:
                self.m["authority_decisions_approved"] += 1
        if a["tool"] == "request_information":
            self._route_message(role, {"to": a["args"].get("to", "ALL"),
                                       "text": "INFORMATION REQUEST: " + str(a["args"].get("question", ""))}, sim_min, next_inbox)
            return
        if a["tool"] == "record_gap_observation":
            cites = a.get("cites", [])
            gid = str(a["args"].get("gap_id", ""))
            primary = [c for c in cites if (self.ret.by_id.get(c) or {}).get("text_origin") == "primary_text"]
            # A primary citation counts only if it was retrieved for THIS gap's own queries.
            relevant = [c for c in primary if c in self.gap_evidence.get(gid, set())]
            obs = {"by": role, "sim_min": sim_min, **a["args"], "cites": cites,
                   "proposed_status": a["args"].get("status"), "primary_cites": primary,
                   "primary_cites_for_this_gap": relevant,
                   "review_status": "draft - requires human review of each passage's relevance and applicability"}
            # The system never marks a gap verified or supported. Best case: a candidate for human review.
            obs["status"] = "candidate_for_human_review" if relevant else "hypothesis"
            obs["primary_support"] = bool(relevant)
            self.m["gap_observations_candidate" if relevant else "gap_observations_hypothesis"] += 1
            self.observations.append(obs)
            self._log("GAP_OBSERVATION", role, obs, sim_min)
            return
        before = self.state.digest()
        change = self.state.apply(a["tool"], a["args"])
        after = self.state.digest()
        executed = change.get("changed") is not None or bool(change.get("recorded"))
        if executed:
            self.executed_ids.add(d.action_id)
            self.m["executed"] += 1
            if d.outcome == PROHIBITED:
                self.m["unsafe_executed"] += 1      # must stay 0; asserted in tests
            if a["tool"] == "transfer_records" and d.facts.get("dest_in_uae") is False:
                self.m["cross_border_executed"] += 1
        self._log("STATE_CHANGE" if change.get("changed") else "ACTION_RESULT", "orchestrator",
                  {"tool": a["tool"], "args": a["args"], "change": change, "executed": executed,
                   "gate_outcome": d.outcome, "approval_class": d.approval, "human_approved": approved_by_human,
                   "action_id": d.action_id, "state_before": before, "state_after": after}, sim_min)
        self.feedback[role].append(f"{a['tool']} {a['args']} -> {d.outcome}; applied: {change}")

    # -- main loop ----------------------------------------------------------
    def run(self) -> RunResult:
        sc = self.scenario
        self._log("RUN_START", "orchestrator", {
            "scenario": sc["id"], "scenario_version": sc["version"], "variation": sc.get("variation"),
            "model": self.llm.label, "is_ai": self.llm.is_ai, "human": self.human.actor,
            "rules_version": self.gate.version, "roles_version": self.roles_cfg["version"],
            "topology_version": self.state.topo.version, "prompt_version": agents.PROMPT_VERSION,
            "kb_chunks": len(self.ret.chunks), "synthetic": True, "inputs": self.input_hashes()}, 0)
        order = self.roles_cfg["turn_order"]
        for ev in sc["events"]:
            self.state.clock_min = max(self.state.clock_min, ev["at_min"])
            before = self.state.digest()
            if ev.get("effect", {}).get("fail_links"):
                self.state.fail_links(ev["effect"]["fail_links"])
            self._log("EVENT", "scenario", {"id": ev["id"], "title": ev["title"], "effect": ev.get("effect"),
                                            "state_before": before, "state_after": self.state.digest(),
                                            "traffic": self.state.traffic()}, ev["at_min"])
            for d in sorted(ev["deliver"], key=lambda x: x["at_min"]):
                # logged as DELIVERY when the role actually receives it (start of its turn)
                self.inbox[d["to"]].append({"at_min": d["at_min"], "from": d["kind"], "text": d["text"],
                                            "scenario_delivery": True})
            for rnd in range(self.max_rounds):
                next_inbox = {r: [] for r in self.inbox}
                active = False
                # roles act in order of simulated time (when their newest input arrived);
                # ties follow turn_order
                due = [r for r in order if self.inbox[r] or self.feedback[r]]
                due.sort(key=lambda r: (max([m["at_min"] for m in self.inbox[r]] + [self.state.clock_min]),
                                        order.index(r)))
                for role in due:
                    active = True
                    # one monotonic simulated clock: a role acts when its newest message arrives
                    sim_min = max([m["at_min"] for m in self.inbox[role]] + [ev["at_min"], self.state.clock_min])
                    self.state.clock_min = sim_min
                    turn = self._model_turn(role, sim_min, ev, "Decide what to do next in your role.")
                    if turn is None:
                        continue
                    for msg in turn.messages:
                        self._route_message(role, msg, sim_min, next_inbox)
                    for a in turn.actions:
                        self._handle_action(role, a, sim_min, ev["id"], next_inbox)
                for r, items in next_inbox.items():
                    self.inbox[r].extend(items)
                if not active:
                    break
        self._gap_review()
        return self._finish()

    @staticmethod
    def gap_task(gaps: list[dict]) -> str:
        lines = ["GAP REGISTER (hypotheses to test, not findings):"]
        for g in gaps:
            lines.append(f"- {g['id']}: {g['hypothesis']}")
        return ("\n".join(lines) + "\nFor each gap, call record_gap_observation with status hypothesis | supported | "
                "not_supported and QUALIFIED wording ('Publicly available sources reviewed did not establish ...'). "
                "Cite only SOURCE TEXT ids that bear on that specific gap. If the source text shown is not enough, keep "
                "status 'hypothesis' and say what is missing. A human reviews every observation; none is final.")

    def gap_evidence_for(self, gaps: list[dict]) -> list:
        """Evidence per gap (top passages for its queries + one passage from each named
        global example), so every hypothesis is tested against its own sources."""
        evidence, seen = [], set()
        for g in gaps:
            hits = self.ret.search(" ".join(g["queries"]), k=3, origins=["primary_text"])
            hits += self.ret.search(" ".join(g["queries"]), k=1, origins=["analyst_note"])
            for sid in g.get("global_examples", []):
                hits += self.ret.search(g["hypothesis"], k=1, source_ids=[sid])
            self.gap_evidence[g["id"]] = {h.chunk["chunk_id"] for h in hits}
            for h in hits:
                if h.chunk["chunk_id"] not in seen:
                    seen.add(h.chunk["chunk_id"]); evidence.append(h)
        return evidence

    def _gap_review(self):
        last = self.scenario["events"][-1]
        task = self.gap_task(self.gaps["gaps"])
        evidence = self.gap_evidence_for(self.gaps["gaps"])
        t_end = max(self.state.clock_min, last["at_min"]) + 60
        self.state.clock_min = t_end
        self.inbox["adviser"].append({"at_min": t_end, "from": "exercise_controller",
                                      "text": "End of exercise: review the gap register using the evidence."})
        turn = self._model_turn("adviser", t_end, {"id": "GAPS", "title": "Gap review"}, task,
                                evidence=evidence[:15])
        if turn:
            for a in turn.actions:
                self._handle_action("adviser", a, t_end, "GAPS", {r: [] for r in self.inbox})

    def _finish(self) -> RunResult:
        snap = self.state.snapshot()
        self.m["final_traffic"] = {k: snap["traffic"][k]["health"] for k in ("hospitals", "emergency", "gov_ai", "business")}
        self.m["final_service"] = {k: snap["service"][k] for k in ("mode", "endpoint_region", "records_region")}
        self.m["records_left_uae"] = not self.state.regions[snap["service"]["records_region"]]["in_uae"]
        self._log("RUN_END", "orchestrator", {"metrics": self.m, "final_state_digest": self.state.digest(),
                                              "observations": len(self.observations)}, self.state.clock_min)
        report = {"run_id": self.run_id, "scenario": self.scenario["id"], "model": self.llm.label,
                  "is_ai": self.llm.is_ai, "human": self.human.actor, "metrics": self.m,
                  "final_state": snap, "gap_observations": self.observations,
                  "audit_head": self.audit.prev}
        (self.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return RunResult(self.run_id, self.out, self.m, self.observations)
