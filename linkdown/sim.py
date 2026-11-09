"""Deterministic, synthetic network model (the Y.3172 "simulated underlay").

Nothing here calls an AI model. Given which links are up and how demand is
prioritised, it computes how much of each demand class is delivered and at
what latency. The same inputs always give the same outputs.

Allocation method (documented so judges can check it):
  * capacity is handed out one capacity unit (cu) at a time;
  * each unit takes the lowest-latency path that still has >= 1 cu spare;
  * with no approved priority plan, the next unit goes to the class with the
    lowest delivered share, so every class suffers the same shortfall;
  * with an approved plan, higher-priority classes are served first.
This is a transparent teaching heuristic, not an optimal traffic-engineering model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

ORIGIN = "uae_core"


@dataclass
class ClassResult:
    id: str
    dest: str
    demand: int
    delivered: int
    avg_ms: float | None
    health: str  # OK | DEGRADED | DOWN

    @property
    def share(self) -> float:
        return self.delivered / self.demand if self.demand else 1.0


@dataclass
class Topology:
    nodes: dict
    links: list[dict]
    demand: list[dict]
    health: dict
    version: str
    synthetic: bool = True
    down: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: str | Path) -> "Topology":
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if cfg.get("synthetic") is not True:          # fail closed: absent, false or "yes" all refuse
            raise ValueError("Topology must be marked synthetic: true")
        return cls(cfg["nodes"], cfg["links"], cfg["demand"], cfg["health"], cfg["version"])

    def link_ids(self, group: str | None = None) -> list[str]:
        return [l["id"] for l in self.links if group is None or l["group"] == group]

    def set_down(self, ids: list[str]) -> None:
        unknown = set(ids) - set(self.link_ids())
        if unknown:
            raise KeyError(f"unknown links: {sorted(unknown)}")
        self.down |= set(ids)

    def set_up(self, ids: list[str]) -> None:
        self.down -= set(ids)

    def capacity_to(self, dest: str) -> int:
        """Max-flow capacity from the UAE core to a region over links that are up."""
        g = nx.Graph()
        for l in self.links:
            if l["id"] not in self.down:
                if g.has_edge(l["a"], l["b"]):
                    g[l["a"]][l["b"]]["capacity"] += l["cap"]
                else:
                    g.add_edge(l["a"], l["b"], capacity=l["cap"])
        if ORIGIN not in g or dest not in g:
            return 0
        return int(nx.maximum_flow_value(g, ORIGIN, dest))

    def allocate(self, dest_override: dict[str, str] | None = None,
                 priority: list[str] | None = None) -> dict[str, ClassResult]:
        """Allocate capacity to every demand class. Returns results keyed by class id."""
        dest_override = dest_override or {}
        resid = {l["id"]: l["cap"] for l in self.links if l["id"] not in self.down}
        by_id = {l["id"]: l for l in self.links}

        classes = [dict(c, dest=dest_override.get(c["id"], c["dest"])) for c in self.demand]
        need = {c["id"]: c["cu"] for c in classes}
        got = {c["id"]: 0 for c in classes}
        ms_sum = {c["id"]: 0.0 for c in classes}
        dest = {c["id"]: c["dest"] for c in classes}

        def best_path(target: str):
            g = nx.Graph()
            for lid, cap in resid.items():
                if cap >= 1:
                    l = by_id[lid]
                    # keep the faster of parallel links as the edge, remember its id
                    if g.has_edge(l["a"], l["b"]) and g[l["a"]][l["b"]]["ms"] <= l["ms"]:
                        continue
                    g.add_edge(l["a"], l["b"], ms=l["ms"], lid=lid)
            if ORIGIN not in g or target not in g or not nx.has_path(g, ORIGIN, target):
                return None
            nodes = nx.shortest_path(g, ORIGIN, target, weight="ms")
            lids = [g[u][v]["lid"] for u, v in zip(nodes, nodes[1:])]
            return lids, sum(by_id[i]["ms"] for i in lids)

        def push_one(cid: str) -> bool:
            p = best_path(dest[cid])
            if p is None:
                return False
            lids, ms = p
            for i in lids:
                resid[i] -= 1
            got[cid] += 1
            ms_sum[cid] += ms
            return True

        if priority:
            order = [c for c in priority if c in need] + [c["id"] for c in classes if c["id"] not in priority]
            for cid in order:
                while got[cid] < need[cid] and push_one(cid):
                    pass
        else:
            # Equal-share fairness: the next unit always goes to the class with the
            # lowest delivered share so far (ties: config order). Without a priority
            # plan no class is favoured, approximating congestion without QoS.
            stuck: set[str] = set()
            order = [c["id"] for c in classes]
            while True:
                cands = [c for c in order if got[c] < need[c] and c not in stuck]
                if not cands:
                    break
                cid = min(cands, key=lambda c: (got[c] / need[c], order.index(c)))
                if not push_one(cid):
                    stuck.add(cid)

        out: dict[str, ClassResult] = {}
        for c in classes:
            cid = c["id"]
            avg = round(ms_sum[cid] / got[cid], 1) if got[cid] else None
            out[cid] = ClassResult(cid, dest[cid], need[cid], got[cid], avg,
                                   self._health(got[cid], need[cid], avg))
        return out

    def _health(self, delivered: int, demand: int, avg_ms: float | None) -> str:
        share = delivered / demand if demand else 1.0
        ok, deg = self.health["ok"], self.health["degraded"]
        if share >= ok["min_delivered"] and avg_ms is not None and avg_ms <= ok["max_ms"]:
            return "OK"
        if share >= deg["min_delivered"]:
            return "DEGRADED"
        return "DOWN"
