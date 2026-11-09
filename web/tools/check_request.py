"""Validate a request file before a request-driven job acts on it. Request files express intent only.

    python web/tools/check_request.py bundle web/requests/bundle.json
    python web/tools/check_request.py audit  web/requests/audit.json

bundle: {"kind": "offline-NOT-AI", "reason": str, "requested_by": str}
        The source commit is the commit that carries the request (a commit cannot name itself);
        the job records it as SOURCE in the anchor line.
audit:  {"scope": "read-only", "reason": str, "requested_by": str}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SPECS = {
    "bundle": {"kind": {"offline-NOT-AI"}},
    "audit": {"scope": {"read-only"}},
}


def check(kind: str, data) -> list[str]:
    if kind not in SPECS:
        return [f"unknown request kind {kind!r}"]
    if not isinstance(data, dict):
        return ["request must be a JSON object"]
    spec = SPECS[kind]
    want = set(spec) | {"reason", "requested_by"}
    problems = []
    if set(data) != want:
        problems.append(f"request keys must be exactly {sorted(want)}")
    for k, allowed in spec.items():
        if data.get(k) not in allowed:
            problems.append(f"{k} must be one of {sorted(allowed)}")
    for k in ("reason", "requested_by"):
        if not isinstance(data.get(k), str) or not data.get(k, "").strip() or len(data.get(k, "")) > 300:
            problems.append(f"{k} must be a non-empty string of at most 300 characters")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit(__doc__)
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"REQUEST INVALID: {e}")
        return 1
    problems = check(argv[0], data)
    for p in problems:
        print("REQUEST INVALID: " + p)
    if not problems:
        print(f"REQUEST OK: {argv[0]} ({data.get('kind') or data.get('scope')}) by {data['requested_by']}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
