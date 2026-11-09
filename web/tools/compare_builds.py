"""Reproducibility check (§18.1 test 6): two builds of the same commit must list identical files
with identical sha256 values. release.json (the only file carrying built_at) is excluded.

    python web/tools/compare_builds.py DIST_A DIST_B
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_release import file_map  # noqa: E402


def compare(a: Path, b: Path) -> list[str]:
    fa, fb = file_map(a), file_map(b)
    problems = [f"only in first build: {p}" for p in sorted(set(fa) - set(fb))]
    problems += [f"only in second build: {p}" for p in sorted(set(fb) - set(fa))]
    problems += [f"differs between builds: {p}" for p in sorted(set(fa) & set(fb)) if fa[p] != fb[p]]
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.exit(__doc__)
    problems = compare(Path(argv[0]), Path(argv[1]))
    for p in problems:
        print("REPRODUCIBILITY FAIL " + p)
    print("REPRODUCIBILITY: " + ("FAIL" if problems else f"PASS ({len(file_map(Path(argv[0])))} files identical)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
