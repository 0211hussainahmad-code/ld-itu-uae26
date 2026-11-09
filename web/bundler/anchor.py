"""External anchors for bundle heads, read from git history.

The `bundle` job commits each new bundle with a message line

    BUNDLE <bundle_id> AUDIT_HEAD <64-hex head> SOURCE <40-hex commit> RUN <actions run url>

That commit message is outside the bundle file and permanent in git (unlike Actions
logs). verify requires the commit that ADDED the bundle file to carry exactly one such
line for that bundle id, and the bundle's computed head to equal it.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINE = re.compile(r"^BUNDLE ([0-9a-f]{16}) AUDIT_HEAD ([0-9a-f]{64}) SOURCE ([0-9a-f]{40}) RUN (\S+)$", re.M)


class AnchorError(RuntimeError):
    pass


@dataclass(frozen=True)
class Anchor:
    bundle_id: str
    head: str
    source_commit: str
    run_url: str
    commit: str


def anchor_line(bundle_id: str, head: str, source_commit: str, run_url: str) -> str:
    line = f"BUNDLE {bundle_id} AUDIT_HEAD {head} SOURCE {source_commit} RUN {run_url}"
    if not LINE.fullmatch(line):
        raise AnchorError("anchor fields are malformed")
    return line


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def parse_anchors(message: str) -> list[tuple[str, str, str, str]]:
    return LINE.findall(message)


def find_anchor(rel_path: str, bundle_id: str, repo: Path = ROOT) -> Anchor:
    added = [c for c in _git(repo, "log", "--diff-filter=A", "--format=%H", "--", rel_path).split() if c]
    if len(added) != 1:
        raise AnchorError(f"{rel_path}: expected exactly one commit adding the file, found {len(added)}")
    commit = added[0]
    lines = [a for a in parse_anchors(_git(repo, "show", "-s", "--format=%B", commit)) if a[0] == bundle_id]
    if len(lines) != 1:
        raise AnchorError(f"{rel_path}: the commit that added it ({commit[:12]}) carries {len(lines)} anchor "
                          f"lines for bundle {bundle_id}; exactly one is required")
    _, head, source, run = lines[0]
    return Anchor(bundle_id, head, source, run, commit)
