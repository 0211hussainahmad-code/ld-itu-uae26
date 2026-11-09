"""Versioned exercise state. Only the orchestrator changes it, and only after the
gate (and, where required, a human) has allowed the change. Models never write here.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

from .sim import Topology


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class ExerciseState:
    topo: Topology
    service: dict
    record_sets: dict
    endpoints: dict
    regions: dict = field(default_factory=dict)
    priority_plan: list[str] | None = None        # approved plan only
    pending_recommendations: list[dict] = field(default_factory=list)
    version: int = 0
    clock_min: int = 0                            # simulated minutes since T+0
    synthetic: bool = True

    @classmethod
    def from_scenario(cls, topo: Topology, scenario: dict) -> "ExerciseState":
        regions = {nid: {"label": n["label"], "in_uae": bool(n.get("in_uae"))}
                   for nid, n in topo.nodes.items() if n["kind"] == "region"}
        return cls(topo=topo,
                   service=copy.deepcopy(scenario["service"]),
                   record_sets=copy.deepcopy(scenario["record_sets"]),
                   endpoints=copy.deepcopy(scenario["endpoints"]),
                   regions=regions)

    # -- read views ------------------------------------------------------
    def traffic(self) -> dict:
        res = self.topo.allocate(dest_override={"gov_ai": self.service["endpoint_region"]},
                                 priority=self.priority_plan)
        return {k: {"dest": v.dest, "delivered": v.delivered, "demand": v.demand,
                    "share": round(v.share, 3), "avg_ms": v.avg_ms, "health": v.health}
                for k, v in res.items()}

    def snapshot(self) -> dict:
        return {
            "version": self.version, "clock_min": self.clock_min, "synthetic": True,
            "topology_version": self.topo.version, "links_down": sorted(self.topo.down),
            "service": self.service, "record_sets": self.record_sets,
            "endpoints": self.endpoints, "priority_plan": self.priority_plan,
            "traffic": self.traffic(),
        }

    def digest(self) -> str:
        return hashlib.sha256(_canon(self.snapshot()).encode()).hexdigest()[:16]

    # -- writes (called by the orchestrator only) -------------------------
    def _bump(self) -> None:
        self.version += 1

    def fail_links(self, ids: list[str]) -> None:
        self.topo.set_down(ids); self._bump()

    def restore_links(self, ids: list[str]) -> None:
        self.topo.set_up(ids); self._bump()

    def apply(self, tool: str, args: dict) -> dict:
        """Apply an ALLOWED action. Returns a short description of the change."""
        if tool == "set_service_mode":
            old = self.service["mode"]
            if args["mode"] == old:
                return {"changed": None, "note": f"already in {old} mode"}
            self.service["mode"] = args["mode"]; self._bump()
            return {"changed": "service.mode", "from": old, "to": args["mode"]}
        if tool == "switch_ai_endpoint":
            old = self.service["endpoint_region"]
            if args["region"] == old:
                return {"changed": None, "note": f"already using the {old} endpoint"}
            if not self.endpoints.get(args["region"], {}).get("available", False):
                return {"changed": None, "error": f"no compatible model endpoint available in {args['region']}"}
            self.service["endpoint_region"] = args["region"]; self._bump()
            return {"changed": "service.endpoint_region", "from": old, "to": args["region"]}
        if tool == "transfer_records":
            rs = self.record_sets[args["record_set"]]
            old = rs["region"]; rs["region"] = args["dest_region"]
            self.service["records_region"] = args["dest_region"]; self._bump()
            return {"changed": f"record_sets.{args['record_set']}.region", "from": old,
                    "to": args["dest_region"], "note": "SIMULATED - no real data moved"}
        if tool in ("reroute_traffic", "apply_operator_qos"):
            # Routing is recomputed by the model on every read; operator QoS is
            # represented as a proposed class order, applied only via a priority plan.
            return {"changed": None, "recorded": True, "note": "routing already optimal in the model; recorded only"}
        if tool == "issue_priority_order":
            self.priority_plan = list(args["order"]); self._bump()
            return {"changed": "priority_plan", "to": self.priority_plan,
                    "note": "exercise decision by the human controller, not a real order"}
        if tool == "recommend_priority_plan":
            self.pending_recommendations.append({"order": args.get("order"), "by": "regulator"})
            return {"changed": None, "recorded": True, "note": "recommendation recorded (non-binding)"}
        return {"changed": None}
