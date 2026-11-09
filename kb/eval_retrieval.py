"""Score retrieval against kb/retrieval_questions.yaml.

    python kb/eval_retrieval.py            # top-3, all questions
    python kb/eval_retrieval.py --k 5 --author team-blind

Writes kb/build/retrieval_eval.json (per question: pass/fail and the top-k ids).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from linkdown.retrieval import Retriever  # noqa: E402


def evaluate(retriever: Retriever, questions: list[dict], k: int = 3) -> dict:
    rows = []
    for q in questions:
        hits = retriever.search(q["q"], k=k)
        need = (q.get("must_contain") or "").lower()
        ok = any(h.chunk["source_id"] in q["expect"] and need in h.chunk["text"].lower() for h in hits)
        rows.append({"id": q["id"], "author": q.get("author"), "pass": ok,
                     "top": [h.chunk["chunk_id"] for h in hits]})
    passed = sum(r["pass"] for r in rows)
    return {"k": k, "passed": passed, "total": len(rows), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--author", default=None, help="only questions by this author tag")
    ap.add_argument("--kb", default=str(ROOT / "kb/build/chunks.jsonl"))
    a = ap.parse_args()
    qs = yaml.safe_load((ROOT / "kb/retrieval_questions.yaml").read_text(encoding="utf-8"))["questions"]
    if a.author:
        qs = [q for q in qs if q.get("author") == a.author]
    res = evaluate(Retriever.load(a.kb), qs, a.k)
    for r in res["rows"]:
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r['id']}  {r['top'][:a.k]}")
    print(f"\n{res['passed']}/{res['total']} answered by a top-{a.k} chunk")
    (ROOT / "kb/build/retrieval_eval.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
