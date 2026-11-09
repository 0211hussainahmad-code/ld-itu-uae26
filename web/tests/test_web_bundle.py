"""Bundle build + verify on a real offline run (M1-T3, M1-T4, M1-T6, M1-T7, M1-T8)."""
from __future__ import annotations

import copy
import json
import re
import shutil

import pytest

from web.bundler.canonical import bundle_bytes, sha256_hex
from web.bundler.schema import validate_bundle
from web.bundler.transform import BundleError, build_bundle
from web.bundler.verify import verify_bundle_bytes


def entry_for(data: bytes, b: dict) -> dict:
    pv = b["provenance"]
    d = sha256_hex(data)
    return {"bundle_id": d[:16], "file": f"{d[:16]}.json", "sha256": d, "mode": pv["mode"], "label": pv["label"],
            "audit_head": pv["audit_head"], "record_count": pv["record_count"], "withheld_count": pv["withheld_count"],
            "source_commit": pv["source_commit"], "generator_run_url": pv["generator_run_url"]}


def check(b, head, register, scanner, **kw):
    data = bundle_bytes(b)
    return verify_bundle_bytes(data, expected_head=head, manifest_entry=entry_for(data, b), scanner=scanner,
                               register=register, **kw)


def test_offline_bundle_verifies_fully(built, register, scanner):
    b, head = built
    r = check(b, head, register, scanner)
    assert r.ok, r.problems
    assert r.checked == r.total == b["provenance"]["record_count"] > 100
    assert r.withheld == 0 and r.head == head


def test_truthful_mode_and_labels(built, offline_run):
    b, _ = built
    pv = b["provenance"]
    assert pv["mode"] == "offline-NOT-AI" and pv["model"] == "TEST-DOUBLE-NOT-AI" and pv["is_ai"] is False
    assert pv["human"] == "simulated-human:conservative"
    assert "not AI" in pv["label"] and "TEST-DOUBLE-NOT-AI" in pv["label"]
    assert pv["inspect"]["limitations"] == offline_run[2]["limitations"]          # verbatim
    assert pv["inspect"]["served_by"] == ["test-double:TEST-DOUBLE-NOT-AI"]


def test_no_prompt_or_turn_text_in_bundle(built, offline_run):
    b, _ = built
    text = bundle_bytes(b).decode()
    run_dir = offline_run[0]
    for turn in (run_dir / "turns").glob("*.json"):
        t = json.loads(turn.read_text())
        assert t["system"][:200] not in text and t["user"][:200] not in text
    assert not validate_bundle(b)


def test_schema_rejects_prompt_fields(built):
    b = copy.deepcopy(built[0])
    b["provenance"]["inputs"]["prompt"] = "system prompt text"
    assert any("forbidden field" in p for p in validate_bundle(b))


def test_forbidden_field_inside_a_record_body_fails_verification(built, register, scanner):
    from web.bundler.canonical import record_hash
    b = copy.deepcopy(built[0])
    rec = b["audit"][-1]
    body = json.loads(rec["body"])
    body["payload"]["user"] = "leaked prompt"
    rec["body"] = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    rec["hash"] = record_hash(rec["prev"], rec["body"])
    b["provenance"]["audit_head"] = rec["hash"]
    r = check(b, rec["hash"], register, scanner)
    assert not r.ok and r.failed_at == rec["seq"] and "forbidden" in r.summary()


def test_tampered_bundle_fails_closed_at_the_record(built, register, scanner):
    b = copy.deepcopy(built[0])
    k = 40
    b["audit"][k - 1]["body"] = b["audit"][k - 1]["body"].replace('"actor":', '"actor" :', 1)
    r = check(b, built[1], register, scanner)
    assert r.status == "failed" and r.failed_at == k


def test_head_must_match_external_anchor(built, register, scanner):
    b, head = built
    r = check(b, "f" * 64, register, scanner)
    assert not r.ok and "external anchor" in r.summary()
    data = bundle_bytes(b)
    r2 = verify_bundle_bytes(data, expected_head=None, scanner=scanner, register=register)
    assert not r2.ok and "not an anchor" in r2.summary()


def test_manifest_integrity(built, register, scanner):
    b, head = built
    data = bundle_bytes(b)
    e = entry_for(data, b)
    for k, v in (("sha256", "0" * 64), ("bundle_id", "0" * 16), ("audit_head", "e" * 64), ("record_count", 1)):
        bad = {**e, k: v}
        r = verify_bundle_bytes(data, expected_head=head, manifest_entry=bad, scanner=scanner, register=register)
        assert not r.ok, k


def test_planted_third_party_text_is_caught(offline_run, register, scanner, kb_ids, third_party_sentence, tmp_path):
    run_dir, head, report = offline_run
    sentence, chunk_id = third_party_sentence
    copy_dir = tmp_path / "run"
    shutil.copytree(run_dir, copy_dir)
    # Rewrite one MESSAGE as if a model had quoted ITU text, and re-chain the log consistently.
    from linkdown.audit import _h
    recs = [json.loads(l) for l in (copy_dir / "audit.jsonl").read_text().splitlines()]
    target = next(i for i, r in enumerate(recs) if r["kind"] == "MESSAGE")
    recs[target]["payload"]["text"] = "Quoting: " + sentence
    prev = "0" * 64
    for r in recs:
        r["prev"] = prev
        body = {k: v for k, v in r.items() if k not in ("prev", "hash")}
        r["hash"] = prev = _h(prev, body)
    (copy_dir / "audit.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    kw = dict(expected_head=prev, inspect_report=report, source_commit="0" * 40, generator_run_url="local:test",
              register=register, scanner=scanner, kb_chunk_ids=kb_ids)
    with pytest.raises(BundleError, match="third-party text"):
        build_bundle(copy_dir, **kw)
    # As a hypothetical live bundle with withholding allowed: the record is withheld, the bundle is
    # only "partial", and it is refused unless partial publication is explicitly approved.
    live_report = {**report, "mode": "live"}
    with pytest.raises(BundleError, match="not an AI client"):
        build_bundle(copy_dir, **{**kw, "inspect_report": live_report}, allow_withheld=True)


def test_withheld_records_are_never_counted_as_verified(built, register, scanner):
    b = copy.deepcopy(built[0])
    b["audit"][5]["body"], b["audit"][5]["withheld"] = None, True
    b["provenance"]["withheld_count"] = 1
    r = check(b, built[1], register, scanner)
    assert r.status == "failed"                         # offline bundles may not withhold
    assert r.withheld == 1 and r.checked == r.total - 1


def test_secret_in_bundle_is_caught(built, register, scanner):
    b = copy.deepcopy(built[0])
    b["provenance"]["generator_run_url"] = "https://x/" + "sk-" + "A" * 30
    r = check(b, built[1], register, scanner)
    assert not r.ok and "secret scan" in r.summary()


def test_sources_are_metadata_only_and_flag_invented_ids(built, register):
    b, _ = built
    assert b["sources"], "expected citations"
    for cid, s in b["sources"].items():
        assert "text" not in s and "excerpt" not in s
        if s["known"]:
            assert s["publish"] == register[s["source_id"]]["publish"] == "metadata_only"
    itu = [s for s in b["sources"].values() if s["source_id"].startswith("itu-t-y3172")]
    assert itu and all(set(s) <= {"source_id", "known", "in_kb", "kind", "publish", "title", "issuer",
                                   "version_date", "url", "register_status", "jurisdiction"} for s in itu)


def test_unknown_source_in_register_fails(built, scanner):
    b, head = built
    reg = {}
    r = check(b, head, reg, scanner)
    assert not r.ok and "licence decision" in r.summary()


def test_bundle_bytes_are_deterministic(built):
    b, _ = built
    assert bundle_bytes(b) == bundle_bytes(json.loads(bundle_bytes(b)))
    assert re.fullmatch(r"[0-9a-f]{64}", sha256_hex(bundle_bytes(b)))


def test_unsupported_and_invented_citations_get_source_entries(built):
    b, _ = built
    assert "made-up#c999" in b["sources"]
    assert b["sources"]["made-up#c999"]["known"] is False and b["sources"]["made-up#c999"]["in_kb"] is False
