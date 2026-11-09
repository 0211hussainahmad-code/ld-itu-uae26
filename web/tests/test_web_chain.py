"""Exact-byte canonical bodies and fail-closed chain verification (M1-T4, M1-T5)."""
from __future__ import annotations

import copy
import json

from linkdown.audit import AuditLog, verify as engine_verify

from web.bundler.canonical import GENESIS, canonical_body, engine_hash, record_hash
from web.bundler.verify import Result, verify_chain

TRICKY = {"floats": [0.1, 1.0, 1e-07, 0.667, 2.5e20, -0.0], "ints": [0, -3, 2 ** 53 + 1],
          "text": "café — ٱلإمارات 🛰   line\nbreak \"quoted\" \\ back", "none": None, "flags": [True, False],
          "nested": {"z": 1, "a": [{"b": "x"}]}}


def synthetic_records(tmp_path, n=6):
    log = AuditLog(tmp_path / "audit.jsonl", "synthetic-run")
    for i in range(n):
        log.append("EVENT" if i % 2 else "MESSAGE", "tester", {"i": i, **TRICKY}, sim_min=i, extra_meta=i * 0.5)
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").split("\n")
    return [json.loads(l) for l in lines if l.strip()], log.prev


def published(records):
    return [{"seq": r["seq"], "kind": r["kind"], "actor": r["actor"], "prev": r["prev"], "hash": r["hash"],
             "body": canonical_body(r), "withheld": False} for r in records]


def test_canonical_body_reproduces_engine_hash_for_tricky_values(tmp_path):
    records, head = synthetic_records(tmp_path)
    prev = GENESIS
    for r in records:
        body = canonical_body(r)
        assert record_hash(prev, body) == r["hash"] == engine_hash(r)
        prev = r["hash"]
    assert prev == head


def test_full_verification_of_untouched_chain(tmp_path):
    records, head = synthetic_records(tmp_path)
    r = verify_chain(published(records), Result())
    assert not r.problems and r.checked == r.total == len(records) and r.head == head


def _fails_at(recs, k):
    r = verify_chain(recs, Result())
    assert r.problems, "verification should fail"
    assert r.failed_at == k, (r.failed_at, r.problems)


def test_one_byte_flip_fails_at_that_record(tmp_path):
    records, _ = synthetic_records(tmp_path)
    for k in range(1, len(records) + 1):
        recs = published(records)
        body = recs[k - 1]["body"]
        recs[k - 1]["body"] = body.replace('"tester"', '"tester!"', 1)
        _fails_at(recs, k)


def test_reordered_records_fail(tmp_path):
    records, _ = synthetic_records(tmp_path)
    recs = published(records)
    recs[2], recs[3] = recs[3], recs[2]
    _fails_at(recs, 3)


def test_dropped_record_fails(tmp_path):
    records, _ = synthetic_records(tmp_path)
    recs = published(records)
    del recs[3]
    _fails_at(recs, 4)


def test_rewritten_record_with_recomputed_hash_breaks_the_next_link(tmp_path):
    records, _ = synthetic_records(tmp_path)
    recs = published(records)
    body = recs[1]["body"].replace('"i":1', '"i":9', 1)
    assert body != recs[1]["body"]
    recs[1]["body"], recs[1]["hash"] = body, record_hash(recs[1]["prev"], body)
    _fails_at(recs, 3)                      # record 2 now self-consistent; record 3's link breaks


def test_envelope_must_match_hashed_body(tmp_path):
    records, _ = synthetic_records(tmp_path)
    recs = published(records)
    recs[0] = copy.deepcopy(recs[0])
    recs[0]["kind"] = "STATE_CHANGE"
    _fails_at(recs, 1)


def test_engine_verify_agrees_on_ordinary_text(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", "plain-run")
    for i in range(4):
        log.append("EVENT", "tester", {"i": i, "x": 0.667, "t": "café ٱلإمارات"}, sim_min=i)
    assert engine_verify(tmp_path / "audit.jsonl", log.prev)[0]
    lines = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]
    r = verify_chain(published(lines), Result())
    assert not r.problems and r.head == log.prev


def test_line_separator_inside_a_record_does_not_split_it(tmp_path):
    """U+2028 is written unescaped (ensure_ascii=False); the bundler must split on newline only."""
    from web.bundler.transform import read_records
    log = AuditLog(tmp_path / "audit.jsonl", "ls-run")
    log.append("MESSAGE", "tester", {"text": "a\u2028b\u2029c\x85d"})
    recs = read_records(tmp_path)
    assert len(recs) == 1 and recs[0]["hash"] == log.prev
