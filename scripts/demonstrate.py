"""Run/verify the four-role E1-E3 demonstration. Default: offline, NOT AI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercise_demo.demonstration import FullExercise, ROLES, inspect_demonstration, max_model_turns
from linkdown.orchestrator import HumanPolicy
from linkdown.retrieval import Retriever
from linkdown.report import write_markdown
from linkdown.scenario import apply_variation, load_yaml
from linkdown.testdouble import ScriptedTestDouble

MAX_ROUNDS = 2
PLAN_KEYS = ("provider", "model", "approval_reference", "cap_usd", "input_per_million", "output_per_million")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "runs/demonstrations")
    ap.add_argument("--verify", type=Path)
    ap.add_argument("--expected-head")
    ap.add_argument("--require-live", action="store_true",
                    help="With --verify: fail unless every turn came from the reviewed live provider/model")
    ap.add_argument("--require-interactive-human", action="store_true",
                    help="With --verify: fail unless the controller and every decision were human:interactive")
    ap.add_argument("--live-plan", type=Path, help="Reviewed JSON plan; does not authorize spending")
    ap.add_argument("--authorize-live-spend", action="store_true",
                    help="Use only after separate explicit team approval of this exact plan")
    ap.add_argument("--preflight-only", action="store_true",
                    help="With --live-plan: validate the plan and run the free read-only provider checks "
                         "(OpenRouter key limit and endpoint list); no completion request, no ledger")
    a = ap.parse_args()
    if a.verify:
        if not a.expected_head:
            ap.error("Verification requires --expected-head retained outside the run folder")
        report = inspect_demonstration(a.verify, a.expected_head, require_live=a.require_live,
                                       require_interactive_human=a.require_interactive_human)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] else 1
    if a.require_live or a.require_interactive_human:
        ap.error("--require-live / --require-interactive-human apply to --verify")
    if a.preflight_only:
        if not a.live_plan or a.authorize_live_spend:
            ap.error("--preflight-only needs --live-plan and never spends (omit --authorize-live-spend)")
    elif bool(a.live_plan) != a.authorize_live_spend:
        ap.error("A reviewed --live-plan AND separate --authorize-live-spend are required")
    ret = Retriever.load(ROOT / "kb/build/chunks.jsonl")
    sc = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), None)
    budget = None
    if a.live_plan:
        import os
        import uuid
        import httpx
        from exercise_demo.demo_provider import (MAX_REQUESTS, PROFILES, PROMPT_BYTE_LIMIT, DemoBudget,
                                                 DemoClient, openrouter_preflight, profile_for, worst_case_usd)
        from linkdown.llm import LLMConfig
        plan = json.loads(a.live_plan.read_text())
        if not isinstance(plan, dict) or any(k not in plan for k in PLAN_KEYS):
            ap.error("Plan requires " + ", ".join(PLAN_KEYS))
        # Reviewed profiles only: the request body (including OpenRouter's Groq pin)
        # comes from the profile, never from the plan. No other provider or route, no
        # model fallback.
        profile = profile_for(plan["provider"], plan["model"])
        if profile is None:
            ap.error("Reviewed demo supports only: " + ", ".join(
                f"{p['provider']} {p['model']}" for p in PROFILES.values()) + "; no routing substitution")
        if not plan.get("approval_reference") and not a.preflight_only:
            ap.error("Plan requires a separate approval reference")
        # Refuse before any file or request if the run could be cut off part-way
        # by the request or spending limit after paid turns.
        turns = max_model_turns(sc, MAX_ROUNDS)
        if turns > MAX_REQUESTS:
            ap.error(f"Up to {turns} turns exceed the {MAX_REQUESTS}-request demo limit")
        cap = profile["request"]["max_completion_tokens"]
        try:
            low = profile["min_price_usd_per_mtok"]
            if plan["input_per_million"] < low["input"] or plan["output_per_million"] < low["output"]:
                ap.error(f"Plan prices are below the documented prices USD {low['input']} / {low['output']} "
                         f"per million (checked {profile['checked']}); reservations would under-count")
            per_turn = worst_case_usd(PROMPT_BYTE_LIMIT, cap, plan["input_per_million"],
                                      plan["output_per_million"])
            if not plan["cap_usd"] >= turns * per_turn:
                ap.error(f"cap_usd must be at least USD {turns * per_turn:.4f} (worst case for {turns} turns "
                         f"at these prices) so the cap cannot cut the run off after paid turns")
        except TypeError:
            ap.error("Prices and cap must be numbers")
        key = os.environ.get("LINKDOWN_LLM_API_KEY")
        if not key:
            ap.error("Set LINKDOWN_LLM_API_KEY privately; never put it in the plan")
        preflight = {"ok": True, "problems": [], "evidence": {}, "note": "no free provider check for this profile"}
        if profile["serving"] == "pinned":
            # Free, read-only GETs (key limit, endpoint list); refused before any file or paid call.
            with httpx.Client(timeout=30.0) as http:
                preflight = openrouter_preflight(http, key, profile, plan["cap_usd"], plan["input_per_million"],
                                                 plan["output_per_million"], turns * per_turn)
        if a.preflight_only:
            print(json.dumps({**preflight, "worst_case_usd": round(turns * per_turn, 6),
                              "profile": f"{profile['provider']}:{profile['model']}",
                              "request_fields": profile["request"]}, indent=2))
            return 0 if preflight["ok"] else 1
        if not preflight["ok"]:
            print(json.dumps(preflight, indent=2))
            ap.error("Provider preflight failed: " + "; ".join(preflight["problems"]))
        parent = a.out / uuid.uuid4().hex
        budget = DemoBudget(parent / "reservations.jsonl", cap_usd=plan["cap_usd"],
                            input_per_million=plan["input_per_million"],
                            output_per_million=plan["output_per_million"],
                            min_interval_s=plan.get("min_interval_s", 0))
        # No base_url: the provider's documented endpoint only (Groq or OpenRouter preset).
        clients = {r: DemoClient(LLMConfig(provider=plan["provider"], model=plan["model"], api_key=key,
                                          max_tokens=cap), budget) for r in ROLES}
        human = HumanPolicy("interactive")
        # Whitelist metadata; never copy arbitrary plan fields into evidence.
        (parent / "approved_plan.json").write_text(json.dumps({**{k: plan[k] for k in PLAN_KEYS + (
            ("min_interval_s",) if "min_interval_s" in plan else ())}, "request_fields": profile["request"],
            "preflight": preflight}, indent=2))
    else:
        print("OFFLINE TEST DOUBLE — NOT AI; no provider calls")
        clients = {r: ScriptedTestDouble() for r in ROLES}
        human, parent = HumanPolicy("conservative"), a.out
    ex = FullExercise(sc, clients, ret, human, out_root=parent, max_rounds=MAX_ROUNDS)
    res = ex.run()
    write_markdown(res.out_dir)
    head = ex.audit.prev
    live = budget is not None
    result = inspect_demonstration(res.out_dir, head, require_live=live, require_interactive_human=live)
    (res.out_dir / "demonstration.json").write_text(json.dumps(result, indent=2))
    if budget is not None:
        spend = budget.summary()
        (parent / "spend_summary.json").write_text(json.dumps(spend, indent=2))
        print("SPEND " + json.dumps(spend))
    print(f"RUN_DIR {res.out_dir}")
    print(f"AUDIT_HEAD {head}")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
