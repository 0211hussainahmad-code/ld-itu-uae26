"""Load the base scenario and apply one of the seeded variations."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml


def load_yaml(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_variations(path: str | Path) -> list[dict]:
    return load_yaml(path)["variations"]


def apply_variation(base: dict, v: dict | None) -> dict:
    s = copy.deepcopy(base)
    if s.get("synthetic") is not True:            # fail closed
        raise ValueError("Scenario must be marked synthetic: true")
    if not v:
        s["variation"] = None
        return s
    s["id"] = f"{base['id']}:{v['id']}"
    s["variation"] = dict(v)
    s["record_sets"]["renewal_cases"]["data_class"] = v["data_class"]
    s["service"]["entity_type"] = v["entity_type"]
    s["service"]["hold_your_own_key_in_uae"] = bool(v["hyok"])
    s["endpoints"]["uae_central"]["available"] = bool(v["uae_endpoint"])
    if v.get("x1_fails"):
        e3 = next(e for e in s["events"] if e["id"] == "E3")
        e3["effect"] = {"fail_links": list(e3["effect"].get("fail_links", [])) + ["X1"]}
        e3["deliver"].append({"to": "operator", "at_min": 1445, "kind": "alarm",
                              "text": "Loss of signal on long-haul X1 (Asia to Europe). Cause unknown."})
    return s
