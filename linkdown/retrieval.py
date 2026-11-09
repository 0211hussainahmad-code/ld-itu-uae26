"""Source-aware retrieval over the knowledge-base chunks.

Chunks are produced by kb/build_kb.py using ITU's reference chunker, then
stored as JSON Lines with provenance (source id, issuer, version date, clause
hint, page, verification status). Runtime search is BM25: deterministic,
no model download, and it works for Arabic as well as English. When Ollama is
available, kb/build_kb.py also writes the ITU-style ChromaDB collection, so the
same chunks can be searched semantically (see docs/KB.md).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import math
from collections import Counter

_STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were will with
such which who whom whose""".split())
_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25:
    """Okapi BM25 with the Lucene IDF, log(1 + (N - n + 0.5) / (n + 0.5)), which is
    always positive. (The classic IDF is zero or negative for a term found in half
    or more of the documents, so small or focused corpora returned nothing.)"""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg = (sum(self.len) / len(docs)) or 1.0
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def get_scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * dl / self.avg)
            for q in query:
                f = tf.get(q)
                if f:
                    s += self.idf[q] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out


@dataclass
class Hit:
    chunk: dict
    score: float

    def cite_line(self) -> str:
        c = self.chunk
        pages = ""
        if c.get("page"):
            pages = f"pdf p. {c['page']}" + (f"-{c['page_end']}" if c.get("page_end") not in (None, c["page"]) else "")
        where = ", ".join(x for x in (c.get("clause_hint"), pages) if x)
        origin = " [ANALYST NOTE]" if c.get("text_origin") == "analyst_note" else ""
        return (f"[{c['chunk_id']}] {c['title']} ({c.get('issuer', '?')}, {c.get('version_date', '?')}) "
                f"{where}{origin}").strip()


PROMPT_FIELDS = ("chunk_id", "source_id", "text_origin", "title", "issuer", "version_date",
                 "instrument_type", "jurisdiction", "clause_hint", "page", "text")


def content_sha(chunks: list[dict]) -> str:
    """Hash of every chunk field a prompt can show. Excludes build timestamps, so the
    same pinned sources give the same hash on any machine."""
    import hashlib
    rows = sorted(json.dumps({k: c.get(k) for k in PROMPT_FIELDS}, sort_keys=True, ensure_ascii=False)
                  for c in chunks)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


class Retriever:
    def __init__(self, chunks: list[dict]):
        if not chunks:
            raise ValueError("Knowledge base is empty: run kb/build_kb.py first")
        self.chunks = chunks
        self.by_id = {c["chunk_id"]: c for c in chunks}
        self._bm25 = BM25([tokenize(self._doc_text(c)) for c in chunks])

    @staticmethod
    def _doc_text(c: dict) -> str:
        return " ".join([c.get("title", ""), c.get("clause_hint", "") or "", c["text"]])

    @classmethod
    def load(cls, path: str | Path) -> "Retriever":
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls([json.loads(l) for l in lines if l.strip()])

    def search(self, query: str, k: int = 5, jurisdiction: list[str] | None = None,
               topics: list[str] | None = None, source_ids: list[str] | None = None,
               origins: list[str] | None = None) -> list[Hit]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: -scores[i])
        out: list[Hit] = []
        for i in ranked:
            c = self.chunks[i]
            if scores[i] <= 0:
                break
            if jurisdiction and c.get("jurisdiction") not in jurisdiction:
                continue
            if topics and not set(topics) & set(c.get("topics", [])):
                continue
            if source_ids and c["source_id"] not in source_ids:
                continue
            if origins and c.get("text_origin", "primary_text") not in origins:
                continue
            out.append(Hit(c, float(scores[i])))
            if len(out) >= k:
                break
        return out
