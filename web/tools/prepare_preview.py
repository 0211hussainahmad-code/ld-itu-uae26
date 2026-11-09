"""Check a downloaded CI site artifact before it may be uploaded to a preview. Standard library only.

This deploys nothing and needs no credential. It is the gate that makes "deploy the exact CI-verified
artifact, never a rebuild" checkable by a person or a job:

    python web/tools/prepare_preview.py web-dist-<sha>.zip OUTDIR \
        --artifact-sha256 HEX --release-sha HEX --commit SHA [--release-id ID]

1. sha256 of the zip equals --artifact-sha256: the digest GitHub reports for that artifact
   (API field "digest"), recorded in web/deploy/CLOUDFLARE_PREVIEW.md before any upload.
2. The zip is extracted into an empty OUTDIR, refusing absolute paths, "..", symlinks and duplicates.
3. The site is static only: no _worker.js and no functions/ directory, so nothing runs on the host.
4. verify_release.verify(OUTDIR, --release-sha) passes: the anchored release.json digest, every
   listed file's sha256, and every asset a page loads is listed.
5. release.json names --commit (and --release-id, if given), and _headers carries the production CSP.
Exit 0 and "PREVIEW ARTIFACT: PASS" only if all checks pass; otherwise nothing should be uploaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):                       # run as a script: make `web` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from web.tools.verify_release import verify  # noqa: E402

CSP_MARK = "Content-Security-Policy: default-src 'self'"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(zip_path: Path, out: Path) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            mode = info.external_attr >> 16
            if name.startswith("/") or "\\" in name or ".." in parts or not parts:
                problems.append(f"unsafe path in artifact: {name!r}")
            elif stat.S_ISLNK(mode):
                problems.append(f"symlink in artifact: {name!r}")
            elif name in seen:
                problems.append(f"duplicate entry in artifact: {name!r}")
            seen.add(name)
        if problems:
            return problems
        for info in z.infolist():
            if not info.is_dir():
                target = out / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
    return problems


def check(zip_path: Path, out: Path, artifact_sha256: str, release_sha: str, commit: str,
          release_id: str | None = None) -> list[str]:
    digest = sha256_file(zip_path)
    expected = artifact_sha256.removeprefix("sha256:")
    if digest != expected:
        return [f"artifact sha256 {digest} differs from the recorded digest {expected}"]
    if out.exists() and any(out.iterdir()):
        return [f"{out} is not empty: extract into a new, empty directory"]
    out.mkdir(parents=True, exist_ok=True)
    problems = safe_extract(zip_path, out)
    if problems:
        return problems
    if (out / "_worker.js").exists() or (out / "functions").exists():
        problems.append("the artifact contains server code (_worker.js or functions/): static only")
    problems += verify(str(out), release_sha)
    try:
        rel = json.loads((out / "release.json").read_text(encoding="utf-8"))
    except Exception as e:                                              # noqa: BLE001
        return problems + [f"release.json unreadable: {e}"]
    if rel.get("git_commit") != commit:
        problems.append(f"release.json is for commit {rel.get('git_commit')}, not {commit}")
    if release_id and rel.get("release_id") != release_id:
        problems.append(f"release.json is release {rel.get('release_id')}, not {release_id}")
    headers = (out / "_headers").read_text(encoding="utf-8") if (out / "_headers").exists() else ""
    if CSP_MARK not in headers:
        problems.append("_headers does not carry the production Content-Security-Policy")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--artifact-sha256", required=True)
    ap.add_argument("--release-sha", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--release-id")
    a = ap.parse_args(argv)
    problems = check(a.zip, a.out, a.artifact_sha256, a.release_sha, a.commit, a.release_id)
    for p in problems:
        print("PREVIEW ARTIFACT FAIL " + p)
    if problems:
        return 1
    rel = json.loads((a.out / "release.json").read_text(encoding="utf-8"))
    print(f"PREVIEW ARTIFACT: PASS {rel['release_id']} commit {rel['git_commit']} ({len(rel['files'])} files) in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
