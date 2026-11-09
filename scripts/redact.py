"""Remove secrets from run outputs before they are uploaded or committed.

Replaces (a) the exact values of every environment variable whose name ends in
_API_KEY, _TOKEN or _SECRET, and (b) common key formats (sk-..., sk-ant-...,
gsk_..., AIza..., hf_..., Bearer ...) with [REDACTED] in every text file under
the given folder. Prints how many replacements were made.

    python scripts/redact.py runs/
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]
TEXT = {".json", ".jsonl", ".md", ".txt", ".log", ".yaml", ".yml", ".html", ".csv"}


def secrets_from_env() -> list[str]:
    out = []
    for k, v in os.environ.items():
        if v and len(v) >= 8 and k.upper().endswith(("_API_KEY", "_TOKEN", "_SECRET")):
            out.append(v)
    return sorted(set(out), key=len, reverse=True)


def redact_text(text: str, secrets: list[str]) -> tuple[str, int]:
    n = 0
    for s in secrets:
        if s in text:
            n += text.count(s)
            text = text.replace(s, "[REDACTED]")
    for p in PATTERNS:
        text, k = p.subn("[REDACTED]", text)
        n += k
    return text, n


def redact_dir(folder: Path) -> int:
    secrets, total = secrets_from_env(), 0
    for f in folder.rglob("*"):
        if f.is_file() and (f.suffix.lower() in TEXT or f.name.endswith(".log")):
            t = f.read_text(encoding="utf-8", errors="replace")
            new, n = redact_text(t, secrets)
            if n:
                f.write_text(new, encoding="utf-8")
                total += n
    return total


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    n = redact_dir(Path(sys.argv[1]))
    print(f"redact: {n} replacement(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
