"""End-to-end runs with the scripted test double (NOT AI) and the LLM client
against a mocked HTTP provider. These prove the plumbing, not model quality."""
import copy
import json

import httpx
import pytest
import yaml

from linkdown import llm as llm_mod
from linkdown.audit import verify
from linkdown.gate import PROHIBITED
from linkdown.orchestrator import Exercise, HumanPolicy
from linkdown.report import write_markdown
from linkdown.retrieval import Retriever
from linkdown.scenario import apply_variation
from linkdown.testdouble import ScriptedTestDouble

from conftest import ROOT

KB = ROOT / "kb/build/chunks.jsonl"
pytestmark = pytest.mark.skipif(not KB.exists(), reason="run python kb/build_kb.py first")


def run(base, tmp_path, variation=None, human="conservative", rules_path=None, ledger_path=None, manifest_path=None):
    sc = apply_variation(base, variation)
    kw = {k: v for k, v in (("rules_path", rules_path), ("ledger_path", ledger_path),
                            ("manifest_path", manifest_path)) if v}
    ex = Exercise(sc, ScriptedTestDouble(), Retriever.load(KB), HumanPolicy(human), out_root=tmp_path, **kw)
    res = ex.run()
    recs = [json.loads(l) for l in (res.out_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    return ex, res, recs


def test_base_run_is_safe_audited_and_labelled(base_scenario, tmp_path):
    ex, res, recs = run(base_scenario, tmp_path)
    m = res.metrics
    assert m["unsafe_executed"] == 0 and m["cross_border_executed"] == 0
    assert m["cross_border_proposals"] >= 1 and not m["records_left_uae"]
    assert m["e2_transfer_outcomes"] and set(m["e2_transfer_outcomes"]) == {"INSUFFICIENT_AUTHORITY_OR_EVIDENCE"}
    assert m["final_service"]["endpoint_region"] == "uae_central"        # the lawful best move was taken
    assert m["unsupported_citations"] >= 1                                 # invented citation was caught
    assert verify(res.out_dir / "audit.jsonl", ex.audit.prev)[0]
    # nothing produced by the test double can pass as AI
    assert recs[0]["kind"] == "RUN_START" and recs[0]["payload"]["is_ai"] is False
    assert all(r["is_ai"] is False for r in recs if r["kind"] == "AGENT_TURN")
    assert "TEST DOUBLE - NOT AI" in write_markdown(res.out_dir).read_text(encoding="utf-8")
    assert len(res.observations) == 5 and all("draft" in o["review_status"] for o in res.observations)


def test_simulated_clock_never_runs_backwards(base_scenario, tmp_path):
    _, _, recs = run(base_scenario, tmp_path)
    times = [r["sim_min"] for r in recs if r["sim_min"] is not None and r["kind"] != "RUN_END"]
    assert times == sorted(times)


def test_every_state_change_follows_a_non_prohibited_gate_decision(base_scenario, tmp_path):
    _, _, recs = run(base_scenario, tmp_path)
    for i, r in enumerate(recs):
        if r["kind"] == "STATE_CHANGE":
            gates = [g for g in recs[:i] if g["kind"] == "GATE_DECISION"
                     and g["payload"]["tool"] == r["payload"]["tool"] and g["payload"]["args"] == r["payload"]["args"]]
            assert gates and gates[-1]["payload"]["outcome"] != PROHIBITED


def test_verified_rules_refuse_without_asking_a_human(base_scenario, tmp_path):
    from conftest import verified_bundle
    rules, ledger, manifest = verified_bundle(yaml.safe_load((ROOT / "config/rules.yaml").read_text(encoding="utf-8")))
    p, lp, mp = tmp_path / "rules.yaml", tmp_path / "ledger.yaml", tmp_path / "manifest.json"
    p.write_text(yaml.safe_dump(rules), encoding="utf-8")
    lp.write_text(yaml.safe_dump(ledger), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    _, res, recs = run(base_scenario, tmp_path, rules_path=p, ledger_path=lp, manifest_path=mp)
    assert set(res.metrics["e2_transfer_outcomes"]) == {PROHIBITED}
    assert not [r for r in recs if r["kind"] == "HUMAN_DECISION" and r["payload"]["tool"] == "transfer_records"]


def _verified_files(tmp_path):
    from conftest import verified_bundle
    rules, ledger, manifest = verified_bundle(yaml.safe_load((ROOT / "config/rules.yaml").read_text(encoding="utf-8")))
    p, lp, mp = tmp_path / "rules.yaml", tmp_path / "ledger.yaml", tmp_path / "manifest.json"
    p.write_text(yaml.safe_dump(rules), encoding="utf-8")
    lp.write_text(yaml.safe_dump(ledger), encoding="utf-8")
    mp.write_text(json.dumps(manifest), encoding="utf-8")
    return {"rules_path": p, "ledger_path": lp, "manifest_path": mp}


def test_permitted_cross_border_transfer_happens_only_with_human_approval(base_scenario, variations, tmp_path, monkeypatch):
    v03 = next(v for v in variations if v["id"] == "V03")   # baseline data, keys in UAE, no UAE endpoint
    vf = _verified_files(tmp_path)                          # only VERIFIED rules can permit (FIXTURE ledger)
    _, res, _ = run(base_scenario, tmp_path, v03, human="reject_all", **vf)
    assert res.metrics["cross_border_executed"] == 0
    monkeypatch.setattr(HumanPolicy, "decide", lambda self, role, a, d: (True, "test: approve", ""))
    _, res, _ = run(base_scenario, tmp_path, v03, **vf)
    assert res.metrics["cross_border_executed"] >= 1 and res.metrics["unsafe_executed"] == 0


def test_unverified_permission_does_not_let_a_transfer_through(base_scenario, variations, tmp_path, monkeypatch):
    v03 = next(v for v in variations if v["id"] == "V03")   # same case, real (unverified) rules
    monkeypatch.setattr(HumanPolicy, "decide", lambda self, role, a, d: (True, "test: approve", ""))
    _, res, _ = run(base_scenario, tmp_path, v03)
    assert res.metrics["cross_border_executed"] == 0       # operational click cannot authorise INSUFFICIENT


# ---------------- live client against a mocked provider ----------------
def _client(handler):
    c = llm_mod.LLMClient(llm_mod.LLMConfig(provider="custom", model="m", base_url="http://mock/v1"))
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def _ok(text, usage=None):
    return httpx.Response(200, json={"model": "m-1", "choices": [{"message": {"content": text}}],
                                     "usage": usage or {"total_tokens": 42}})


def test_llm_client_parses_fenced_json_and_records_usage():
    c = _client(lambda req: _ok('```json\n{"assessment": "ok", "actions": []}\n```'))
    r = c.complete_json("s", "u")
    assert r.ok and r.data["assessment"] == "ok" and r.is_ai and r.usage["total_tokens"] == 42 and r.model == "m-1"


def test_llm_client_drops_json_mode_when_unsupported():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format not supported")
        return _ok('{"assessment": "fine"}')
    r = _client(handler).complete_json("s", "u")
    assert r.ok and seen == [True, False]


def test_llm_client_retries_rate_limits(monkeypatch):
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    calls = iter([httpx.Response(429, text="slow down"), _ok('{"a": 1}')])
    r = _client(lambda req: next(calls)).complete_json("s", "u")
    assert r.ok and r.data == {"a": 1}


def test_llm_client_honours_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: slept.append(s))
    calls = iter([httpx.Response(429, headers={"retry-after": "7"}, text="tpm"), _ok('{"a": 1}')])
    r = _client(lambda req: next(calls)).complete_json("s", "u")
    assert r.ok and slept == [7.0]


def test_llm_client_records_provider_request_ids():
    r = _client(lambda req: httpx.Response(
        200, headers={"x-request-id": "req_abc"},
        json={"id": "chatcmpl-1", "model": "m-1", "usage": {"total_tokens": 5},
              "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]})).complete_json("s", "u")
    assert (r.request_id, r.response_id, r.finish_reason, r.model) == ("req_abc", "chatcmpl-1", "stop", "m-1")
    r = _client(lambda req: httpx.Response(
        200, json={"id": "c2", "x_groq": {"id": "req_groq"}, "choices": [{"message": {"content": '{"a": 1}'}}]}
    )).complete_json("s", "u")
    assert r.request_id == "req_groq" and r.finish_reason is None


def test_llm_client_reports_failure_honestly():
    r = _client(lambda req: httpx.Response(401, text="bad key")).complete_json("s", "u")
    assert not r.ok and "401" in r.error and r.data is None


# ---------------- smoke script over real HTTP to a local MOCK server (not AI) ----------------
def test_smoke_live_script_end_to_end_against_local_mock_server(tmp_path):
    import os
    import subprocess
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    reply = {"assessment": "Links W1/W2 are down; moving case files abroad is not established as lawful.",
             "unknowns": ["repair time"], "messages": [],
             "actions": [{"tool": "transfer_records", "args": {"record_set": "renewal_cases", "dest_region": "asia_south"},
                          "why": "mock", "cites": []},
                         {"tool": "switch_ai_endpoint", "args": {"region": "uae_central"}, "why": "mock", "cites": []}]}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"model": "MOCK-SERVER-NOT-AI", "usage": {"total_tokens": 1},
                               "choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, LINKDOWN_LLM_PROVIDER="custom", LINKDOWN_LLM_MODEL="MOCK-SERVER-NOT-AI",
               LINKDOWN_LLM_BASE_URL=f"http://127.0.0.1:{srv.server_address[1]}/v1",
               NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
    out = subprocess.run([sys.executable, str(ROOT / "scripts/smoke_live.py"), "--out", str(tmp_path)],
                         capture_output=True, text=True, env=env, timeout=120)
    srv.shutdown()
    assert out.returncode == 0, out.stdout + out.stderr
    assert "INSUFFICIENT_AUTHORITY_OR_EVIDENCE" in out.stdout and "audit: VERIFIED" in out.stdout
    assert "service.endpoint_region" in out.stdout          # the allowed action changed the state
    assert "AUDIT_HEAD" in out.stdout
    run_dir = next(p for p in tmp_path.iterdir() if p.is_dir() and (p / "audit.jsonl").exists())
    rp = subprocess.run([sys.executable, str(ROOT / "scripts/replay.py"), str(run_dir)],
                        capture_output=True, text=True, timeout=120)
    assert rp.returncode == 0 and "REPLAY: PASS" in rp.stdout, rp.stdout
