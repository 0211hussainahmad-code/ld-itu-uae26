"""Secret scanner for public outputs, reusing scripts/redact.py patterns (read-only import).

Reports the pattern and location only, never the matched value.

    python -m web.publication.scan_secrets PATH [PATH ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import PATTERNS, secrets_from_env  # noqa: E402


def scan_text(text: str, where: str) -> list[str]:
    found = [f"{where}: matches key pattern {p.pattern[:24]}..." for p in PATTERNS if p.search(text)]
    found += [f"{where}: contains the value of a secret environment variable"
              for s in secrets_from_env() if s in text]
    return found


def scan_path(path: Path) -> list[str]:
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    out: list[str] = []
    for f in files:
        raw = f.read_bytes()
        if b"\0" in raw[:4096]:
            continue
        out += scan_text(raw.decode("utf-8", errors="replace"), str(f))
    return out


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    hits = [h for p in argv for h in scan_path(Path(p))]
    for h in hits:
        print("SECRET HIT " + h)
    print(f"secret scan: {len(hits)} hit(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
