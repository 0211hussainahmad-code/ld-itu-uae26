"""Append-only, hash-chained audit log (JSON Lines).

Threat model, stated plainly: the chain makes accidental or casual edits
detectable (verify() fails). It is NOT tamper-proof against someone who can
rewrite the whole file, because the chain head is not anchored externally.
We log observable inputs, retrieved passages, tool calls, gate decisions,
human decisions and short model-written justifications. We do not claim to
expose a model's private internal reasoning.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64


def _h(prev: str, body: dict) -> str:
    raw = prev + json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path, run_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.seq = 0
        self.prev = GENESIS
        self.path.write_text("", encoding="utf-8")
        self.records: list[dict] = []

    def append(self, kind: str, actor: str, payload: dict, sim_min: int | None = None, **meta) -> dict:
        self.seq += 1
        body = {"run_id": self.run_id, "seq": self.seq, "kind": kind, "actor": actor,
                "sim_min": sim_min, "wall_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "payload": payload, **meta}
        rec = {**body, "prev": self.prev, "hash": _h(self.prev, body)}
        self.prev = rec["hash"]
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.records.append(rec)
        return rec


def verify(path: str | Path, expected_head: str | None = None) -> tuple[bool, str]:
    """Check the chain. Pass expected_head (from report.json) to also detect
    records deleted from the end of the file."""
    prev = GENESIS
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, 1):
        rec = json.loads(line)
        body = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
        if rec["prev"] != prev:
            return False, f"line {i}: broken link to previous record"
        if _h(prev, body) != rec["hash"]:
            return False, f"line {i}: record content does not match its hash"
        prev = rec["hash"]
    if expected_head is not None and prev != expected_head:
        return False, "chain head does not match the expected head (records missing at the end?)"
    return True, f"{len(lines)} records, chain intact, head {prev[:16]}"
