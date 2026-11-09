"""LinkDown replay-bundle tool.

    python -m web.bundler generate [--out-dir DIR] [--work DIR]
        Run the offline (NOT AI) four-role demonstration exactly as scripts/demonstrate.py
        does, verify it with inspect_demonstration against the head it printed, build the
        bundle, verify the written bundle (rehash, linkage, head, schema, scans, manifest)
        and print BUNDLE_ID / AUDIT_HEAD / BUNDLE_SHA256. It never commits or pushes.

    python -m web.bundler verify [PATH ...] [--expected-head HEX]
        Verify committed bundles (default: every bundle in web/data/bundles) against the
        manifest and the external anchor in the commit that added each file.

    python -m web.bundler ingest --run-dir DIR --expected-head HEX
                                 [--require-live --require-interactive-human] [--allow-withheld]
        Build a bundle from an existing run folder (e.g. a separately approved live run).

Fail closed: any problem exits non-zero and writes nothing further.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.bundler.anchor import AnchorError, find_anchor  # noqa: E402
from web.bundler.canonical import bundle_bytes, sha256_hex  # noqa: E402
from web.bundler.schema import MANIFEST_ID  # noqa: E402
from web.bundler.transform import BundleError, build_bundle, bundle_id_for, chunk_ids  # noqa: E402
from web.bundler.verify import verify_bundle_bytes  # noqa: E402
from web.publication.licences import load_register  # noqa: E402
from web.publication.scan_licence import CHUNKS, LicenceScanner  # noqa: E402

BUNDLES = ROOT / "web/data/bundles"
MANIFEST_NAME = "manifest.json"


def git_head() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def run_url() -> str:
    server, repo, rid = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{rid}" if server and repo and rid else "local:not-a-ci-run"


def load_manifest(out_dir: Path) -> dict:
    p = out_dir / MANIFEST_NAME
    if p.exists():
        m = json.loads(p.read_text(encoding="utf-8"))
        if m.get("schema") != MANIFEST_ID or not isinstance(m.get("bundles"), list):
            raise BundleError("manifest.json is malformed")
        return m
    return {"schema": MANIFEST_ID, "bundles": []}


def write_bundle(bundle: dict, out_dir: Path, *, register, scanner, expected_head: str,
                 allow_partial: bool = False) -> dict:
    data = bundle_bytes(bundle)
    bid = bundle_id_for(data)
    pv = bundle["provenance"]
    entry = {"bundle_id": bid, "file": f"{bid}.json", "sha256": sha256_hex(data), "mode": pv["mode"],
             "label": pv["label"], "audit_head": pv["audit_head"], "record_count": pv["record_count"],
             "withheld_count": pv["withheld_count"], "source_commit": pv["source_commit"],
             "generator_run_url": pv["generator_run_url"],
             "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    # Verify the exact bytes BEFORE anything is written (and again from disk afterwards).
    res = verify_bundle_bytes(data, expected_head=expected_head, manifest_entry=entry, allow_partial=allow_partial,
                              scanner=scanner, register=register)
    if res.status == "failed":
        raise BundleError(res.summary())
    print(f"PRE-WRITE VERIFY: PASS — {res.summary()} Schema, forbidden fields, licence and secret scans clean.")
    print("MANIFEST INTEGRITY: PASS — sha256, bundle_id prefix, head, mode and counts agree.")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(out_dir)
    if any(e["bundle_id"] == bid for e in manifest["bundles"]):
        raise BundleError(f"bundle {bid} already exists; bundles are immutable")
    (out_dir / entry["file"]).write_bytes(data)
    manifest["bundles"].append(entry)
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    disk = (out_dir / entry["file"]).read_bytes()
    res2 = verify_bundle_bytes(disk, expected_head=expected_head, manifest_entry=entry, allow_partial=allow_partial,
                               scanner=scanner, register=register)
    if res2.status == "failed" or disk != data:
        raise BundleError("bundle changed between verification and disk: " + res2.summary())
    print("ON-DISK VERIFY: PASS — the written file is byte-identical to the verified bytes.")
    return entry


def _inspect(run_dir: Path, head: str, require_live: bool, require_interactive_human: bool) -> dict:
    from exercise_demo.demonstration import inspect_demonstration
    return inspect_demonstration(run_dir, head, require_live=require_live,
                                 require_interactive_human=require_interactive_human)


def cmd_generate(a) -> int:
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="linkdown-run-"))
    print("OFFLINE TEST DOUBLE — NOT AI; no provider calls")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/demonstrate.py"), "--out", str(work)],
                          capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        print(proc.stdout[-4000:], proc.stderr[-4000:], sep="\n")
        raise BundleError("scripts/demonstrate.py failed")
    run_dir = re.search(r"^RUN_DIR (.+)$", proc.stdout, re.M)
    head = re.search(r"^AUDIT_HEAD ([0-9a-f]{64})$", proc.stdout, re.M)
    if not run_dir or not head:
        raise BundleError("demonstrate.py did not print RUN_DIR and AUDIT_HEAD")
    run_dir, head = Path(run_dir.group(1)), head.group(1)
    print(f"CAPTURED_AUDIT_HEAD {head}")
    report = _inspect(run_dir, head, False, False)
    print("INSPECT " + json.dumps({k: report.get(k) for k in ("passed", "mode", "problems", "human",
                                                               "human_decisions", "served_by")}))
    if not report.get("passed") or report.get("mode") != "offline-NOT-AI":
        raise BundleError("inspect_demonstration must pass in mode offline-NOT-AI")
    register, scanner = load_register(), LicenceScanner.from_chunks(CHUNKS)
    bundle = build_bundle(run_dir, expected_head=head, inspect_report=report, source_commit=git_head(),
                          generator_run_url=run_url(), register=register, scanner=scanner,
                          kb_chunk_ids=chunk_ids(CHUNKS))
    entry = write_bundle(bundle, Path(a.out_dir), register=register, scanner=scanner, expected_head=head)
    print(f"BUNDLE_ID {entry['bundle_id']}")
    print(f"AUDIT_HEAD {entry['audit_head']}")
    print(f"BUNDLE_SHA256 {entry['sha256']}")
    print(f"SOURCE_COMMIT {entry['source_commit']}")
    print(f"RECORDS {entry['record_count']} WITHHELD {entry['withheld_count']}")
    return 0


def cmd_ingest(a) -> int:
    if bool(a.require_live) != bool(a.require_interactive_human):
        raise BundleError("a live bundle needs both --require-live and --require-interactive-human")
    run_dir = Path(a.run_dir)
    report = _inspect(run_dir, a.expected_head, a.require_live, a.require_interactive_human)
    want = "live" if a.require_live else "offline-NOT-AI"
    if not report.get("passed") or report.get("mode") != want:
        raise BundleError(f"inspect_demonstration must pass in mode {want}: {report.get('problems')}")
    register, scanner = load_register(), LicenceScanner.from_chunks(CHUNKS)
    bundle = build_bundle(run_dir, expected_head=a.expected_head, inspect_report=report, source_commit=git_head(),
                          generator_run_url=run_url(), register=register, scanner=scanner,
                          kb_chunk_ids=chunk_ids(CHUNKS), allow_withheld=a.allow_withheld)
    entry = write_bundle(bundle, Path(a.out_dir), register=register, scanner=scanner, expected_head=a.expected_head,
                         allow_partial=a.allow_withheld)
    print(json.dumps(entry, indent=2))
    return 0


def cmd_verify(a) -> int:
    out_dir = Path(a.out_dir)
    manifest = load_manifest(out_dir)
    entries = {e["file"]: e for e in manifest["bundles"]}
    on_disk = {p.name for p in out_dir.glob("*.json") if p.name != MANIFEST_NAME} if out_dir.exists() else set()
    problems = []
    if set(entries) != on_disk:
        problems.append(f"manifest and files differ: only in manifest {sorted(set(entries) - on_disk)}, "
                        f"only on disk {sorted(on_disk - set(entries))}")
    targets = [Path(p) for p in a.paths] if a.paths else [out_dir / f for f in sorted(on_disk)]
    if not targets and not problems:
        print("verify: no bundles to verify")
        return 0
    register, scanner = load_register(), LicenceScanner.from_chunks(CHUNKS)
    for path in targets:
        entry = entries.get(path.name)
        if entry is None:
            problems.append(f"{path.name}: not in manifest")
            continue
        if a.expected_head:
            head, where = a.expected_head, "command line"
        else:
            try:
                anc = find_anchor(str(path.resolve().relative_to(ROOT)), entry["bundle_id"])
            except (AnchorError, subprocess.CalledProcessError, ValueError) as e:
                problems.append(f"{path.name}: no external anchor ({e})")
                continue
            head, where = anc.head, f"commit {anc.commit[:12]}"
            if anc.source_commit != entry["source_commit"]:
                problems.append(f"{path.name}: anchor SOURCE differs from the manifest")
        res = verify_bundle_bytes(path.read_bytes(), expected_head=head, manifest_entry=entry,
                                  allow_partial=False, scanner=scanner, register=register)
        print(f"{path.name}: {res.summary()} (anchor: {where})")
        if not res.ok:
            problems.append(f"{path.name}: {res.summary()}")
    for p in problems:
        print("VERIFY FAIL " + p)
    print("VERIFY: " + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m web.bundler", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out-dir", default=str(BUNDLES))
    g.add_argument("--work")
    v = sub.add_parser("verify")
    v.add_argument("paths", nargs="*")
    v.add_argument("--out-dir", default=str(BUNDLES))
    v.add_argument("--expected-head")
    i = sub.add_parser("ingest")
    i.add_argument("--run-dir", required=True)
    i.add_argument("--expected-head", required=True)
    i.add_argument("--require-live", action="store_true")
    i.add_argument("--require-interactive-human", action="store_true")
    i.add_argument("--allow-withheld", action="store_true")
    i.add_argument("--out-dir", default=str(BUNDLES))
    a = ap.parse_args(argv)
    try:
        return {"generate": cmd_generate, "verify": cmd_verify, "ingest": cmd_ingest}[a.cmd](a)
    except (BundleError, FileNotFoundError, ValueError) as e:
        print(f"BUNDLER FAIL: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
