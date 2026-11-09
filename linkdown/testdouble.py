"""SCRIPTED TEST DOUBLE - NOT AI.

Used only by automated tests and by `--test-double` dry runs, to exercise the
gate, state and audit plumbing without a model. Every record it produces is
labelled is_ai=false and model "TEST-DOUBLE-NOT-AI". The demo, the evaluation
and every judge-facing artefact must use a real model (Shenzhen lesson M01).

It deliberately proposes one unsafe action (copying confidential case files
abroad) so tests can prove the gate stops it.
"""
from __future__ import annotations

import re

from .llm import LLMResult

LABEL = "TEST-DOUBLE-NOT-AI"


class ScriptedTestDouble:
    is_ai = False
    label = LABEL

    def complete_json(self, system: str, user: str) -> LLMResult:
        ids = re.findall(r"^\[([^\]]+)\]", user, flags=re.M)
        cite = ids[:1]
        t = int(re.search(r"T\+(\d+)", user).group(1))
        role = ("operator" if "Network operations" in system else
                "service" if "government AI service" in system else
                "regulator" if "Regulator role" in system else "adviser")
        gap_mode = "GAP REGISTER" in user
        data: dict = {"assessment": f"[{LABEL}] scripted turn for {role} at T+{t}.", "unknowns": ["cause of failure"],
                      "messages": [], "actions": []}
        if gap_mode:
            for gid in re.findall(r"^- (G\d+):", user, flags=re.M):
                data["actions"].append({"tool": "record_gap_observation", "cites": cite,
                                        "args": {"gap_id": gid, "status": "hypothesis",
                                                 "wording": f"[{LABEL}] Publicly available sources reviewed did not establish {gid} (scripted)."}})
        elif role == "operator" and t < 120:
            data["messages"].append({"to": "regulator", "text": "W1 and W2 down, cause unknown. Westbound capacity reduced.", "cites": []})
            data["actions"].append({"tool": "reroute_traffic", "args": {"note": "use W3, terrestrial and long-haul"}, "why": "keep traffic flowing"})
        elif role == "service" and t < 120:
            data["messages"].append({"to": "adviser", "text": "Which rules apply if we move case files to another region?", "cites": []})
        elif role == "service" and 120 <= t < 1440:
            data["actions"].append({"tool": "transfer_records", "args": {"record_set": "renewal_cases", "dest_region": "asia_south"},
                                    "why": "naive fallback (scripted unsafe proposal)", "cites": cite})
            data["actions"].append({"tool": "switch_ai_endpoint", "args": {"region": "uae_central"}, "why": "in-country option", "cites": cite})
        elif role == "regulator" and t >= 1440:
            order = ["hospitals", "emergency", "gov_ai"]
            data["actions"].append({"tool": "recommend_priority_plan", "args": {"order": order, "rationale": "protect life-critical traffic"}, "cites": cite})
            data["actions"].append({"tool": "issue_priority_order", "args": {"order": order}, "cites": cite})
        elif role == "regulator":
            data["actions"].append({"tool": "request_information", "args": {"to": "operator", "question": "Expected repair time?"}})
        elif role == "adviser":
            data["messages"].append({"to": "ALL", "text": "See cited passage; applicability depends on data classification.", "cites": cite + ["made-up#c999"]})
        return LLMResult(True, data, "", "test-double", LABEL, 0, {}, None, is_ai=False)
