"""Write dist/release.json: the release identity and the sha256 of every OTHER deployed file.

Plan rev 2.1 §18.1: release.json never lists or contains its own hash, and no listed file
contains release.json's hash or contents (the app fetches /release.json at runtime). The
integrity of release.json itself is anchored outside the site (deploy record in git,
GitHub Release SHA256SUMS, the report). Prints RELEASE_JSON_SHA256 for that purpose.

    python web/tools/make_release.py DIST --commit SHA [--run-url URL] [--release-id ID]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

NAME = "release.json"
SCHEMA = "linkdown-release/1"


def file_map(dist: Path) -> dict[str, dict]:
    """sha256 and size of every file under dist except release.json, keyed by URL path."""
    out = {}
    for p in sorted(dist.rglob("*")):
        if p.is_file() and p.relative_to(dist).as_posix() != NAME:
            data = p.read_bytes()
            out[p.relative_to(dist).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return out


def bundles_from(dist: Path) -> list[dict]:
    m = dist / "bundles/manifest.json"
    if not m.exists():
        return []
    return [{"bundle_id": e["bundle_id"], "sha256": e["sha256"], "audit_head": e["audit_head"]}
            for e in json.loads(m.read_text(encoding="utf-8"))["bundles"]]


def build_release(dist: Path, commit: str, run_url: str, release_id: str | None = None) -> tuple[bytes, str]:
    files = file_map(dist)
    rid = release_id or f"web-{time.strftime('%Y%m%d', time.gmtime())}-{commit[:7]}"
    release = {"schema": SCHEMA, "release_id": rid, "git_commit": commit,
               "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ci_run_url": run_url,
               "bundles": bundles_from(dist), "files": files}
    data = (json.dumps(release, indent=2, sort_keys=True) + "\n").encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    for rel in files:                                   # §18.1: no listed file may carry this digest
        if digest.encode() in (dist / rel).read_bytes():
            raise SystemExit(f"{rel} contains the release.json digest; refusing (self-reference)")
    return data, digest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dist", type=Path)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--run-url", default="local:not-a-ci-run")
    ap.add_argument("--release-id")
    a = ap.parse_args(argv)
    data, digest = build_release(a.dist, a.commit, a.run_url, a.release_id)
    (a.dist / NAME).write_bytes(data)
    rel = json.loads(data)
    print(f"RELEASE_ID {rel['release_id']}")
    print(f"RELEASE_FILES {len(rel['files'])}")
    print(f"RELEASE_JSON_SHA256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
