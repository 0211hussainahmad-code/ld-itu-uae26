"""Structural schema of a public replay bundle (linkdown-replay-bundle/1).

Kept as explicit Python checks (stdlib only, so the existing CI can import it) and
mirrored by the zod schema in web/app/src/lib/bundle.ts. Any change must update both
and bump the schema id.
"""
from __future__ import annotations

import re

SCHEMA_ID = "linkdown-replay-bundle/1"
MANIFEST_ID = "linkdown-bundle-manifest/1"
MODES = {"offline-NOT-AI", "live"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
BUNDLE_ID = re.compile(r"^[0-9a-f]{16}$")

# Fields that would carry prompts, turn files or raw model output. Never allowed anywhere.
FORBIDDEN_KEYS = {"system", "user", "prompt", "prompts", "response_text", "response_json", "raw_response",
                  "messages_raw", "turn_text"}
TOP_KEYS = {"schema", "provenance", "context", "audit", "sources"}
PROVENANCE_KEYS = {"mode", "label", "run_id", "scenario", "scenario_version", "variation", "model", "is_ai",
                   "human", "rules_version", "roles_version", "topology_version", "prompt_version", "inputs",
                   "source_commit", "generator_run_url", "audit_head", "record_count", "withheld_count",
                   "inspect"}
INSPECT_KEYS = {"passed", "mode", "coverage", "problems", "replay", "human", "human_decisions", "served_by",
                "limitations", "metrics"}
RECORD_KEYS = {"seq", "kind", "actor", "prev", "hash", "body", "withheld"}
CONTEXT_KEYS = {"topology", "roles", "scenario"}
# register_status is the team's source-register status from kb/sources.yaml (e.g. "we opened the
# primary text"); it is NOT a legal verification. The verification ledger is separate.
SOURCE_KEYS = {"source_id", "known", "in_kb", "kind", "publish", "title", "issuer", "version_date", "url",
               "register_status", "jurisdiction"}


def find_forbidden(obj, where: str = "$") -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in FORBIDDEN_KEYS:
                out.append(f"{where}.{k}")
            out += find_forbidden(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += find_forbidden(v, f"{where}[{i}]")
    return out


def validate_bundle(b) -> list[str]:
    """Return a list of schema problems (empty means structurally valid)."""
    p: list[str] = []
    if not isinstance(b, dict):
        return ["bundle is not an object"]
    if set(b) != TOP_KEYS:
        p.append(f"top-level keys must be exactly {sorted(TOP_KEYS)}; got {sorted(b)}")
        return p
    if b["schema"] != SCHEMA_ID:
        p.append(f"schema must be {SCHEMA_ID}")
    pv = b["provenance"]
    if not isinstance(pv, dict) or set(pv) != PROVENANCE_KEYS:
        p.append("provenance keys mismatch")
    else:
        if pv["mode"] not in MODES:
            p.append(f"provenance.mode must be one of {sorted(MODES)}")
        if not isinstance(pv["is_ai"], bool):
            p.append("provenance.is_ai must be boolean")
        if not (isinstance(pv["audit_head"], str) and HEX64.match(pv["audit_head"])):
            p.append("provenance.audit_head must be 64 hex characters")
        for k in ("record_count", "withheld_count"):
            if not isinstance(pv[k], int) or isinstance(pv[k], bool) or pv[k] < 0:
                p.append(f"provenance.{k} must be a non-negative integer")
        if not isinstance(pv["inspect"], dict) or set(pv["inspect"]) != INSPECT_KEYS:
            p.append("provenance.inspect keys mismatch")
        if not isinstance(pv["inputs"], dict):
            p.append("provenance.inputs must be an object")
    ctx = b["context"]
    if not isinstance(ctx, dict) or set(ctx) != CONTEXT_KEYS:
        p.append("context keys mismatch")
    else:
        for k in CONTEXT_KEYS:
            c = ctx[k]
            if not isinstance(c, dict) or set(c) != {"sha256", "data"} or not HEX64.match(str(c.get("sha256", ""))):
                p.append(f"context.{k} must be {{sha256, data}}")
    recs = b["audit"]
    if not isinstance(recs, list) or not recs:
        p.append("audit must be a non-empty list")
    else:
        for i, r in enumerate(recs):
            if not isinstance(r, dict) or set(r) != RECORD_KEYS:
                p.append(f"audit[{i}] keys mismatch")
                continue
            if not isinstance(r["seq"], int) or isinstance(r["seq"], bool):
                p.append(f"audit[{i}].seq must be an integer")
            if not (isinstance(r["prev"], str) and HEX64.match(r["prev"])):
                p.append(f"audit[{i}].prev must be 64 hex characters")
            if not (isinstance(r["hash"], str) and HEX64.match(r["hash"])):
                p.append(f"audit[{i}].hash must be 64 hex characters")
            if not isinstance(r["withheld"], bool):
                p.append(f"audit[{i}].withheld must be boolean")
            elif r["withheld"] and r["body"] is not None:
                p.append(f"audit[{i}] is withheld but carries a body")
            elif not r["withheld"] and not isinstance(r["body"], str):
                p.append(f"audit[{i}].body must be the canonical string")
            if not isinstance(r["kind"], str) or not isinstance(r["actor"], str):
                p.append(f"audit[{i}].kind/actor must be strings")
    src = b["sources"]
    if not isinstance(src, dict):
        p.append("sources must be an object")
    else:
        for cid, s in src.items():
            if not isinstance(s, dict) or not set(s) <= SOURCE_KEYS or not {"source_id", "known", "in_kb",
                                                                            "kind", "publish"} <= set(s):
                p.append(f"sources[{cid}] has missing or unexpected fields (no text or excerpt fields in M1)")
    p += [f"forbidden field {w}" for w in find_forbidden({k: b[k] for k in ("provenance", "context", "sources")})]
    return p
