"""Shared fixtures for the website tooling tests.

These tests use only the standard library and the repository's own requirements, so the
existing CI (which collects every test under the repository) can run them unchanged.
No test writes third-party text into the repository: planted "copyrighted" text is read
from the locally built kb/build/chunks.jsonl at run time.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHUNKS = ROOT / "kb/build/chunks.jsonl"


@pytest.fixture(scope="session")
def offline_run(tmp_path_factory):
    """One real offline (NOT AI) four-role run, produced exactly as scripts/demonstrate.py does."""
    out = tmp_path_factory.mktemp("runs")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/demonstrate.py"), "--out", str(out)],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    run_dir = Path(re.search(r"^RUN_DIR (.+)$", proc.stdout, re.M).group(1))
    head = re.search(r"^AUDIT_HEAD ([0-9a-f]{64})$", proc.stdout, re.M).group(1)
    report = json.loads((run_dir / "demonstration.json").read_text())
    return run_dir, head, report


@pytest.fixture(scope="session")
def register():
    from web.publication.licences import load_register
    return load_register()


@pytest.fixture(scope="session")
def scanner():
    from web.publication.scan_licence import LicenceScanner
    return LicenceScanner.from_chunks(CHUNKS)


@pytest.fixture(scope="session")
def kb_ids():
    from web.bundler.transform import chunk_ids
    return chunk_ids(CHUNKS)


@pytest.fixture(scope="session")
def third_party_sentence():
    """A real 20-word run from a third-party (ITU) chunk, read at run time, never stored in the repo."""
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        if c["source_id"].startswith("itu-t-y3172") and c.get("text_origin") != "analyst_note":
            words = c["text"].split()
            if len(words) >= 40:
                return " ".join(words[10:30]), c["chunk_id"]
    raise AssertionError("no ITU chunk available to plant")


@pytest.fixture(scope="session")
def built(offline_run, register, scanner, kb_ids):
    from web.bundler.transform import build_bundle
    run_dir, head, report = offline_run
    bundle = build_bundle(run_dir, expected_head=head, inspect_report=report, source_commit="0" * 40,
                          generator_run_url="local:test", register=register, scanner=scanner,
                          kb_chunk_ids=kb_ids)
    return bundle, head


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True).stdout
