"""Independent verification of a published bundle (the same checks the browser makes, plus scans).

Fail closed: any problem makes the result "failed". A bundle with withheld records is
"partial" at best and is refused unless partial publication was explicitly approved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from web.bundler.canonical import GENESIS, record_hash, sha256_hex
from web.bundler.schema import BUNDLE_ID, find_forbidden, validate_bundle
from web.publication.scan_secrets import scan_text as secret_scan_text


@dataclass
class Result:
    status: str = "failed"                 # "full" | "partial" | "failed"
    failed_at: int | None = None           # record sequence number where verification failed
    checked: int = 0                       # records rehashed
    total: int = 0
    withheld: int = 0
    head: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "full"

    def summary(self) -> str:
        if self.status == "full":
            return f"Fully rehashed: {self.checked} of {self.total} records. Head {self.head}."
        if self.status == "partial":
            return (f"Partially verified: {self.checked} of {self.total} records rehashed; {self.withheld} withheld "
                    "and not checkable. Not a complete verification.")
        where = f" at record #{self.failed_at}" if self.failed_at else ""
        return f"Verification failed{where}: " + "; ".join(self.problems)


def _fail(r: Result, msg: str, seq: int | None = None) -> Result:
    r.status = "failed"
    if seq is not None and r.failed_at is None:
        r.failed_at = seq
    r.problems.append(msg)
    return r


def verify_chain(records: list[dict], r: Result) -> Result:
    """Exact-byte rehash and linkage of every record; mutates and returns r."""
    prev = GENESIS
    r.total = len(records)
    for i, rec in enumerate(records, 1):
        if rec.get("seq") != i:
            return _fail(r, f"record #{i}: out of sequence (found {rec.get('seq')})", i)
        if rec.get("prev") != prev:
            return _fail(r, f"record #{i}: broken link to the previous record", i)
        if rec.get("withheld"):
            r.withheld += 1
        else:
            body = rec.get("body")
            if not isinstance(body, str):
                return _fail(r, f"record #{i}: missing canonical body", i)
            if record_hash(prev, body) != rec.get("hash"):
                return _fail(r, f"record #{i}: content does not match its hash", i)
            try:
                parsed = json.loads(body)
            except ValueError:
                return _fail(r, f"record #{i}: body is not JSON", i)
            if parsed.get("seq") != i or parsed.get("kind") != rec.get("kind") or parsed.get("actor") != rec.get("actor"):
                return _fail(r, f"record #{i}: envelope differs from the hashed body", i)
            bad = find_forbidden(parsed)
            if bad:
                return _fail(r, f"record #{i}: forbidden fields {bad}", i)
            r.checked += 1
        prev = rec.get("hash")
    r.head = prev
    return r


def verify_bundle_bytes(data: bytes, *, expected_head: str | None = None, manifest_entry: dict | None = None,
                        allow_partial: bool = False, scanner=None, register: dict | None = None) -> Result:
    r = Result()
    try:
        b = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return _fail(r, f"bundle is not valid UTF-8 JSON ({e})")
    problems = validate_bundle(b)
    if problems:
        r.problems += problems
        return r
    verify_chain(b["audit"], r)
    if r.problems:
        return r
    pv = b["provenance"]
    if r.head != pv["audit_head"]:
        return _fail(r, "computed head differs from the bundle's recorded head")
    if expected_head is not None and r.head != expected_head:
        return _fail(r, "computed head differs from the external anchor")
    if expected_head is None:
        return _fail(r, "no external anchor supplied; the head inside the bundle alone is not an anchor")
    if pv["record_count"] != r.total or pv["withheld_count"] != r.withheld:
        return _fail(r, "record or withheld counts differ from the provenance")
    start = json.loads(b["audit"][0]["body"]) if not b["audit"][0]["withheld"] else None
    if start is None or start.get("kind") != "RUN_START":
        return _fail(r, "first record must be a published RUN_START", 1)
    sp = start.get("payload", {})
    for k in ("model", "is_ai", "human", "variation", "scenario", "rules_version", "prompt_version"):
        if pv.get(k) != sp.get(k):
            return _fail(r, f"provenance.{k} differs from the hashed RUN_START")
    if pv["run_id"] != start.get("run_id") or pv["inputs"] != (sp.get("inputs") or {}):
        return _fail(r, "provenance run_id/inputs differ from the hashed RUN_START")
    if pv["mode"] == "offline-NOT-AI":
        if sp.get("is_ai") is not False or sp.get("model") != "TEST-DOUBLE-NOT-AI":
            return _fail(r, "offline bundle is not labelled TEST-DOUBLE-NOT-AI in RUN_START")
        if r.withheld:
            return _fail(r, "offline bundles must have zero withheld records")
    elif sp.get("is_ai") is not True:
        return _fail(r, "live bundle whose RUN_START is not an AI client")
    insp = pv["inspect"]
    if insp.get("passed") is not True or insp.get("mode") != pv["mode"]:
        return _fail(r, "recorded inspect_demonstration result did not pass for this mode")
    if register is not None:
        unknown = sorted({s["source_id"] for s in b["sources"].values() if s["known"]} - set(register))
        if unknown:
            return _fail(r, f"sources without a licence decision: {unknown}")
        for cid, s in b["sources"].items():
            if s["known"] and s["publish"] != register[s["source_id"]]["publish"]:
                return _fail(r, f"sources[{cid}].publish differs from the licence register")
    secret_hits = secret_scan_text(data.decode("utf-8"), "bundle")
    if secret_hits:
        return _fail(r, "secret scan: " + "; ".join(secret_hits))
    if scanner is not None:
        hits = scanner.scan_json(b)
        if hits:
            return _fail(r, f"licence scan: {len(hits)} match(es), first {hits[0].where} ~ {hits[0].chunk_id}")
    else:
        return _fail(r, "licence scan not run (no scanner); refusing to report a pass")
    if manifest_entry is not None:
        digest = sha256_hex(data)
        if manifest_entry.get("sha256") != digest:
            return _fail(r, "manifest sha256 differs from the bundle file")
        if manifest_entry.get("bundle_id") != digest[:16] or not BUNDLE_ID.match(str(manifest_entry.get("bundle_id"))):
            return _fail(r, "bundle_id is not the sha256 prefix of the file")
        for k, v in (("audit_head", r.head), ("mode", pv["mode"]), ("record_count", r.total),
                     ("withheld_count", r.withheld)):
            if manifest_entry.get(k) != v:
                return _fail(r, f"manifest {k} differs from the bundle")
    if r.withheld:
        r.status = "partial"
        if not allow_partial:
            r.problems.append("bundle has withheld records and partial publication is not approved")
            r.status = "failed"
        return r
    r.status = "full"
    return r
