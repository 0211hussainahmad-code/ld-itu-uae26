"""Offline regressions for the November 6 partial live evidence failures."""
import json
from pathlib import Path

import httpx
import pytest

from conftest import ROOT
from exercise_demo.demonstration import FullExercise, ROLES, inspect_demonstration
from linkdown.audit import GENESIS, _h
from linkdown.orchestrator import HumanPolicy
from linkdown.retrieval import Retriever
from linkdown.scenario import apply_variation
from linkdown.testdouble import ScriptedTestDouble
from test_demonstration import or_client, or_mock


class UnicodeDouble(ScriptedTestDouble):
    def complete_json(self, system, user):
        result = super().complete_json(system, user)
        if "Network operations" in system:
            result.data["actions"] = [
                {"tool": "apply_operator_qos", "args": {"order": ["hospitals", "emergency", "gov_ai", "business"]}},
                {"tool": "reroute_traffic", "args": {"note": "low‑priority EU‑west تنسيق"}},
            ]
        return result


@pytest.fixture
def unicode_run(base_scenario, tmp_path):
    exercise = FullExercise(apply_variation(base_scenario, None), {r: UnicodeDouble() for r in ROLES},
                            Retriever.load(ROOT / "kb/build/chunks.jsonl"),
                            HumanPolicy("conservative"), out_root=tmp_path)
    result = exercise.run()
    return result.out_dir, exercise.audit.prev


def test_cp1252_default_preserves_unicode_and_final_state(unicode_run, monkeypatch):
    run, head = unicode_run
    original_read = Path.read_text
    reads = {}

    def cp1252_read(path, *args, **kwargs):
        reads[path] = kwargs.get("encoding")
        if not args and kwargs.get("encoding") is None:
            kwargs["encoding"] = "cp1252"
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", cp1252_read)
    report = inspect_demonstration(run, head)
    assert report["passed"], report["problems"]
    assert all(reads[path] == "utf-8" for path in
               [run / "audit.jsonl", run / "report.json", *list((run / "turns").glob("*.json"))])
    records = [json.loads(line) for line in original_read(run / "audit.jsonl", encoding="utf-8").splitlines()]
    actions = [r["payload"] for r in records if r["kind"] == "ACTION_RESULT"]
    assert any(p["tool"] == "reroute_traffic" and "‑" in p["args"]["note"] for p in actions)
    assert all(p["state_before"] == p["state_after"] for p in actions)
    assert report["independent_final_state"]["digest"] == records[-1]["payload"]["final_state_digest"]
    assert report["independent_final_state"]["clock_min"] == records[-1]["sim_min"]


def rechain_fixture(run, records):
    """Only synthetic test fixtures are rehashed, never external run evidence."""
    prev = GENESIS
    for r in records:
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        r["prev"], r["hash"] = prev, _h(prev, body)
        prev = r["hash"]
    (run / "audit.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                    encoding="utf-8")
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    report["audit_head"] = prev
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return prev


@pytest.mark.parametrize("damage", ["gate_id", "result_id", "event_before", "event_after", "final_clock"])
def test_precise_fail_closed_diagnostics(unicode_run, damage):
    run, _ = unicode_run
    records = [json.loads(s) for s in (run / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    if damage == "gate_id":
        row = next(r for r in records if r["kind"] == "GATE_DECISION")
        reconstructed = row["payload"]["action_id"]
        row["payload"]["action_id"] = "forged-id"
        expected = ["Action ID mismatch", "recorded=forged-id", f"reconstructed={reconstructed}",
                    f"seq {row['seq']}", "version=", "digest=", "clock="]
    elif damage == "result_id":
        row = next(r for r in records if r["kind"] == "ACTION_RESULT")
        row["payload"]["action_id"] = "missing-id"
        expected = ["No reconstructed gate decision", "missing-id", f"seq {row['seq']}"]
    elif damage in ("event_before", "event_after"):
        row = next(r for r in records if r["kind"] == "EVENT")
        row["payload"]["state_before" if damage == "event_before" else "state_after"] = "wrong"
        expected = ["Event starting state differs" if damage == "event_before" else "Event resulting state differs"]
    else:
        records[-1]["sim_min"] += 1
        expected = ["Independently replayed final state differs", "clock="]
    result = inspect_demonstration(run, rechain_fixture(run, records))
    assert not result["passed"]
    assert all(word in " ".join(result["problems"]) for word in expected), result


@pytest.mark.parametrize("failure", ["http429", "http500", "transport", "missing_usage"])
def test_every_unreceipted_request_stays_unresolved(tmp_path, failure):
    posts, gets = [], []
    success = or_mock(posts, gets)
    count = 0

    def handler(request):
        nonlocal count
        if request.method == "POST":
            count += 1
            if count == 10:
                if failure == "transport":
                    raise httpx.ReadTimeout("offline fixture")
                if failure == "missing_usage":
                    response = success(request)
                    body = response.json()
                    del body["usage"]
                    return httpx.Response(200, json=body)
                return httpx.Response(429 if failure == "http429" else 500, json={"error": {"code": 429}})
        return success(request)

    client, budget = or_client(tmp_path, handler)
    for _ in range(9):
        assert client.complete_json("SYSTEM", "USER").ok
    assert not client.complete_json("SYSTEM", "USER").ok
    reserved = budget.reserved
    assert not client.complete_json("SYSTEM", "USER").ok
    summary = budget.summary()
    assert count == summary["requests_sent"] == 10
    assert summary["requests_without_reported_usage"] == 1
    assert summary["requests_without_verified_charge"] == (0 if failure == "missing_usage" else 1)
    assert summary["reserved_usd"] == reserved
    assert summary["reported_usd"] > 0
    assert summary["halted"]
