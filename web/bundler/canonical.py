"""Exact canonical bytes of an audit record, identical to linkdown/audit.py.

linkdown/audit.py hashes  sha256(prev + json.dumps(body, sort_keys=True,
ensure_ascii=False, separators=(",", ":"), default=str))  where body is the record
without "prev" and "hash". We publish that exact string, so a browser can rehash the
same UTF-8 bytes. Every record is also cross-checked against the engine's own _h().
"""
from __future__ import annotations

import hashlib
import json

from linkdown import audit as _engine_audit

GENESIS = _engine_audit.GENESIS


def canonical_body(record: dict) -> str:
    body = {k: v for k, v in record.items() if k not in ("prev", "hash")}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def record_hash(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def engine_hash(record: dict) -> str:
    """The frozen engine's own hash of this record (private helper, imported read-only)."""
    body = {k: v for k, v in record.items() if k not in ("prev", "hash")}
    return _engine_audit._h(record["prev"], body)


def bundle_bytes(bundle: dict) -> bytes:
    """Deterministic serialisation of a bundle file."""
    return (json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
