"""Simulator, state, audit log, retrieval and output parsing."""
import json

import pytest
import yaml

from linkdown import agents
from linkdown.audit import AuditLog, verify
from linkdown.retrieval import Retriever
from linkdown.sim import Topology

from conftest import ROOT, make_state


# ---------------- simulator (synthetic) ----------------
def test_topology_must_be_marked_synthetic(tmp_path):
    cfg = yaml.safe_load((ROOT / "config/topology.yaml").read_text(encoding="utf-8"))
    cfg["synthetic"] = False
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):
        Topology.load(p)


@pytest.mark.parametrize("value", [None, "yes", 1, "true"])
def test_synthetic_flag_must_be_exactly_true(tmp_path, value):
    cfg = yaml.safe_load((ROOT / "config/topology.yaml").read_text(encoding="utf-8"))
    if value is None:
        cfg.pop("synthetic")
    else:
        cfg["synthetic"] = value
    p = tmp_path / "t.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):
        Topology.load(p)


def test_delivery_never_exceeds_max_flow_for_any_failure_set(topo):
    """Invariant: for every combination of the long-distance links failing, the
    allocation never delivers more to a region than its max-flow capacity."""
    import itertools
    links = [l["id"] for l in topo.links if l["group"] != "domestic"]
    for n in range(0, 4):
        for cut in itertools.combinations(links, n):
            topo.down = set(cut)
            for prio in (None, ["hospitals", "emergency", "gov_ai"]):
                res = topo.allocate(priority=prio)
                for dest in {r.dest for r in res.values()}:
                    got = sum(r.delivered for r in res.values() if r.dest == dest)
                    assert got <= topo.capacity_to(dest), (cut, dest, got)
                assert all(0 <= r.delivered <= r.demand for r in res.values())


def test_westbound_cut_degrades_europe_traffic(topo):
    assert topo.capacity_to("eu_west") == 110
    assert all(r.health == "OK" for r in topo.allocate().values())
    topo.set_down(["W1", "W2"])
    assert topo.capacity_to("eu_west") == 50
    res = topo.allocate()
    assert sum(r.delivered for r in res.values() if r.dest == "eu_west") == 50   # capacity is respected
    assert res["hospitals"].health == "DEGRADED" and res["gov_ai"].health == "DEGRADED"
    assert res["domestic"].health == "OK" and res["asia_mix"].health == "OK"


def test_priority_plan_is_a_real_trade_off(topo):
    topo.set_down(["W1", "W2"])
    res = topo.allocate(priority=["hospitals", "emergency", "gov_ai"])
    assert res["hospitals"].health == res["emergency"].health == res["gov_ai"].health == "OK"
    assert res["business"].share <= 0.5          # someone pays for the priority


def test_in_country_endpoint_frees_capacity(topo):
    topo.set_down(["W1", "W2"])
    before = topo.allocate()["business"].delivered
    after = topo.allocate(dest_override={"gov_ai": "uae_central"})
    assert after["gov_ai"].health == "OK" and after["business"].delivered > before


# ---------------- state ----------------
def test_state_changes_are_versioned_and_digested(base_scenario):
    st, _ = make_state(base_scenario)
    d0, v0 = st.digest(), st.version
    st.apply("switch_ai_endpoint", {"region": "uae_central"})
    assert st.version == v0 + 1 and st.digest() != d0
    assert st.service["endpoint_region"] == "uae_central"


def test_unavailable_endpoint_changes_nothing(base_scenario, variations):
    v02 = next(v for v in variations if v["id"] == "V02")       # no UAE endpoint
    st, _ = make_state(base_scenario, v02)
    d0 = st.digest()
    ch = st.apply("switch_ai_endpoint", {"region": "uae_central"})
    assert ch["changed"] is None and st.digest() == d0


def test_transfer_is_marked_simulated(base_scenario):
    st, _ = make_state(base_scenario)
    ch = st.apply("transfer_records", {"record_set": "renewal_cases", "dest_region": "uae_central"})
    assert "SIMULATED" in ch["note"]


# ---------------- audit ----------------
def _log(tmp_path, n=5):
    log = AuditLog(tmp_path / "audit.jsonl", "test")
    for i in range(n):
        log.append("EVENT", "test", {"i": i, "text": "عربي ok"}, i)
    return log


def test_audit_chain_verifies(tmp_path):
    log = _log(tmp_path)
    ok, msg = verify(log.path, log.prev)
    assert ok, msg


def test_audit_detects_edit(tmp_path):
    log = _log(tmp_path)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2]); rec["payload"]["i"] = 99
    lines[2] = json.dumps(rec, ensure_ascii=False)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert verify(log.path)[0] is False


def test_audit_detects_deletion_and_truncation(tmp_path):
    log = _log(tmp_path)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text("\n".join(lines[:2] + lines[3:]) + "\n", encoding="utf-8")
    assert verify(log.path)[0] is False
    log.path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    assert verify(log.path)[0] is True                  # stated limitation: not detectable alone
    assert verify(log.path, log.prev)[0] is False       # detectable with the head from report.json


# ---------------- retrieval (FIXTURE corpus, not real documents) ----------------
FIXTURE = [
    {"chunk_id": "fx-uae#c1", "source_id": "fx-uae", "title": "FIXTURE UAE policy", "jurisdiction": "UAE",
     "topics": ["cloud"], "text": "Encryption keys must be managed inside the country. FIXTURE TEXT.",
     "text_origin": "analyst_note"},
    {"chunk_id": "fx-int#c1", "source_id": "fx-int", "title": "FIXTURE international report", "jurisdiction": "International",
     "topics": ["telecom"], "text": "Repair permits for subsea cables should be streamlined. FIXTURE TEXT.",
     "text_origin": "primary_text", "page": 3, "page_end": 4, "clause_hint": "cl. 2.1"},
]


def test_retrieval_ranks_and_filters():
    r = Retriever(FIXTURE)
    assert r.search("encryption keys")[0].chunk["chunk_id"] == "fx-uae#c1"
    assert r.search("encryption keys", jurisdiction=["International"]) == []
    assert r.search("cable repair", topics=["telecom"])[0].chunk["source_id"] == "fx-int"


def test_cite_line_shows_origin_and_location():
    r = Retriever(FIXTURE)
    assert "[ANALYST NOTE]" in r.search("encryption keys")[0].cite_line()
    line = r.search("cable repair")[0].cite_line()
    assert "cl. 2.1" in line and "pdf p. 3-4" in line


def test_empty_kb_is_an_error():
    with pytest.raises(ValueError):
        Retriever([])


def test_built_kb_meets_retrieval_target_if_present():
    path = ROOT / "kb/build/chunks.jsonl"
    if not path.exists():
        pytest.skip("knowledge base not built (python kb/build_kb.py)")
    import sys
    sys.path.insert(0, str(ROOT / "kb"))
    from eval_retrieval import evaluate
    qs = yaml.safe_load((ROOT / "kb/retrieval_questions.yaml").read_text(encoding="utf-8"))["questions"]
    res = evaluate(Retriever.load(path), qs, 3)
    assert res["total"] == 30 and res["passed"] >= 27, res


# ---------------- parsing model output ----------------
def test_parse_flags_invented_citations_and_converts_messages():
    data = {"assessment": "x", "unknowns": ["cause"],
            "messages": [{"to": "regulator", "text": "hi", "cites": ["real#c1", "fake#c9"]}],
            "actions": [{"tool": "send_message", "args": {"to": "ALL", "text": "note"}, "cites": ["real#c1"]},
                        {"tool": "transfer_records", "args": {}, "cites": []},
                        {"no_tool": True}]}
    t = agents.parse_turn("service", data, {"real#c1"}, ["transfer_records", "send_message"])
    assert t.unsupported_cites == ["fake#c9"]
    assert len(t.messages) == 2 and len(t.actions) == 1
    assert t.malformed == ["action without tool"]


def test_parse_rejects_non_object():
    t = agents.parse_turn("service", None, set(), [])
    assert t.malformed == ["no JSON object"] and not t.actions


def test_parse_keeps_the_options_the_model_considered():
    data = {"assessment": "a", "options": [{"option": "switch to in-country endpoint", "decision": "keep",
                                            "reason": "no data moves"}, {"bad": 1}, "x"],
            "actions": []}
    t = agents.parse_turn("service", data, set(), [])
    assert t.options == [{"option": "switch to in-country endpoint", "decision": "keep", "reason": "no data moves"}]
