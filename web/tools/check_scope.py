"""M1 isolation guard (acceptance test M1-T10).

Fails if the branch changes anything outside the paths approved for the website
milestone, relative to the commit the branch started from (PR #4's head).
Frozen scientific inputs, existing workflows, exercise_demo/, scripts/ and
existing reports must stay byte-identical.

    python web/tools/check_scope.py [--base SHA]
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "1d92d96498563b2a7a18362af807b94fba7d7251"   # feature/full-exercise-evidence head (PR #4) at branch start
ALLOWED = [
    ".github/workflows/web.yml",
    ".gitignore",
    "web/*",
    "docs/reports/2026-11-02_M1_web_handoff.md",
    "docs/reports/2026-11-0*_M2_web_handoff.md",
    "docs/reports/2026-11-*_M3_web_handoff.md",
    "docs/reports/2026-11-*_M3.1_web_handoff.md",
    "docs/reports/2026-11-*_M3.2_web_handoff.md",
]


def changed_paths(base: str) -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--no-renames", "--name-only", base, "HEAD"],
                         capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p.strip()]


def outside_scope(paths: list[str]) -> list[str]:
    return [p for p in paths if not any(fnmatch.fnmatch(p, pat) for pat in ALLOWED)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=BASE)
    a = ap.parse_args()
    paths = changed_paths(a.base)
    bad = outside_scope(paths)
    if bad:
        print("SCOPE: FAIL — changes outside the approved website paths:")
        for p in bad:
            print("  " + p)
        return 1
    print(f"SCOPE: PASS — {len(paths)} changed paths, all inside the approved website paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
