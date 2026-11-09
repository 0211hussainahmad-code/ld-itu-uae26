"""Copy lint: site copy may only make claims from docs/CLAIMS.md "Can say now".

Fails on phrases from the "Never say" list and on wording the register keeps under
"Cannot say yet". It scans the site's own copy (app source and built output), NOT the
replay bundles: a bundle is recorded evidence of what happened, and a model's words in
it are shown as evidence (and flagged by the engine), not as our claims.

    python -m web.publication.claims_lint PATH [PATH ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# (pattern, why). Case-insensitive, word-bounded.
BANNED = [
    (r"\bimmutable\b", "CLAIMS: say 'tamper-evident', never 'immutable'"),
    (r"\blive ai agents?\b", "CLAIMS Cannot say yet: no full multi-role live run"),
    (r"\blegally grounded\b", "CLAIMS Never say"),
    (r"\b(lawful|compliant|compliance with)\b", "CLAIMS Never say: no legal-status claims"),
    (r"\bchain[- ]of[- ]thought\b", "CLAIMS Never say: we do not expose chain of thought"),
    (r"\bnovel safety mechanism\b", "CLAIMS Never say"),
    (r"\bnobody has ever built\b", "CLAIMS Never say"),
    (r"\bgovernment authori[sz]ation\b", "CLAIMS Never say"),
    (r"\bgrounded\b", "CLAIMS Cannot say yet: 'grounded'"),
    (r"\btested by (outside|external) users\b", "CLAIMS Cannot say yet until T17 evidence exists"),
    (r"\breal (traffic|capacities|routes)\b", "CLAIMS Never say: all network figures are synthetic"),
    (r"\bproduction[- ]ready\b", "Plan rev 2 section 9: no production-readiness claims"),
    (r"\bunlimited scal", "Plan rev 2 section 9: no scalability claims"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), why) for p, why in BANNED]
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".json", ".md", ".txt", ".svg"}
SKIP_PARTS = {"node_modules", "bundles", "tests", "test-results", "playwright-report"}


def lint_text(text: str, where: str) -> list[str]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx, why in _COMPILED:
            m = rx.search(line)
            if m:
                out.append(f"{where}:{i}: '{m.group(0)}' — {why}")
    return out


def lint_path(path: Path) -> list[str]:
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES
        and not (SKIP_PARTS & set(p.relative_to(path).parts)))
    out: list[str] = []
    for f in files:
        out += lint_text(f.read_text(encoding="utf-8", errors="replace"), str(f))
    return out


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    hits = [h for p in argv for h in lint_path(Path(p))]
    for h in hits:
        print("CLAIMS LINT " + h)
    print(f"claims lint: {len(hits)} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
