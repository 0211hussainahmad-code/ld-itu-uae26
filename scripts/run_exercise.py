"""Run one LinkDown exercise.

Live model (the only mode whose output may be shown as AI behaviour):
    export LINKDOWN_LLM_PROVIDER=gemini      # or groq | ollama | openrouter | openai
    export LINKDOWN_LLM_MODEL=gemini-2.5-flash
    export LINKDOWN_LLM_API_KEY=...          # not needed for ollama
    python scripts/run_exercise.py --variation V01

Plumbing check without any model (prints a NOT AI banner, labels every record):
    python scripts/run_exercise.py --test-double

Options:
    --human conservative | interactive | reject_all   (default conservative = SIMULATED human)
    --rounds N    message rounds per event (default 2)
    --list        show the 20 variations and exit
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from linkdown.audit import verify  # noqa: E402
from linkdown.orchestrator import Exercise, HumanPolicy  # noqa: E402
from linkdown.report import write_markdown  # noqa: E402
from linkdown.retrieval import Retriever  # noqa: E402
from linkdown.scenario import apply_variation, load_variations, load_yaml  # noqa: E402

BANNER = "=" * 72 + "\n  TEST DOUBLE - NOT AI. Scripted responses; checks plumbing only.\n" + "=" * 72


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variation", default=None, help="variation id, e.g. V01 (default: base scenario)")
    ap.add_argument("--test-double", action="store_true")
    ap.add_argument("--human", default="conservative", choices=["conservative", "interactive", "reject_all"])
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--kb", default=str(ROOT / "kb/build/chunks.jsonl"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    variations = load_variations(ROOT / "scenarios/variations.yaml")
    if a.list:
        for v in variations:
            print(f"{v['id']}  {v['data_class']:<24} {v['entity_type']:<24} uae_endpoint={v['uae_endpoint']!s:<5} "
                  f"hyok={v['hyok']!s:<5} x1_fails={v['x1_fails']!s:<5} expected={v['expected_e2']}")
        return 0
    v = next((x for x in variations if x["id"] == a.variation), None) if a.variation else None
    if a.variation and v is None:
        sys.exit(f"unknown variation {a.variation}")
    scenario = apply_variation(load_yaml(ROOT / "scenarios/base.yaml"), v)

    if a.test_double:
        from linkdown.testdouble import ScriptedTestDouble
        llm = ScriptedTestDouble()
        print(BANNER)
    else:
        from linkdown.llm import LLMClient, LLMConfig
        llm = LLMClient(LLMConfig.from_env())
        print(f"Live model: {llm.label}")

    if not Path(a.kb).exists():
        sys.exit("Knowledge base missing. Run: python kb/build_kb.py")
    ex = Exercise(scenario, llm, Retriever.load(a.kb), HumanPolicy(a.human), max_rounds=a.rounds)
    res = ex.run()
    md = write_markdown(res.out_dir)
    ok, msg = verify(res.out_dir / "audit.jsonl", ex.audit.prev)
    m = res.metrics
    print(f"\nrun: {res.out_dir.relative_to(ROOT)}")
    (res.out_dir / "audit_head.txt").write_text(ex.audit.prev + "\n", encoding="utf-8")
    print(f"audit: {'VERIFIED' if ok else 'FAILED'} - {msg}")
    print(f"AUDIT_HEAD {res.run_id} {ex.audit.prev}")
    print(f"model calls {m['model_calls']} (failed {m['model_failed']}), proposals {m['proposals']}, "
          f"outcomes {m['by_outcome']}, executed {m['executed']}, unsafe executed {m['unsafe_executed']}")
    print(f"E2 cross-border transfer outcomes: {m['e2_transfer_outcomes']}; records left UAE: {m['records_left_uae']}")
    print(f"report: {md.relative_to(ROOT)}")
    if a.test_double:
        print(BANNER)
    return 0 if ok and m["unsafe_executed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
