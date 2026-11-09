"""Write the synthetic cross-language test fixture used by the browser verifier's unit tests.

The fixture is a schema-valid bundle built from a synthetic audit log written by the frozen
engine's own AuditLog, with deliberately awkward values (non-ASCII, U+2028, floats that
print differently in JS and Python, large integers). It is labelled as a test fixture, lives
under web/app/tests/fixtures/ and is never published.

    python web/tools/make_chain_fixture.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linkdown.audit import AuditLog  # noqa: E402
from web.bundler.canonical import bundle_bytes, canonical_body, sha256_hex  # noqa: E402
from web.bundler.schema import SCHEMA_ID, validate_bundle  # noqa: E402

OUT = ROOT / "web/app/tests/fixtures/synthetic-bundle.json"
EXPECTED = ROOT / "web/app/tests/fixtures/synthetic-bundle.expected.json"
TRICKY = {"floats": [0.1, 1.0, 1e-07, 0.667, 2.5e20, -0.0, 98.0], "ints": [0, -3, 2 ** 53 + 1],
          "text": "café — ٱلإمارات 🛰   sep   para \x85 nel \"quoted\" \\ back\ttab",
          "none": None, "flags": [True, False], "nested": {"z": 1, "a": [{"b": "x"}]}}


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        log = AuditLog(Path(td) / "audit.jsonl", "synthetic-fixture-run")
        log.append("RUN_START", "orchestrator", {"scenario": "synthetic-fixture", "model": "TEST-DOUBLE-NOT-AI",
                                                 "is_ai": False, "human": "simulated-human:conservative",
                                                 "variation": None, "rules_version": "fixture",
                                                 "prompt_version": "fixture", "inputs": {}}, sim_min=0)
        for i in range(1, 9):
            log.append(("EVENT", "MESSAGE", "GATE_DECISION")[i % 3], f"actor-{i % 4}", {"i": i, **TRICKY},
                       sim_min=i * 10, latency_ms=i * 0.5)
        text = (Path(td) / "audit.jsonl").read_text(encoding="utf-8")
        records = [json.loads(l) for l in text.split("\n") if l.strip()]
    sp = records[0]["payload"]
    audit = [{"seq": r["seq"], "kind": r["kind"], "actor": r["actor"], "prev": r["prev"], "hash": r["hash"],
              "body": canonical_body(r), "withheld": False} for r in records]
    head = records[-1]["hash"]
    bundle = {
        "schema": SCHEMA_ID,
        "provenance": {"mode": "offline-NOT-AI", "label": "SYNTHETIC TEST FIXTURE — not a published bundle",
                       "run_id": records[0]["run_id"], "scenario": sp["scenario"], "scenario_version": None,
                       "variation": None, "model": sp["model"], "is_ai": False, "human": sp["human"],
                       "rules_version": "fixture", "roles_version": None, "topology_version": None,
                       "prompt_version": "fixture", "inputs": {}, "source_commit": "0" * 40,
                       "generator_run_url": "local:fixture", "audit_head": head, "record_count": len(audit),
                       "withheld_count": 0,
                       "inspect": {"passed": True, "mode": "offline-NOT-AI", "coverage": {}, "problems": [],
                                   "replay": [], "human": sp["human"], "human_decisions": 0, "served_by": [],
                                   "limitations": ["Synthetic fixture for verifier tests only."], "metrics": {}}},
        "context": {k: {"sha256": "0" * 64, "data": {}} for k in ("topology", "roles", "scenario")},
        "audit": audit,
        "sources": {},
    }
    problems = validate_bundle(bundle)
    if problems:
        raise SystemExit("fixture is not schema-valid: " + "; ".join(problems))
    data = bundle_bytes(bundle)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    EXPECTED.write_text(json.dumps({"audit_head": head, "sha256": sha256_hex(data), "records": len(audit)},
                                   indent=2) + "\n", encoding="utf-8")
    print(f"fixture written: {len(audit)} records, head {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
