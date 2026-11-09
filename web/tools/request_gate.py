"""Decide which request-driven jobs a push may start (used by the `changes` job in web.yml).

Request files express intent only; they never authorize production (plan rev 2.1 §18.2).
Rules (fail closed):
  - no usable "before" commit -> no request-driven job runs;
  - bundle generation and deployment can never run from the same push (§18.3);
  - M1 has no deploy job: a deploy request is refused outright.

    python web/tools/request_gate.py BEFORE AFTER      (writes key=value lines to $GITHUB_OUTPUT if set)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE, AUDIT, DEPLOY = "web/requests/bundle.json", "web/requests/audit.json", "web/requests/deploy.json"
ZERO = "0" * 40
DEPLOY_ENABLED = False          # M1: there is no deploy job; M2 changes this only after approval A3


class GateError(RuntimeError):
    pass


def decide(changed: list[str] | None) -> dict[str, bool]:
    if changed is None:
        return {"bundle_requested": False, "audit_requested": False, "deploy_requested": False}
    s = set(changed)
    flags = {"bundle_requested": BUNDLE in s, "audit_requested": AUDIT in s, "deploy_requested": DEPLOY in s}
    if flags["deploy_requested"] and not DEPLOY_ENABLED:
        raise GateError("deploy requests are not accepted in M1 (no deploy job, no credentials)")
    if flags["bundle_requested"] and flags["deploy_requested"]:
        raise GateError("bundle generation and deployment may not be requested in the same push")
    return flags


def changed_paths(before: str, after: str, repo: Path = ROOT) -> list[str] | None:
    if not before or before == ZERO:
        return None
    ok = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{before}^{{commit}}"],
                        capture_output=True).returncode == 0
    if not ok:
        return None
    out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", before, after],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p.strip()]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit(__doc__)
    changed = changed_paths(argv[0], argv[1])
    if changed is None:
        print("No usable 'before' commit: request files are ignored (fail closed).")
    else:
        print("changed paths:\n  " + "\n  ".join(changed or ["(none)"]))
    try:
        flags = decide(changed)
    except GateError as e:
        print(f"REQUEST GATE: REFUSED — {e}")
        return 1
    lines = [f"{k}={'true' if v else 'false'}" for k, v in flags.items()]
    print("REQUEST GATE: " + " ".join(lines))
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
