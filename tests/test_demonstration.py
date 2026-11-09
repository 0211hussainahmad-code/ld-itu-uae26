"""Complete offline exercise proof; nothing in this file calls a model provider.

Live-transport tests use httpx.MockTransport only (no network, no key, no spend)."""
import json
import re

import httpx
import pytest

from exercise_demo.demonstration import FullExercise, ROLES, inspect_demonstration, max_model_turns
from exercise_demo.demo_provider import GROQ_CHAT_URL, MAX_REQUESTS, PROFILES, DemoBudget, DemoClient
from linkdown.llm import LLMConfig, LLMResult
from linkdown.orchestrator import HumanPolicy
from linkdown.retrieval import Retriever
from linkdown.scenario import apply_variation
from linkdown.testdouble import ScriptedTestDouble
from conftest import ROOT


@pytest.fixture
def exercise(base_scenario, tmp_path):
    # Missing KB is a failure, never a silently skipped full-exercise proof.
    return FullExercise(apply_variation(base_scenario, None),
                        {r: ScriptedTestDouble() for r in ROLES},
                        Retriever.load(ROOT / "kb/build/chunks.jsonl"),
                        HumanPolicy("conservative"), out_root=tmp_path)


def test_all_roles_all_events_with_replay_and_information_limits(exercise):
    result = exercise.run()
    report = inspect_demonstration(result.out_dir, exercise.audit.prev)
    assert report["passed"], report
    assert report["mode"] == "offline-NOT-AI"
    assert all(n >= 1 for roles in report["coverage"].values() for n in roles.values())
    assert result.metrics["cross_border_executed"] == 0
    assert result.metrics["human_rejected"] >= 2  # E2 transfer and E3 binding order
    assert result.metrics["final_service"]["endpoint_region"] == "uae_central"
    assert result.metrics["primary_text_citations"] > 0
    assert result.metrics["unsupported_citations"] > 0  # deliberate hostile citation
    deliveries = [d for e in exercise.scenario["events"] for d in e["deliver"]]
    for path in (result.out_dir / "turns").glob("*.json"):
        role = path.stem.split("_", 1)[1]
        prompt = json.loads(path.read_text())["user"]
        minute = int(re.search(r"T\+(\d+)", prompt).group(1))
        for d in deliveries:
            if d["to"] != role or d["at_min"] > minute:
                assert d["text"] not in prompt
        if role != "service":
            assert "renewal_cases" not in prompt.split("INBOX")[0]
        if role == "adviser":
            assert '"synthetic": true\n}' in prompt.split("INBOX")[0]


def test_e3_explicit_simulated_authority_changes_state(exercise):
    class Controller(HumanPolicy):
        def decide(self, role, action, decision):
            return (action["tool"] == "issue_priority_order", "offline test controller",
                    "exercise decision: protect life-critical traffic")
    exercise.human = Controller()
    result = exercise.run()
    assert inspect_demonstration(result.out_dir, exercise.audit.prev)["passed"]
    assert result.metrics["cross_border_executed"] == 0
    assert exercise.state.priority_plan == ["hospitals", "emergency", "gov_ai"]
    assert exercise.state.traffic()["hospitals"]["health"] == "OK"
    assert result.metrics["authority_decisions_approved"] > 0


@pytest.mark.parametrize("damage", ["turn", "truncation", "report", "missing_file"])
def test_evidence_damage_fails(exercise, damage):
    result = exercise.run()
    if damage in ("turn", "missing_file"):
        path = next((result.out_dir / "turns").glob("*.json"))
        path.unlink() if damage == "missing_file" else path.write_text("{}")
    elif damage == "truncation":
        path = result.out_dir / "audit.jsonl"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    else:
        path = result.out_dir / "report.json"
        rep = json.loads(path.read_text())
        rep["final_state"]["service"]["endpoint_region"] = "asia_south"
        path.write_text(json.dumps(rep))
    assert not inspect_demonstration(result.out_dir, exercise.audit.prev)["passed"]


def test_one_failed_role_never_counts_as_full_success(exercise):
    class Failed(ScriptedTestDouble):
        def complete_json(self, system, user):
            return LLMResult(False, None, "", "test-double", self.label, 0, {}, "fixture failure", is_ai=False)
    exercise.clients["adviser"] = Failed()
    result = exercise.run()
    report = inspect_demonstration(result.out_dir, exercise.audit.prev)
    assert not report["passed"]
    assert "Missing successful role/event turns" in report["problems"]


def test_empty_json_is_not_a_successful_role_decision(exercise):
    class Empty(ScriptedTestDouble):
        def complete_json(self, system, user):
            return LLMResult(True, {}, "{}", "test-double", self.label, 0, {}, is_ai=False)
    exercise.clients["adviser"] = Empty()
    result = exercise.run()
    assert not inspect_demonstration(result.out_dir, exercise.audit.prev)["passed"]


def test_replay_rejects_removed_human_approval_even_if_rechained(exercise):
    from linkdown.audit import GENESIS, _h
    exercise.human.decide = lambda role, a, d: (a["tool"] == "issue_priority_order", "test", "exercise decision: test")
    result = exercise.run()
    path = result.out_dir / "audit.jsonl"
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    prev, rewritten = GENESIS, []
    for r in rows:
        if r["kind"] == "HUMAN_DECISION" and r["payload"]["approved"]:
            continue
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        body["seq"] = len(rewritten) + 1
        new = {**body, "prev": prev, "hash": _h(prev, body)}
        prev = new["hash"]
        rewritten.append(new)
    path.write_text("".join(json.dumps(r) + "\n" for r in rewritten))
    rp = result.out_dir / "report.json"
    rep = json.loads(rp.read_text()); rep["audit_head"] = prev
    rp.write_text(json.dumps(rep))
    report = inspect_demonstration(result.out_dir, prev)
    assert not report["passed"] and "Missing matching human approval" in report["problems"]


def test_repeated_runs_never_overwrite(base_scenario, tmp_path):
    runs = [FullExercise(base_scenario, {r: ScriptedTestDouble() for r in ROLES},
                         Retriever.load(ROOT / "kb/build/chunks.jsonl"), HumanPolicy(), tmp_path)
            for _ in range(2)]
    assert runs[0].out != runs[1].out


MODEL = "openai/gpt-oss-120b"
GROQ = PROFILES["groq:" + MODEL]
PRICE = GROQ["min_price_usd_per_mtok"]


def client(tmp_path, handler, budget=None, **kw):
    budget = budget or DemoBudget(tmp_path / "reservations.jsonl", cap_usd=1, input_per_million=PRICE["input"],
                                  output_per_million=PRICE["output"], **kw)
    c = DemoClient(LLMConfig(provider="groq", model=MODEL, api_key="TEST-KEY-NOT-REAL",
                             base_url="http://mock"), budget)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c, budget


def groq_reply(content='{"assessment":"ok"}', usage=None, finish="stop", model=MODEL, rid="req_TEST01"):
    """A Groq chat completion as documented (console.groq.com/docs/api-reference)."""
    usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20,
             "prompt_time": 0.01, "completion_time": 0.02, "queue_time": 0.01, "total_time": 0.04} \
        if usage is None else usage
    body = {"id": "chatcmpl-TEST", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish}], "system_fingerprint": "fp_test", "service_tier": "on_demand"}
    if rid:
        body["x_groq"] = {"id": rid}
    return body if usage == "omit" else {**body, "usage": usage}


LIMIT_HEADERS = {"x-ratelimit-limit-tokens": "250000", "x-ratelimit-remaining-tokens": "249000",
                 "x-ratelimit-reset-tokens": "0.24s", "x-ratelimit-limit-requests": "1000",
                 "x-ratelimit-remaining-requests": "999", "x-ratelimit-reset-requests": "1m26.4s"}


def ok_handler(req):
    return httpx.Response(200, json=groq_reply(), headers=LIMIT_HEADERS)


def ledger(tmp_path):
    return [json.loads(s) for s in (tmp_path / "reservations.jsonl").read_text().splitlines()]


def test_exact_groq_request_body_and_endpoint(tmp_path):
    seen = []
    def handler(req):
        seen.append(req)
        return ok_handler(req)
    c, _ = client(tmp_path, handler)
    assert c.complete_json("SYSTEM-TEXT", "USER-TEXT").ok
    req = seen[0]
    assert str(req.url) == "http://mock/chat/completions" and req.method == "POST"
    assert req.headers["authorization"] == "Bearer TEST-KEY-NOT-REAL"
    assert json.loads(req.content) == {
        "model": "openai/gpt-oss-120b",
        "messages": [{"role": "system", "content": "SYSTEM-TEXT"}, {"role": "user", "content": "USER-TEXT"}],
        "reasoning_effort": "high", "response_format": {"type": "json_object"}, "max_completion_tokens": 16000}
    # Without a test base_url the client uses Groq's documented endpoint only.
    assert LLMConfig(provider="groq", model=MODEL).url == GROQ_CHAT_URL == \
        "https://api.groq.com/openai/v1/chat/completions"


def test_live_profile_is_frozen_benchmark_config_a_word_for_word():
    import yaml
    a = yaml.safe_load((ROOT / "eval/bakeoff_cases.yaml").read_text())["configs"]["A"]
    assert a["model"] == MODEL and a["upstream_slug"] == GROQ["provider"]
    assert {k: v for k, v in a["request"].items() if k != "provider"} == GROQ["request"]
    assert {k: a["price_usd_per_mtok"][k] for k in ("input", "output")} == PRICE


@pytest.mark.parametrize("cfg", [dict(provider="openai", model=MODEL), dict(provider="groq", model="openai/gpt-oss-20b"),
                                 dict(provider="openrouter", model="openai/gpt-oss-20b")])
def test_only_reviewed_profiles_can_be_used(tmp_path, cfg):
    budget = DemoBudget(tmp_path / "r.jsonl", cap_usd=1, input_per_million=1, output_per_million=1)
    with pytest.raises(ValueError):
        DemoClient(LLMConfig(**cfg), budget)


def test_reservation_and_settlement_are_exact(tmp_path):
    c, budget = client(tmp_path, ok_handler)
    assert c.complete_json("s", "u").ok
    rows = ledger(tmp_path)
    reserved = next(r for r in rows if r.get("status") == "reserved-before-send")
    settled = next(r for r in rows if r.get("status") == "settled")
    assert reserved["reserved_usd"] == pytest.approx(((2 + 512) * 0.15 + 16000 * 0.60) / 1e6)
    assert settled["reported_usd"] == pytest.approx((10 * 0.15 + 10 * 0.60) / 1e6)
    assert settled["request_id"] == "req_TEST01"
    assert settled["rate_limits"]["x-ratelimit-remaining-tokens"] == "249000"
    s = budget.summary()
    assert s["requests_sent"] == 1 and s["requests_without_reported_usage"] == 0 and not s["halted"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_no_automatic_provider_retry_and_no_error_secret_leak(tmp_path, status):
    sent = []
    def handler(req):
        sent.append(req)
        return httpx.Response(status, text="SECRET-SENTINEL")
    c, budget = client(tmp_path, handler)
    r = c.complete_json("s", "u")
    assert not r.ok and len(sent) == 1 and len(budget.calls) == 1
    assert "SECRET-SENTINEL" not in r.error
    assert f"HTTP {status}" in r.error   # status (not body) is kept for diagnosis


def test_request_cap_is_shared_and_reservation_precedes_transport(tmp_path):
    def handler(req):
        assert "reserved-before-send" in (tmp_path / "reservations.jsonl").read_text()
        return ok_handler(req)
    c, budget = client(tmp_path, handler, max_requests=1)
    other, _ = client(tmp_path, handler, budget=budget)     # a second role, same budget
    assert c.complete_json("s", "u").ok
    r = other.complete_json("s", "u")
    assert not r.ok and "request or spending limit" in r.error
    assert len(budget.calls) == 1


def test_spend_cap_blocks_before_send(tmp_path):
    def handler(req):
        pytest.fail("must not send")
    c, budget = client(tmp_path, handler)
    budget.cap = 0.000001
    assert not c.complete_json("s", "u").ok
    assert not budget.calls


def _bad(kind):
    """Malformed or failed Groq replies. Each must fail its turn and stop the run."""
    secret = "SECRET-SENTINEL"
    if kind == "json_validate_failed":   # Groq JSON mode failure (observed shape, HTTP 400)
        return httpx.Response(400, json={"error": {"message": f"Failed to validate JSON {secret}",
                                                   "type": "invalid_request_error", "code": "json_validate_failed",
                                                   "failed_generation": secret}})
    if kind == "rate_limited":
        return httpx.Response(429, json={"error": {"message": secret, "type": "tokens",
                                                   "code": "rate_limit_exceeded"}},
                              headers={**LIMIT_HEADERS, "retry-after": "7"})
    if kind == "spend_limit":            # Groq spend limit reached (docs: HTTP 400 blocked_api_access)
        return httpx.Response(400, json={"error": {"message": secret, "code": "blocked_api_access"}})
    if kind == "transport":
        raise httpx.ConnectTimeout(secret)
    if kind == "not_json_body":
        return httpx.Response(200, text=f"<html>{secret}</html>")
    if kind == "list_body":
        return httpx.Response(200, json=[secret])
    body = groq_reply()
    if kind == "choice_error":           # 200 carrying an error (observed through OpenRouter)
        body["choices"][0].update(finish_reason="error", error={"code": 502, "message": secret})
    elif kind == "top_level_error":
        body["error"] = {"message": secret}
    elif kind == "truncated":
        body["choices"][0]["finish_reason"] = "length"
    elif kind == "unknown_finish":
        body["choices"][0]["finish_reason"] = "tool_calls"
    elif kind == "missing_finish":
        del body["choices"][0]["finish_reason"]
    elif kind == "not_json":
        body["choices"][0]["message"]["content"] = "I think the answer is to reroute."   # model text, kept as evidence
    elif kind == "json_array":
        body["choices"][0]["message"]["content"] = "[1, 2]"
    elif kind == "content_not_text":
        body["choices"][0]["message"]["content"] = [{"type": "text", "text": "{}"}]
    elif kind == "empty_content":
        body["choices"][0]["message"]["content"] = None
    elif kind == "two_choices":
        body["choices"].append(body["choices"][0])
    elif kind == "no_choices":
        body["choices"] = []
    elif kind == "model_substituted":
        body["model"] = "openai/gpt-oss-20b"
    return httpx.Response(200, json=body)


BAD = ["json_validate_failed", "rate_limited", "spend_limit", "transport", "not_json_body", "list_body",
       "choice_error", "top_level_error", "truncated", "unknown_finish", "missing_finish", "not_json",
       "json_array", "content_not_text", "empty_content", "two_choices", "no_choices", "model_substituted"]


@pytest.mark.parametrize("kind", BAD)
def test_malformed_or_failed_reply_fails_the_turn_and_stops_every_later_request(tmp_path, kind):
    sent = []
    def handler(req):
        sent.append(req)
        if len(sent) > 1:
            pytest.fail("no request may be sent after a failed turn")
        return _bad(kind)
    c, budget = client(tmp_path, handler)
    other, _ = client(tmp_path, handler, budget=budget)
    r = c.complete_json("s", "u")
    assert not r.ok and "SECRET-SENTINEL" not in (r.error or "") + r.text
    later = other.complete_json("s", "u")
    assert not later.ok and "Halted" in later.error
    assert len(sent) == 1 and len(budget.calls) == 1
    rows = ledger(tmp_path)
    assert "SECRET-SENTINEL" not in (tmp_path / "reservations.jsonl").read_text()
    assert budget.halted and [x.get("status") for x in rows].count("halted") == 1
    if kind in ("json_validate_failed", "rate_limited", "spend_limit"):
        code = {"json_validate_failed": "json_validate_failed", "rate_limited": "rate_limit_exceeded",
                "spend_limit": "blocked_api_access"}[kind]
        assert code in r.error
        err = next(x for x in rows if x.get("status") == "http-error-reservation-retained")
        assert err["error_code"].split()[0] == code     # the code first; then type/metadata tokens
        if kind == "rate_limited":
            assert err["rate_limits"]["retry-after"] == "7"
        assert budget.summary()["requests_without_reported_usage"] == 1


@pytest.mark.parametrize("usage", ["omit", None, {"prompt_tokens": 10}, {"prompt_tokens": "10", "completion_tokens": 1},
                                   {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 99},
                                   {"prompt_tokens": 10, "completion_tokens": 10 ** 7}])
def test_missing_inconsistent_or_excessive_usage_stops_later_requests(tmp_path, usage):
    sent = []
    def handler(req):
        sent.append(req)
        return httpx.Response(200, json=groq_reply(usage=usage) if usage is not None
                              else {**groq_reply(), "usage": None})
    c, budget = client(tmp_path, handler)
    r = c.complete_json("s", "u")
    # The response that could not be reconciled fails itself (not only later ones),
    # carries no data, and keeps the model text as evidence.
    assert not r.ok and r.data is None and r.text == '{"assessment":"ok"}' and "RECONCILIATION" in r.error
    assert budget.halted and "RECONCILIATION" in budget.halted
    assert not c.complete_json("s", "u").ok and len(sent) == 1
    if isinstance(usage, dict) and usage.get("completion_tokens") == 10 ** 7:
        assert budget.reserved == pytest.approx(budget.reported)   # overage is added, never hidden
    else:
        assert budget.summary()["requests_without_reported_usage"] == 1


def test_optional_pacing_is_shared_and_never_retries(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr("exercise_demo.demo_provider.time.sleep", waits.append)
    c, budget = client(tmp_path, ok_handler, min_interval_s=30)
    other, _ = client(tmp_path, ok_handler, budget=budget)
    assert c.complete_json("s", "u").ok and other.complete_json("s", "u").ok
    assert len(waits) == 1 and 29 < waits[0] <= 30 and len(budget.calls) == 2


@pytest.mark.parametrize("bad", [float("nan"), -1, 0, "1", True])
def test_invalid_budget_values_are_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        DemoBudget(tmp_path / "r.jsonl", cap_usd=bad, input_per_million=1, output_per_million=1)
    with pytest.raises(ValueError):
        DemoBudget(tmp_path / "r.jsonl", cap_usd=1, input_per_million=1, output_per_million=1,
                   min_interval_s=-1 if bad == 0 else 121)
    assert not (tmp_path / "r.jsonl").exists()


def test_structural_turn_ceiling_fits_the_shared_request_cap(base_scenario, exercise):
    ceiling = max_model_turns(base_scenario, 2)
    assert ceiling <= MAX_REQUESTS
    result = exercise.run()
    assert result.metrics["model_calls"] <= ceiling


# --- Full four-role exercise through the real Groq adapter, HTTP mocked ---------

def scripted_groq(sent, rewrite=None, rid=True, bad_usage=None):
    """Mock Groq: answers each request with the scripted double's JSON for that
    prompt. NOT AI. `rewrite(n, data)` may damage the n-th reply's content and
    `bad_usage(n, data, usage)` its reported usage."""
    def handler(req):
        body = json.loads(req.content)
        sent.append(body)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        data = ScriptedTestDouble().complete_json(system, user).data
        if rewrite:
            data = rewrite(len(sent), data)
        text = json.dumps(data)
        usage = {"prompt_tokens": len((system + user).encode()) // 4, "completion_tokens": len(text) // 4 + 300}
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        if bad_usage:
            usage = bad_usage(len(sent), data, usage)
        return httpx.Response(200, json=groq_reply(text, usage=usage, rid=f"req_{len(sent):03d}" if rid else None),
                              headers=LIMIT_HEADERS)
    return handler


def interactive_answers(monkeypatch):
    """A person at the terminal: approves operational sign-offs, gives no authority basis."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "y" if "approve?" in prompt else "")


def mock_live(base_scenario, tmp_path, sent, human, rewrite=None, rid=True, bad_usage=None):
    budget = DemoBudget(tmp_path / "ledger" / "reservations.jsonl", cap_usd=1,
                        input_per_million=PRICE["input"], output_per_million=PRICE["output"])
    clients = {}
    for r in ROLES:
        c = DemoClient(LLMConfig(provider="groq", model=MODEL, api_key="TEST-KEY-NOT-REAL",
                                 base_url="http://mock"), budget)
        c._http = httpx.Client(transport=httpx.MockTransport(scripted_groq(sent, rewrite, rid, bad_usage)))
        clients[r] = c
    ex = FullExercise(apply_variation(base_scenario, None), clients,
                      Retriever.load(ROOT / "kb/build/chunks.jsonl"), human, out_root=tmp_path / "runs")
    return ex, ex.run(), budget


def test_mock_live_run_passes_live_and_interactive_checks(base_scenario, tmp_path, monkeypatch):
    interactive_answers(monkeypatch)
    sent = []
    ex, result, budget = mock_live(base_scenario, tmp_path, sent, HumanPolicy("interactive"))
    report = inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True, require_interactive_human=True)
    assert report["passed"], report["problems"]
    assert report["mode"] == "live" and report["served_by"] == ["groq:openai/gpt-oss-120b"]
    assert report["human"] == "human:interactive" and report["human_decisions"] >= 2
    assert all(n >= 1 for roles in report["coverage"].values() for n in roles.values())
    # Every request had exactly the reviewed body; one request per turn; all settled.
    keys = {"model", "messages", "reasoning_effort", "response_format", "max_completion_tokens"}
    assert all(set(b) == keys and b["max_completion_tokens"] == 16000 and b["reasoning_effort"] == "high"
               for b in sent)
    s = budget.summary()
    assert len(sent) == s["requests_sent"] == result.metrics["model_calls"] <= MAX_REQUESTS
    assert s["requests_without_reported_usage"] == 0 and s["halted"] is None
    assert 0 < s["reported_usd"] < s["reserved_usd"] <= 1


@pytest.mark.parametrize("damage", ["malformed_action", "malformed_message", "empty_assessment",
                                    "assessment_not_text", "option_without_text"])
def test_unusable_parsed_turn_stops_every_later_live_request(base_scenario, tmp_path, monkeypatch, damage):
    interactive_answers(monkeypatch)
    def rewrite(n, data):
        if n == 3:      # valid JSON from the provider, unusable for the exercise
            if damage == "malformed_action":
                data["actions"] = [{"args": {}, "why": "no tool named"}]
            elif damage == "malformed_message":
                data["messages"] = [{"to": "ALL"}]
            elif damage == "empty_assessment":
                data["assessment"] = "   "
            elif damage == "assessment_not_text":
                data["assessment"] = 42
            else:
                data["options"] = [{"decision": "keep"}]
        return data
    sent = []
    ex, result, budget = mock_live(base_scenario, tmp_path, sent, HumanPolicy("interactive"), rewrite)
    assert len(sent) == 3 and budget.halted.startswith("Unusable turn 003_")
    turns = [r["payload"] for r in ex.audit.records if r["kind"] == "DEMO_TURN"]
    assert [t["usable"] for t in turns[:3]] == [True, True, False] and not any(t["usable"] for t in turns[3:])
    assert not inspect_demonstration(result.out_dir, ex.audit.prev)["passed"]


EFFECTS = ("MESSAGE", "GATE_DECISION", "HUMAN_DECISION", "STATE_CHANGE", "ACTION_RESULT",
           "GAP_OBSERVATION", "DUPLICATE_ACTION", "STALE_APPROVAL")


def is_target(target, data):
    """first: the operator's opening turn (a message plus an action);
    switch: the service turn with the state-changing switch_ai_endpoint."""
    if target == "first":
        return any(a.get("tool") == "reroute_traffic" for a in data.get("actions", []))
    return any(a.get("tool") == "switch_ai_endpoint" for a in data.get("actions", []))


def effects_after_turn(records, turn_file):
    """Records the exercise wrote between this turn and the next model turn."""
    i = next(k for k, r in enumerate(records) if r["kind"] == "DEMO_TURN" and r["payload"]["turn_file"] == turn_file)
    out = []
    for r in records[i + 1:]:
        if r["kind"] in ("AGENT_TURN", "RUN_END"):
            break
        out.append(r["kind"])
    return [k for k in out if k in EFFECTS]


def test_control_target_turns_do_have_effects(base_scenario, tmp_path, monkeypatch):
    """Control for the two regressions below: undamaged, the targeted replies
    send a message, gate an action and change the synthetic state."""
    interactive_answers(monkeypatch)
    ex, result, _ = mock_live(base_scenario, tmp_path, [], HumanPolicy("interactive"))
    recs = ex.audit.records
    assert "MESSAGE" in effects_after_turn(recs, "001_operator.json")
    assert "GATE_DECISION" in effects_after_turn(recs, "001_operator.json")
    switch = [r for r in recs if r["kind"] == "STATE_CHANGE" and r["payload"]["tool"] == "switch_ai_endpoint"]
    assert switch and ex.state.snapshot()["service"]["endpoint_region"] == "uae_central"


@pytest.mark.parametrize("live", [True, False], ids=["live-adapter", "offline-double"])
@pytest.mark.parametrize("target", ["first", "switch"])
def test_unusable_turn_is_discarded_whole_even_with_a_valid_action(base_scenario, tmp_path, monkeypatch,
                                                                    live, target):
    """A reply with a valid (state-changing) action AND a malformed item: nothing
    from it executes, is routed or reaches the gate."""
    interactive_answers(monkeypatch)
    hit = []
    def rewrite(n, data):
        if not hit and is_target(target, data):
            hit.append(n)
            data["actions"].append({"args": {"region": "uae_central"}, "why": "malformed: no tool"})
        return data
    sent = []
    if live:
        ex, result, budget = mock_live(base_scenario, tmp_path, sent, HumanPolicy("interactive"), rewrite)
    else:
        class Damaged(ScriptedTestDouble):
            def complete_json(self, system, user):
                r = super().complete_json(system, user)
                r.data = rewrite(0, r.data)
                return r
        ex = FullExercise(apply_variation(base_scenario, None), {r: Damaged() for r in ROLES},
                          Retriever.load(ROOT / "kb/build/chunks.jsonl"), HumanPolicy("interactive"), tmp_path)
        result = ex.run()
    recs = ex.audit.records
    i = next(k for k, r in enumerate(recs) if r["kind"] == "DEMO_TURN" and not r["payload"]["usable"])
    damaged = recs[i]["payload"]
    assert damaged["parsed"] and hit
    parsed = next(r["payload"] for r in reversed(recs[:i]) if r["kind"] == "TURN_PARSED")
    assert parsed["malformed"]                 # the parser saw the malformed item
    assert effects_after_turn(recs, damaged["turn_file"]) == []
    if live:
        # Live: the run also stops; nothing from that reply or later ever executes.
        assert len(sent) == hit[0] and budget.halted.startswith("Unusable turn")
        if target == "switch":
            assert not [r for r in recs if r["kind"] == "STATE_CHANGE" and r["payload"]["tool"] == "switch_ai_endpoint"]
            assert ex.state.snapshot()["service"]["endpoint_region"] != "uae_central"
    assert not inspect_demonstration(result.out_dir, ex.audit.prev)["passed"]


@pytest.mark.parametrize("target", ["first", "switch"])
@pytest.mark.parametrize("kind", ["missing", "total_mismatch", "overage"])
def test_unreconciled_usage_fails_that_reply_and_nothing_from_it_executes(base_scenario, tmp_path, monkeypatch,
                                                                          target, kind):
    interactive_answers(monkeypatch)
    hit = []
    def bad_usage(n, data, usage):
        if hit or not is_target(target, data):
            return usage
        hit.append(n)
        if kind == "missing":
            return "omit"
        if kind == "total_mismatch":
            return {**usage, "total_tokens": usage["total_tokens"] + 1}
        return {**usage, "completion_tokens": 10 ** 7, "total_tokens": usage["prompt_tokens"] + 10 ** 7}
    sent = []
    ex, result, budget = mock_live(base_scenario, tmp_path, sent, HumanPolicy("interactive"), bad_usage=bad_usage)
    recs = ex.audit.records
    assert hit and len(sent) == hit[0] and "RECONCILIATION" in budget.halted
    turn = next(r for r in recs if r["kind"] == "AGENT_TURN" and r["payload"]["turn_file"].startswith(f"{hit[0]:03d}_"))
    assert turn["payload"]["ok"] is False and "RECONCILIATION" in turn["payload"]["error"]
    name = turn["payload"]["turn_file"]
    saved = json.loads((result.out_dir / "turns" / name).read_text())
    assert saved["response_json"] is None and json.loads(saved["response_text"])   # evidence kept, not used
    assert not any(r["kind"] == "TURN_PARSED" and r["seq"] > turn["seq"] for r in recs)
    assert effects_after_turn(recs, name) == []
    if target == "switch":
        assert ex.state.snapshot()["service"]["endpoint_region"] != "uae_central"
    assert not inspect_demonstration(result.out_dir, ex.audit.prev)["passed"]


def test_settle_reports_whether_the_reply_may_be_used(tmp_path):
    budget = DemoBudget(tmp_path / "r.jsonl", cap_usd=1, input_per_million=0.15, output_per_million=0.6)
    row = budget.reserve("s", "u", 16000)
    assert budget.settle(row, {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}) is True
    row = budget.reserve("s", "u", 16000)
    assert budget.settle(row, {"prompt_tokens": 5, "completion_tokens": 10 ** 7}) is False
    budget2 = DemoBudget(tmp_path / "r2.jsonl", cap_usd=1, input_per_million=0.15, output_per_million=0.6)
    assert budget2.settle(budget2.reserve("s", "u", 16000), None) is False


def test_require_live_rejects_scripted_offline_evidence(exercise):
    result = exercise.run()
    plain = inspect_demonstration(result.out_dir, exercise.audit.prev)
    assert plain["passed"] and plain["mode"] == "offline-NOT-AI"
    report = inspect_demonstration(result.out_dir, exercise.audit.prev, require_live=True)
    assert not report["passed"] and any("scripted" in p for p in report["problems"])


def test_require_interactive_rejects_simulated_human(exercise):
    result = exercise.run()
    report = inspect_demonstration(result.out_dir, exercise.audit.prev, require_interactive_human=True)
    assert not report["passed"] and any("human:interactive" in p for p in report["problems"])


def test_require_live_rejects_scripted_double_labelled_as_ai(base_scenario, tmp_path):
    class Labelled(ScriptedTestDouble):
        is_ai = True
        def complete_json(self, system, user):
            r = super().complete_json(system, user)
            r.is_ai = True
            return r
    ex = FullExercise(apply_variation(base_scenario, None), {r: Labelled() for r in ROLES},
                      Retriever.load(ROOT / "kb/build/chunks.jsonl"), HumanPolicy("conservative"), tmp_path)
    result = ex.run()
    report = inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True)
    assert report["mode"] == "live" and not report["passed"]
    assert any("reviewed live provider/model" in p for p in report["problems"])


def test_require_live_rejects_turns_without_provider_request_ids(base_scenario, tmp_path, monkeypatch):
    interactive_answers(monkeypatch)
    ex, result, _ = mock_live(base_scenario, tmp_path, [], HumanPolicy("interactive"), rid=False)
    report = inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True)
    assert report["passed"]          # without a request id, the completion id still identifies each turn
    # Remove the completion id too (rechained), so no provider identifier is left.
    from linkdown.audit import GENESIS, _h
    path = result.out_dir / "audit.jsonl"
    prev, rows = GENESIS, []
    for r in [json.loads(s) for s in path.read_text().splitlines()]:
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        if body["kind"] == "AGENT_TURN":
            body["response_id"] = None
        rows.append({**body, "prev": prev, "hash": _h(prev, body)})
        prev = rows[-1]["hash"]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rp = result.out_dir / "report.json"
    rep = json.loads(rp.read_text()); rep["audit_head"] = prev
    rp.write_text(json.dumps(rep))
    report = inspect_demonstration(result.out_dir, prev, require_live=True)
    assert not report["passed"] and any("request id" in p for p in report["problems"])


def test_require_interactive_rejects_live_run_with_simulated_human(base_scenario, tmp_path):
    ex, result, _ = mock_live(base_scenario, tmp_path, [], HumanPolicy("conservative"))
    assert inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True)["passed"]
    report = inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True, require_interactive_human=True)
    assert not report["passed"] and any("human:interactive" in p for p in report["problems"])


def test_require_interactive_rejects_relabelled_controller_even_if_rechained(exercise):
    from linkdown.audit import GENESIS, _h
    result = exercise.run()
    path = result.out_dir / "audit.jsonl"
    prev, rows = GENESIS, []
    for r in [json.loads(s) for s in path.read_text().splitlines()]:
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        if body["kind"] == "RUN_START":
            body["payload"]["human"] = "human:interactive"
        rows.append({**body, "prev": prev, "hash": _h(prev, body)})
        prev = rows[-1]["hash"]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rp = result.out_dir / "report.json"
    rep = json.loads(rp.read_text()); rep["audit_head"] = prev
    rp.write_text(json.dumps(rep))
    report = inspect_demonstration(result.out_dir, prev, require_interactive_human=True)
    assert not report["passed"]
    assert "A human decision was not made by the interactive controller" in report["problems"]


def demonstrate(*args, env=None):
    import os
    import subprocess
    import sys
    e = {k: v for k, v in os.environ.items() if k != "LINKDOWN_LLM_API_KEY"}
    e.update(env or {})
    return subprocess.run([sys.executable, str(ROOT / "scripts/demonstrate.py"), *map(str, args)],
                          capture_output=True, text=True, env=e)


def test_cli_verify_flags_reject_scripted_evidence(exercise):
    result = exercise.run()
    head = exercise.audit.prev
    assert demonstrate("--verify", result.out_dir, "--expected-head", head).returncode == 0
    for flag in ("--require-live", "--require-interactive-human"):
        p = demonstrate("--verify", result.out_dir, "--expected-head", head, flag)
        assert p.returncode == 1 and json.loads(p.stdout)["passed"] is False
    p = demonstrate("--require-live")
    assert p.returncode == 2 and "apply to --verify" in p.stderr


def test_live_requires_explicit_plan_and_authorization(tmp_path):
    p = demonstrate("--authorize-live-spend")
    assert p.returncode == 2 and "reviewed --live-plan" in p.stderr
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    p = demonstrate("--live-plan", plan, "--out", tmp_path / "out")
    assert p.returncode == 2 and "reviewed --live-plan" in p.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("change, message", [
    ({"provider": "openai"}, "Reviewed demo supports only: groq openai/gpt-oss-120b"),
    ({"provider": "openrouter", "model": "openai/gpt-oss-20b"}, "no routing substitution"),
    ({"model": "openai/gpt-oss-20b"}, "Reviewed demo supports only"),
    ({"approval_reference": ""}, "separate approval reference"),
    ({"input_per_million": 0.10}, "below the documented prices"),
    ({"output_per_million": 0.50}, "below the documented prices"),
    ({"cap_usd": 0.42}, "cap_usd must be at least USD 0.4294"),
    ({"cap_usd": "60"}, "must be numbers"),
    ({}, "LINKDOWN_LLM_API_KEY"),
])
def test_live_plan_is_refused_before_any_file_or_request(tmp_path, change, message):
    plan = {"provider": "groq", "model": MODEL, "approval_reference": "TEST-FIXTURE",
            "cap_usd": 1, "input_per_million": 0.15, "output_per_million": 0.60, **change}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    p = demonstrate("--live-plan", path, "--authorize-live-spend", "--out", tmp_path / "out")
    assert p.returncode == 2 and message in p.stderr, p.stderr
    assert not (tmp_path / "out").exists()


# --- OpenRouter pinned to Groq (frozen configuration A), HTTP mocked ------------

OR = "openrouter:" + MODEL
OR_CHAT = "https://openrouter.ai/api/v1/chat/completions"


def or_reply(n, content='{"assessment":"ok"}', usage=None, model=MODEL, finish="stop"):
    """An OpenRouter chat completion (docs: api-reference overview; usage always
    included, cost in credits)."""
    usage = {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300,
             "cost": (100 * 0.15 + 200 * 0.60) / 1e6,
             "completion_tokens_details": {"reasoning_tokens": 150}} if usage is None else usage
    body = {"id": f"gen-TEST-{n:03d}", "object": "chat.completion", "created": 1, "model": model,
            "provider": "Groq",      # undocumented reply-body field: recorded nowhere as proof
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish, "native_finish_reason": finish}]}
    return body if usage == "omit" else {**body, "usage": usage}


def or_record(gen_id, cost=(100 * 0.15 + 200 * 0.60) / 1e6, host="Groq", attempts=None):
    """OpenRouter generation record (docs: GET /api/v1/generation)."""
    attempts = [{"provider_name": host, "status": 200, "routed_service_tier": "flex"}] if attempts is None else attempts
    return {"data": {"id": gen_id, "model": MODEL, "provider_name": host, "total_cost": cost,
                     "native_tokens_prompt": 100, "native_tokens_completion": 200, "native_tokens_reasoning": 150,
                     "finish_reason": "stop", "provider_responses": attempts}}


def or_mock(posts, gets, reply=None, record=None):
    """POST chat -> reply(n) ; GET generation -> record(gen_id). Anything else fails."""
    def handler(req):
        if req.method == "POST":
            assert str(req.url) == OR_CHAT
            posts.append(json.loads(req.content))
            n = len(posts)
            return httpx.Response(200, json=reply(n, posts[-1]) if reply else or_reply(n))
        assert req.method == "GET" and req.url.path == "/api/v1/generation"
        gets.append(str(req.url))
        gen_id = req.url.params["id"]
        out = record(gen_id) if record else or_record(gen_id)
        return out if isinstance(out, httpx.Response) else httpx.Response(200, json=out)
    return handler


def or_client(tmp_path, handler, budget=None):
    budget = budget or DemoBudget(tmp_path / "reservations.jsonl", cap_usd=1, input_per_million=0.15,
                                  output_per_million=0.60)
    c = DemoClient(LLMConfig(provider="openrouter", model=MODEL, api_key="TEST-OR-KEY-NOT-REAL"),
                   budget, sleep=lambda s: None)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c, budget


def test_openrouter_profile_is_frozen_config_a_exactly_with_its_groq_pin():
    import yaml
    a = yaml.safe_load((ROOT / "eval/bakeoff_cases.yaml").read_text())["configs"]["A"]
    p = PROFILES[OR]
    assert (a["provider"], a["model"], a["upstream"]) == (p["provider"], p["model"], p["upstream"])
    assert a["request"] == p["request"]          # word for word, route pin included
    assert p["request"]["provider"] == {"order": ["groq"], "only": ["groq"], "allow_fallbacks": False,
                                        "require_parameters": True}
    assert not {"models", "route", "temperature", "top_p", "max_tokens"} & set(p["request"])
    assert {k: a["price_usd_per_mtok"][k] for k in ("input", "output")} == p["min_price_usd_per_mtok"]
    assert PROFILES["groq:" + MODEL]["request"] == {k: v for k, v in a["request"].items() if k != "provider"}


def test_exact_openrouter_request_body_endpoint_and_host_lookup(tmp_path):
    posts, gets = [], []
    c, budget = or_client(tmp_path, or_mock(posts, gets))
    r = c.complete_json("SYSTEM-TEXT", "USER-TEXT")
    assert r.ok, r.error
    assert LLMConfig(provider="openrouter", model=MODEL).url == OR_CHAT
    assert posts == [{"model": MODEL, "messages": [{"role": "system", "content": "SYSTEM-TEXT"},
                                                   {"role": "user", "content": "USER-TEXT"}],
                      "reasoning_effort": "high", "response_format": {"type": "json_object"},
                      "max_completion_tokens": 16000,
                      "provider": {"order": ["groq"], "only": ["groq"], "allow_fallbacks": False,
                                   "require_parameters": True}}]
    assert gets == ["https://openrouter.ai/api/v1/generation?id=gen-TEST-001"]
    assert r.response_id == "gen-TEST-001" and c.last_serving["state"] == "verified"
    assert c.last_serving["provider_name"] == "Groq" and c.last_serving["native_tokens_reasoning"] == 150
    rows = ledger(tmp_path)
    charged = next(x for x in rows if x.get("status") == "charged")
    assert charged["charged_usd"] == pytest.approx(charged["plan_price_usd"]) and not budget.halted
    s = budget.summary()
    assert s["requests_without_reported_usage"] == 0 and s["requests_without_verified_charge"] == 0


def _host_case(kind):
    """(reply override, record override) for one host-provenance or cost failure."""
    other = [{"provider_name": "DeepInfra", "status": 502}, {"provider_name": "Groq", "status": 200}]
    return {
        "other_host": (None, lambda g: or_record(g, host="DeepInfra",
                                                  attempts=[{"provider_name": "DeepInfra", "status": 200}])),
        "fallback_attempt": (None, lambda g: or_record(g, attempts=other)),
        "two_served": (None, lambda g: or_record(g, attempts=[{"provider_name": "Groq", "status": 200}] * 2)),
        "no_attempts": (None, lambda g: or_record(g, attempts=[])),
        "attempts_missing": (None, lambda g: {"data": {k: v for k, v in or_record(g)["data"].items()
                                                       if k != "provider_responses"}}),
        "record_never_found": (None, lambda g: httpx.Response(404, json={"error": {"code": 404}})),
        "record_forbidden": (None, lambda g: httpx.Response(403, json={"error": {"code": 403}})),
        "no_generation_id": (lambda n, b: {**or_reply(n), "id": None}, None),
        "bad_generation_id": (lambda n, b: {**or_reply(n), "id": "chatcmpl-123"}, None),
        "cost_missing": (None, lambda g: or_record(g, cost=None)),
        "cost_over_reservation": (None, lambda g: or_record(g, cost=5.0)),
        "cost_above_prices": (None, lambda g: or_record(g, cost=2 * (100 * 0.15 + 200 * 0.60) / 1e6)),
        "usage_cost_above_prices": (lambda n, b: or_reply(n, usage={"prompt_tokens": 100, "completion_tokens": 200,
                                                                    "total_tokens": 300, "cost": 0.01}), None),
    }[kind]


HOST_CASES = ["other_host", "fallback_attempt", "two_served", "no_attempts", "attempts_missing",
              "record_never_found", "record_forbidden", "no_generation_id", "bad_generation_id",
              "cost_missing", "cost_over_reservation", "cost_above_prices", "usage_cost_above_prices"]


@pytest.mark.parametrize("kind", HOST_CASES)
def test_unproved_host_or_unreconciled_charge_fails_the_reply_and_stops_the_run(tmp_path, kind):
    reply, record = _host_case(kind)
    posts, gets = [], []
    c, budget = or_client(tmp_path, or_mock(posts, gets, reply, record))
    other, _ = or_client(tmp_path, or_mock(posts, gets, reply, record), budget=budget)
    r = c.complete_json("s", "u")
    assert not r.ok and r.data is None and r.text == '{"assessment":"ok"}'   # evidence kept, never used
    assert budget.halted and "RECONCILIATION" in budget.halted
    later = other.complete_json("s", "u")
    assert not later.ok and "Halted" in later.error and len(posts) == 1
    statuses = [x.get("status") for x in ledger(tmp_path)]
    if kind in ("cost_missing", "cost_over_reservation", "cost_above_prices", "usage_cost_above_prices"):
        assert c.last_serving["state"] == "verified"
        assert ("charged" if kind != "cost_missing" else "charge-unverified-reservation-retained") in statuses
    else:
        assert c.last_serving["state"] in ("mismatch", "unverified")
        assert "host-not-verified-reservation-retained" in statuses
        assert budget.summary()["requests_without_verified_charge"] == 1
    if kind in ("no_generation_id", "bad_generation_id"):
        assert gets == []                               # nothing to look up: never "verified"
    if kind == "cost_over_reservation":
        assert budget.reserved >= 5.0                   # the overage is counted, never hidden


@pytest.mark.parametrize("status, body, expect", [
    (402, {"error": {"code": 402, "message": "SECRET-SENTINEL", "metadata": {"limit_source": "openrouter_key_limit"}}},
     "402 openrouter_key_limit"),
    (402, {"error": {"code": 402, "message": "SECRET-SENTINEL", "metadata": {"limit_source": "openrouter_credits"}}},
     "402 openrouter_credits"),
    (403, {"error": {"code": 403, "message": "SECRET-SENTINEL", "metadata": {"limit_source": "openrouter_key_limit"}}},
     "403 openrouter_key_limit"),
    (404, {"error": {"code": 404, "message": "SECRET-SENTINEL"}}, "HTTP 404"),
    (503, {"error": {"code": 503, "message": "SECRET-SENTINEL"}}, "503"),
    (429, {"error": {"code": 429, "message": "SECRET-SENTINEL", "metadata": {"provider_name": "Groq",
                                                                           "raw": "SECRET-SENTINEL"}}}, "429 groq"),
    (502, {"error": {"code": 502, "message": "SECRET-SENTINEL"}}, "HTTP 502"),
])
def test_openrouter_http_errors_fail_closed_without_leaking_bodies(tmp_path, status, body, expect):
    posts, gets = [], []
    def handler(req):
        posts.append(req)
        return httpx.Response(status, json=body)
    c, budget = or_client(tmp_path, handler)
    r = c.complete_json("s", "u")
    assert not r.ok and expect in r.error and "SECRET-SENTINEL" not in r.error
    assert "SECRET-SENTINEL" not in (tmp_path / "reservations.jsonl").read_text()
    assert budget.halted and not c.complete_json("s", "u").ok and len(posts) == 1


@pytest.mark.parametrize("shape", ["error_no_choices", "choice_json_failure", "model_substituted", "truncated"])
def test_openrouter_200_failures_fail_closed(tmp_path, shape):
    def reply(n, body):
        r = or_reply(n)
        if shape == "error_no_choices":          # docs: a non-streaming 200 can carry an error and no choices
            r.pop("choices")
            r["error"] = {"code": 502, "message": "SECRET-SENTINEL"}
        elif shape == "choice_json_failure":     # observed 26 Oct: Groq JSON-validation failure through OpenRouter
            r["choices"][0].update(finish_reason="error",
                                   error={"code": 502, "message": "Upstream error from Groq: Failed to validate JSON"})
        elif shape == "model_substituted":       # docs: the model field shows the model actually used
            r["model"] = "openai/gpt-oss-20b"
        else:
            r["choices"][0]["finish_reason"] = "length"
        return r
    posts, gets = [], []
    c, budget = or_client(tmp_path, or_mock(posts, gets, reply))
    r = c.complete_json("s", "u")
    assert not r.ok and budget.halted and "SECRET-SENTINEL" not in (r.error or "")
    assert not c.complete_json("s", "u").ok and len(posts) == 1


def or_live(base_scenario, tmp_path, posts, gets, human, record=None, rewrite=None):
    """Full four-role exercise through the OpenRouter adapter. Mock replies are the
    scripted double's JSON (NOT AI); each has its own generation record."""
    budget = DemoBudget(tmp_path / "ledger" / "reservations.jsonl", cap_usd=1,
                        input_per_million=0.15, output_per_million=0.60)
    costs = {}
    def reply(n, body):
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        data = ScriptedTestDouble().complete_json(system, user).data
        if rewrite:
            data = rewrite(n, data)
        text = json.dumps(data)
        pt, ct = len((system + user).encode()) // 4, len(text) // 4 + 300
        costs[f"gen-TEST-{n:03d}"] = (pt * 0.15 + ct * 0.60) / 1e6
        return or_reply(n, text, usage={"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct,
                                        "cost": costs[f"gen-TEST-{n:03d}"]})
    rec = record or (lambda g: or_record(g, cost=costs[g]))
    clients = {}
    for r in ROLES:
        c, _ = or_client(tmp_path, or_mock(posts, gets, reply, rec), budget=budget)
        clients[r] = c
    ex = FullExercise(apply_variation(base_scenario, None), clients,
                      Retriever.load(ROOT / "kb/build/chunks.jsonl"), human, out_root=tmp_path / "runs")
    return ex, ex.run(), budget


def test_mock_openrouter_run_passes_live_interactive_and_host_checks(base_scenario, tmp_path, monkeypatch):
    interactive_answers(monkeypatch)
    posts, gets = [], []
    ex, result, budget = or_live(base_scenario, tmp_path, posts, gets, HumanPolicy("interactive"))
    report = inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True, require_interactive_human=True)
    assert report["passed"], report["problems"]
    assert report["served_by"] == ["openrouter:openai/gpt-oss-120b"] and report["human_decisions"] >= 2
    demos = [r["payload"] for r in ex.audit.records if r["kind"] == "DEMO_TURN"]
    assert all(d["serving"]["state"] == "verified" and d["serving"]["provider_name"] == "Groq" for d in demos)
    assert all(b["provider"]["only"] == ["groq"] and b["provider"]["allow_fallbacks"] is False for b in posts)
    assert len(posts) == len(gets) == result.metrics["model_calls"] <= MAX_REQUESTS
    s = budget.summary()
    assert s["requests_sent"] == len(posts) and s["halted"] is None
    assert s["requests_without_reported_usage"] == 0 and s["requests_without_verified_charge"] == 0
    assert 0 < s["reported_usd"] < s["reserved_usd"] <= 1


def test_mock_openrouter_run_stops_at_the_first_unproved_host(base_scenario, tmp_path, monkeypatch):
    """A substitution mid-run: the reply served elsewhere is never used, and no
    later request is sent."""
    interactive_answers(monkeypatch)
    posts, gets = [], []
    def record(g):
        return or_record(g, host="Cerebras", attempts=[{"provider_name": "Cerebras", "status": 200}]) \
            if g == "gen-TEST-004" else or_record(g, cost=0.0001)
    ex, result, budget = or_live(base_scenario, tmp_path, posts, gets, HumanPolicy("interactive"), record=record)
    assert len(posts) == 4 and "mismatch" in budget.halted
    bad = next(r for r in ex.audit.records if r["kind"] == "DEMO_TURN" and r["payload"]["turn_file"].startswith("004_"))
    assert bad["payload"]["serving"]["state"] == "mismatch" and not bad["payload"]["usable"]
    assert effects_after_turn(ex.audit.records, bad["payload"]["turn_file"]) == []
    assert not inspect_demonstration(result.out_dir, ex.audit.prev, require_live=True)["passed"]


@pytest.mark.parametrize("forge", ["state", "provider_name", "generation_id", "removed"])
def test_require_live_rejects_missing_or_altered_host_evidence(base_scenario, tmp_path, monkeypatch, forge):
    from linkdown.audit import GENESIS, _h
    interactive_answers(monkeypatch)
    ex, result, _ = or_live(base_scenario, tmp_path, [], [], HumanPolicy("interactive"))
    path = result.out_dir / "audit.jsonl"
    prev, rows, done = GENESIS, [], False
    for r in [json.loads(s) for s in path.read_text().splitlines()]:
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        if body["kind"] == "DEMO_TURN" and not done:
            done = True
            sv = body["payload"]["serving"]
            if forge == "removed":
                del body["payload"]["serving"]
            else:
                sv.update({"state": "unverified"} if forge == "state" else
                          {"provider_name": "Cerebras"} if forge == "provider_name" else
                          {"generation_id": "gen-OTHER"})
        rows.append({**body, "prev": prev, "hash": _h(prev, body)})
        prev = rows[-1]["hash"]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rp = result.out_dir / "report.json"
    rep = json.loads(rp.read_text()); rep["audit_head"] = prev
    rp.write_text(json.dumps(rep))
    report = inspect_demonstration(result.out_dir, prev, require_live=True)
    assert not report["passed"] and any("Serving host not verified as Groq" in p for p in report["problems"])


# --- Free OpenRouter preflight (GET only), mocked -------------------------------

def endpoint(**kw):
    e = {"name": "Groq | openai/gpt-oss-120b", "provider_name": "Groq", "tag": "groq", "context_length": 131072,
         "max_completion_tokens": 65536, "quantization": "unknown", "status": 0, "uptime_last_30m": 99.9,
         "pricing": {"prompt": "0.00000015", "completion": "0.0000006", "request": "0", "image": "0",
                     "input_cache_read": "0.000000075"},
         "supported_parameters": ["max_tokens", "reasoning", "include_reasoning", "response_format",
                                  "structured_outputs", "temperature", "tools"]}
    e.update(kw)
    return e


def preflight(key_data=None, endpoints=None, key_status=200, ep_status=200, cap=1.0, gen_status=404):
    from exercise_demo.demo_provider import openrouter_preflight
    seen = []
    key_data = {"limit": 1.0, "limit_remaining": 1.0, "limit_reset": None, "usage": 0,
                "effective_budget": {"remaining_usd": 0.42942}, "budgets": [{"remaining_usd": 0.42942}],
                "is_free_tier": False, "label": "free text SECRET-SENTINEL"} if key_data is None else key_data
    eps = [endpoint(), endpoint(provider_name="Cerebras", tag="cerebras")] if endpoints is None else endpoints
    def handler(req):
        seen.append((req.method, req.url.path))
        assert req.method == "GET" and req.headers["authorization"] == "Bearer TEST-OR-KEY-NOT-REAL"
        if req.url.path == "/api/v1/key":
            return httpx.Response(key_status, json={"data": key_data})
        if req.url.path == "/api/v1/generation":
            assert req.url.params["id"] == "gen-linkdown-preflight-0000000000"
            return httpx.Response(gen_status, json={"error": {"code": gen_status, "message": "SECRET-SENTINEL"}})
        assert req.url.path == "/api/v1/models/openai/gpt-oss-120b/endpoints"
        return httpx.Response(ep_status, json={"data": {"id": MODEL, "endpoints": eps}})
    out = openrouter_preflight(httpx.Client(transport=httpx.MockTransport(handler)), "TEST-OR-KEY-NOT-REAL",
                               PROFILES[OR], cap, 0.15, 0.60, 0.42942)
    assert seen == [("GET", "/api/v1/key"), ("GET", "/api/v1/generation"),
                    ("GET", "/api/v1/models/openai/gpt-oss-120b/endpoints")]
    assert "SECRET-SENTINEL" not in json.dumps(out)
    return out


def test_openrouter_preflight_passes_with_a_limited_key_and_the_groq_endpoint():
    out = preflight()
    assert out["ok"], out["problems"]
    assert out["evidence"]["key"]["limit"] == 1.0 and len(out["evidence"]["endpoints"]) == 1
    assert out["evidence"]["generation_record_access"] == {"probe_status": 404}
    assert out["evidence"]["key"]["effective_remaining_usd"] == 0.42942


@pytest.mark.parametrize("kwargs, problem", [
    (dict(key_data={"limit": None, "limit_remaining": None}), "no credit limit"),
    (dict(key_data={"limit": 5.0, "limit_remaining": 5.0}), "above the plan cap"),
    (dict(key_data={"limit": 1.0, "limit_remaining": 0.2}), "below the worst case"),
    (dict(key_status=401), "Key check failed (401)"),
    (dict(endpoints=[endpoint(provider_name="Cerebras")]), "No Groq endpoint"),
    (dict(endpoints=[endpoint(pricing={"prompt": "0.0000002", "completion": "0.0000006"})]), "above the plan's"),
    (dict(endpoints=[endpoint(pricing={"prompt": "0.00000015", "completion": "0.0000006", "request": "0.001"})]),
     "reservation does not cover"),
    (dict(endpoints=[endpoint(pricing={"prompt": "x", "completion": "0.0000006"})]), "unreadable"),
    (dict(endpoints=[endpoint(supported_parameters=["max_tokens", "reasoning"])]), "does not list"),
    (dict(endpoints=[endpoint(context_length=32768)]), "context is too small"),
    (dict(endpoints=[endpoint(max_completion_tokens=8192)]), "output limit is below"),
    (dict(ep_status=503), "Endpoint list failed (503)"),
])
def test_openrouter_preflight_refuses(kwargs, problem):
    out = preflight(**kwargs)
    assert not out["ok"] and any(problem in p for p in out["problems"]), out["problems"]


@pytest.mark.parametrize("status", [200, 302, 400, 401, 402, 403, 429, 500, 503, 529])
def test_generation_probe_requires_not_found(status):
    out = preflight(gen_status=status)
    assert not out["ok"]
    assert out["evidence"]["generation_record_access"]["probe_status"] == status


@pytest.mark.parametrize("changes, missing", [
    ({"limit_reset": "monthly"}, None), ({}, "limit_reset"),
    ({"limit": 0.4}, None), ({"limit_remaining": 1.1}, None),
    ({"limit_remaining": 0.429419}, None),
    ({}, "effective_budget"), ({"effective_budget": None}, None),
    ({"effective_budget": {}}, None), ({"effective_budget": {"remaining_usd": True}}, None),
    ({"effective_budget": {"remaining_usd": 0.429419}}, None),
])
def test_preflight_requires_nonresetting_key_and_sufficient_budget(changes, missing):
    key = {"limit_reset": None, "limit": 1.0, "limit_remaining": 1.0,
           "effective_budget": {"remaining_usd": 1.0}, "budgets": [{"remaining_usd": 1.0}], **changes}
    if missing:
        del key[missing]
    assert not preflight(key_data=key)["ok"]


def test_unbudgeted_key_is_valid_metadata_but_ineligible_for_demo():
    out = preflight(key_data={"limit_reset": None, "limit": None, "limit_remaining": None,
                              "budgets": [], "effective_budget": None})
    assert not out["ok"]
    assert out["evidence"]["key"]["effective_remaining_usd"] is None
    assert len(out["problems"]) == 2
    assert any("no credit limit" in p for p in out["problems"])
    assert any("Key credit remaining" in p for p in out["problems"])


@pytest.mark.parametrize("budget, layers", [
    (None, []), (None, [{"remaining_usd": 1}]),
    ("invalid", []), ({"remaining_usd": "1"}, [{"remaining_usd": "1"}]),
    ({"remaining_usd": 1}, None), ({"remaining_usd": 1}, []),
    ({"remaining_usd": 1}, [None]), ({"remaining_usd": 1}, [{}]),
    ({"remaining_usd": 1}, [{"remaining_usd": 1}, {"remaining_usd": 0.2}]),
    ({"remaining_usd": 0.5}, [{"remaining_usd": 0.75}]),
    ({"remaining_usd": 2}, [{"remaining_usd": 2}]),
])
def test_inconsistent_budget_evidence_blocks_capped_key(budget, layers):
    out = preflight(key_data={"limit_reset": None, "limit": 1, "limit_remaining": 1,
                              "effective_budget": budget, "budgets": layers})
    assert not out["ok"]


def test_successful_cli_preflight_returns_before_creating_budget_or_clients(tmp_path, monkeypatch):
    from scripts import demonstrate as cli
    from exercise_demo import demo_provider

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"provider": "openrouter", "model": MODEL, "approval_reference": "",
                                "cap_usd": 1, "input_per_million": 0.15, "output_per_million": 0.60}))
    monkeypatch.setenv("LINKDOWN_LLM_API_KEY", "TEST-OR-KEY-NOT-REAL")
    monkeypatch.setattr(cli.sys, "argv", ["demonstrate", "--live-plan", str(plan), "--preflight-only",
                                         "--out", str(tmp_path / "out")])
    monkeypatch.setattr(demo_provider, "openrouter_preflight", lambda *args: {"ok": True})
    monkeypatch.setattr(demo_provider, "DemoBudget", lambda *a, **kw: pytest.fail("Created a spending ledger"))
    monkeypatch.setattr(demo_provider, "DemoClient", lambda *a, **kw: pytest.fail("Created a completion client"))
    assert cli.main() == 0
    assert not (tmp_path / "out").exists()


def test_cli_preflight_only_and_openrouter_plan_refusals(tmp_path):
    p = demonstrate("--preflight-only")
    assert p.returncode == 2 and "--preflight-only needs --live-plan" in p.stderr
    plan = {"provider": "openrouter", "model": MODEL, "approval_reference": "TEST-FIXTURE",
            "cap_usd": 1, "input_per_million": 0.15, "output_per_million": 0.60}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    p = demonstrate("--live-plan", path, "--preflight-only", "--authorize-live-spend")
    assert p.returncode == 2 and "never spends" in p.stderr
    for args in (("--live-plan", path, "--preflight-only"),
                 ("--live-plan", path, "--authorize-live-spend", "--out", tmp_path / "out")):
        p = demonstrate(*args)        # the OpenRouter profile is accepted; no key -> refused before any network call
        assert p.returncode == 2 and "LINKDOWN_LLM_API_KEY" in p.stderr, p.stderr
    path.write_text(json.dumps({**plan, "approval_reference": ""}))
    p = demonstrate("--live-plan", path, "--preflight-only")     # the free check needs no approval yet
    assert p.returncode == 2 and "LINKDOWN_LLM_API_KEY" in p.stderr, p.stderr
    p = demonstrate("--live-plan", path, "--authorize-live-spend", "--out", tmp_path / "out")
    assert p.returncode == 2 and "separate approval reference" in p.stderr
    path.write_text(json.dumps({**plan, "cap_usd": 0.40}))
    p = demonstrate("--live-plan", path, "--preflight-only")
    assert p.returncode == 2 and "cap_usd must be at least USD 0.4294" in p.stderr
    assert not (tmp_path / "out").exists()
