"""Fingerprints of everything a run depends on (GPT-6 M1 verdict, item 7).

RUN_START records these, so a later replay can tell whether it is checking the
run against the same rules, scenario and topology the run used, or against files
that have changed since. Prompt-side inputs (roles, gaps, KB, prompt code) do not
affect replay, but are recorded so a run can be matched to its exact inputs.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE_SIDE = ("rules", "ledger", "fetch_manifest", "topology", "scenario")   # replay depends on these


def file_sha(path: str | Path | None) -> str | None:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest() if p and p.exists() else None


def scenario_sha(scenario: dict) -> str:
    """Hash of the scenario as run (base + variation applied), independent of key order."""
    return hashlib.sha256(json.dumps(scenario, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def code_commit() -> str | None:
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def input_hashes(*, rules: Path, ledger: Path, fetch_manifest: Path, topology: Path, roles: Path, gaps: Path,
                 scenario: dict, kb_content: str | None) -> dict:
    return {"rules": file_sha(rules), "ledger": file_sha(ledger), "fetch_manifest": file_sha(fetch_manifest),
            "topology": file_sha(topology), "scenario": scenario_sha(scenario),
            "roles": file_sha(roles), "gaps": file_sha(gaps), "kb_content": kb_content,
            "prompt_code": file_sha(ROOT / "linkdown/agents.py"), "code_commit": code_commit()}
