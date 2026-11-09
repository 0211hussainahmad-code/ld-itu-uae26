"""Shingle scanner: defence in depth against publishing third-party source text.

A clean scan is NOT permission to publish (plan rev 2.1, section 6). It only catches
verbatim runs of 12+ words copied from third-party chunks in kb/build/chunks.jsonl
(every chunk whose text is not the team's own analyst note). The text of the KB is
never written to any output: findings carry the chunk id and the location only.

    python -m web.publication.scan_licence PATH [PATH ...]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "kb/build/chunks.jsonl"
SHINGLE = 12
_WORD = re.compile(r"[0-9a-z]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _key(words) -> bytes:
    return hashlib.blake2b(" ".join(words).encode("utf-8"), digest_size=12).digest()


def shingles(text: str, n: int = SHINGLE):
    w = tokens(text)
    for i in range(len(w) - n + 1):
        yield _key(w[i:i + n])


@dataclass(frozen=True)
class Hit:
    where: str
    chunk_id: str


class LicenceScanner:
    def __init__(self, index: dict[bytes, str], chunk_count: int):
        self.index, self.chunk_count = index, chunk_count

    @classmethod
    def from_chunks(cls, path: Path = CHUNKS) -> "LicenceScanner":
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing: build the KB first (python kb/build_kb.py). "
                                    "The scan fails closed rather than passing without its reference text.")
        index: dict[bytes, str] = {}
        n = 0
        for line in path.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            c = json.loads(line)
            if c.get("text_origin") == "analyst_note":      # the team's own writing
                continue
            n += 1
            for k in shingles(c.get("text", "")):
                index.setdefault(k, c["chunk_id"])
        if n == 0:
            raise ValueError("no third-party chunks found; refusing to report a clean scan")
        return cls(index, n)

    def scan_text(self, text: str, where: str) -> list[Hit]:
        seen, hits = set(), []
        for k in shingles(text):
            cid = self.index.get(k)
            if cid and cid not in seen:
                seen.add(cid)
                hits.append(Hit(where, cid))
        return hits

    def count_by_source(self, text: str) -> dict[str, int]:
        """Number of matching 12-word sequences per source id (scale of a match; text never returned)."""
        counts: dict[str, int] = {}
        for k in shingles(text):
            cid = self.index.get(k)
            if cid:
                sid = cid.split("#", 1)[0]
                counts[sid] = counts.get(sid, 0) + 1
        return counts

    def scan_json(self, obj, where: str = "$") -> list[Hit]:
        hits: list[Hit] = []
        if isinstance(obj, str):
            hits += self.scan_text(obj, where)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                hits += self.scan_json(v, f"{where}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                hits += self.scan_json(v, f"{where}[{i}]")
        return hits

    def scan_path(self, path: Path) -> list[Hit]:
        hits: list[Hit] = []
        files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for f in files:
            raw = f.read_bytes()
            if b"\0" in raw[:4096]:
                continue                                    # binary (fonts, images)
            hits += self.scan_text(raw.decode("utf-8", errors="replace"), str(f))
        return hits


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    sc = LicenceScanner.from_chunks()
    hits = [h for p in argv for h in sc.scan_path(Path(p))]
    for h in hits:
        print(f"LICENCE HIT {h.where}: matches third-party chunk {h.chunk_id}")
    print(f"licence scan: {len(hits)} hit(s) against {sc.chunk_count} third-party chunks")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
