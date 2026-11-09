"""Build the LinkDown knowledge base from kb/sources.yaml (+ kb/notes.yaml).

Reuses ITU's reference ingestion code (CrashingGuru/ITUAIReadiness, MIT licence,
pinned commit in scripts/get_itu_reference.sh, fetched into vendor/):
  - chunk_text()      same chunk size (256 words), overlap (30) and 2000-char cap
  - build_metadata()  same base metadata keys; our provenance is added via `extra`
  - parse_file()      for .txt / .md files
PDFs are read with PyMuPDF page by page, the same extraction ITU's parse_file
falls back to, so the text is the same but each chunk keeps its page number and
the clause headings it contains.

Outputs
  kb/build/chunks.jsonl     runtime knowledge base (linkdown/retrieval.py, BM25)
  kb/build/kb_manifest.json what went in: file hash, chunks, origin, verification
  kb/build/chromadb/        only with --chroma: ITU KnowledgeBase collection
                            "kb_main", embedded with Ollama nomic-embed-text

    python kb/build_kb.py
    python kb/build_kb.py --chroma      # needs `ollama serve` + `ollama pull nomic-embed-text`
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import warnings
from pathlib import Path

import yaml

KB = Path(__file__).resolve().parent
ROOT = KB.parent
ITU_ROOT = ROOT / "vendor" / "ITUAIReadiness"
ITU_SIM = ITU_ROOT / "simulation"

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def import_itu():
    """Import ITU's ingestion functions from the pinned vendor copy."""
    if not (ITU_SIM / "server" / "knowledge" / "ingest.py").exists():
        sys.exit("ITU reference code not found. Run: bash scripts/get_itu_reference.sh")
    sys.path.insert(0, str(ITU_SIM))
    from server.knowledge import ingest  # noqa: E402  (ITU code)
    return ingest


# Clause headings: "3.2.6" alone on a line (ITU-T layout), "3.2.6 Title" on one line,
# a single number followed by a short title line ("5" / "Conventions"), or "Article (2)".
_NUM_ONLY = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})$")
_NUM_TITLE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,3})\s+([A-Za-z].{2,90})$")
_ARTICLE = re.compile(r"^(?:Article|ARTICLE)\s*\(?(\d{1,3})\)?(?:\s|$)")


def find_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Return (line_index, label) for lines that start a clause."""
    out = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or "...." in line:                       # skip tables of contents
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        m = _ARTICLE.match(line)
        if m:
            out.append((i, f"Art. {m.group(1)}"))
            continue
        m = _NUM_TITLE.match(line)
        if m:
            out.append((i, m.group(1)))
            continue
        m = _NUM_ONLY.match(line)
        if m and nxt[:1].isalpha() and not nxt.startswith("Rec."):
            # a bare integer is a top-level clause only if small and followed by a short title
            # (page numbers in these PDFs also sit alone on a line)
            if "." in m.group(1) or (int(m.group(1)) <= 20 and len(nxt) <= 60 and nxt[:1].isupper()):
                out.append((i, m.group(1)))
    return out


def read_pdf(path: Path) -> tuple[str, list[int], list[tuple[int, str]]]:
    """Text joined like ITU's PyMuPDF fallback, plus per-word page and clause marks."""
    import pymupdf
    doc = pymupdf.open(str(path))
    pages = [p.get_text() for p in doc]
    page_start_word: list[int] = []        # word index where each page begins
    heads: list[tuple[int, str]] = []      # (word index, clause label)
    w = 0
    for text in pages:
        page_start_word.append(w)
        lines = text.splitlines()
        marks = dict(find_headings(lines))
        for li, line in enumerate(lines):
            if li in marks:
                heads.append((w, marks[li]))
            w += len(line.split())
    return "\n\n".join(pages), page_start_word, heads


def read_html(path: Path) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n")
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def locate(chunks: list[str], norm_words: list[str]) -> list[int]:
    """Word index at which each chunk starts (chunk_text keeps word order)."""
    joined = " ".join(norm_words)
    # char offset -> word index
    starts, pos, out = [], 0, []
    for wd in norm_words:
        starts.append(pos)
        pos += len(wd) + 1
    import bisect
    cursor = 0
    for ch in chunks:
        probe = " ".join(ch.split()[:12])
        off = joined.find(probe, cursor)
        if off < 0:
            off = cursor
        wi = max(0, bisect.bisect_right(starts, off) - 1)
        out.append(wi)
        cursor = off + 1
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_file(src: dict) -> Path | None:
    if src.get("itu_reference_path"):
        p = ITU_ROOT / src["itu_reference_path"]
        if p.exists():
            return p
    if src.get("local_file"):
        p = KB / "docs" / src["local_file"]
        if p.exists():
            return p
    return None


def provenance(src: dict, origin: str) -> dict:
    # YAML reads 2025-09-17 as a date object; keep every field as plain text
    return {k: (str(src[k]) if src.get(k) is not None else None)
            for k in ("title", "issuer", "jurisdiction", "instrument_type", "version_date", "url", "verification")} | {
        "source_id": src["id"], "topics": src.get("topics", []), "text_origin": origin,
        "licence": src.get("licence", "unknown")}


def build(args) -> dict:
    ingest = import_itu()
    reg = yaml.safe_load((KB / "sources.yaml").read_text(encoding="utf-8"))
    notes = (yaml.safe_load((KB / "notes.yaml").read_text(encoding="utf-8")) or {}).get("notes", {})
    # Curated verbatim clauses (kb/curated/clauses.yaml, cut at article boundaries by
    # kb/extract_clauses.py, not by ITU's chunk_text): each one is its own primary_text chunk.
    cur_path = KB / "curated/clauses.yaml"
    curated = (yaml.safe_load(cur_path.read_text(encoding="utf-8")) or {}).get("clauses", []) if cur_path.exists() else []
    unknown = sorted({c["source_id"] for c in curated} - {s["id"] for s in reg["sources"]})
    if unknown:
        raise SystemExit(f"curated clauses for sources not in kb/sources.yaml: {unknown}")
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_dir = KB / "build"
    out_dir.mkdir(exist_ok=True)
    records: list[dict] = []
    manifest = {"built_at": stamp, "sources_version": reg["version"], "notes_version": None,
                "itu_chunk_size": ingest.settings.chunk_size, "itu_chunk_overlap": ingest.settings.chunk_overlap,
                "sources": []}
    manifest["notes_version"] = "notes-0.1" if notes else None
    # Provenance of the ITU reference code actually used. Only trust vendor's OWN .git:
    # without it, git would walk up and report LinkDown's commit instead.
    manifest["itu_reference_commit"] = "unknown (vendor copy has no .git; use scripts/get_itu_reference.sh)"
    if (ITU_ROOT / ".git").exists():
        import subprocess
        r = subprocess.run(["git", "-C", str(ITU_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
        if r.returncode == 0:
            manifest["itu_reference_commit"] = r.stdout.strip()
    manifest["itu_functions_used"] = ["server.knowledge.ingest.chunk_text", "server.knowledge.ingest.build_metadata",
                                      "server.knowledge.ingest.parse_file", "server.knowledge.ingest.embed_texts (--chroma)",
                                      "server.knowledge.kb.KnowledgeBase (--chroma)"]

    for src in reg["sources"]:
        entry = {"id": src["id"], "verification": src.get("verification"), "parts": []}
        f = resolve_file(src)
        if f is not None:
            page_start, heads = None, []
            if f.suffix.lower() == ".pdf":
                text, page_start, heads = read_pdf(f)
            elif f.suffix.lower() in (".html", ".htm"):
                text = read_html(f)
            else:
                text = ingest.parse_file(f)
            chunks = ingest.chunk_text(text)
            norm = text.split()
            starts = locate(chunks, norm)
            import bisect
            for i, ch in enumerate(chunks):
                s = starts[i]
                e = s + len(ch.split())
                page = bisect.bisect_right(page_start, s) if page_start else None
                page_end = bisect.bisect_right(page_start, max(s, e - 1)) if page_start else None
                before = [h for h in heads if h[0] <= s]
                inside = [h[1] for h in heads if s < h[0] < e]
                labels = ([before[-1][1]] if before else []) + inside
                seen = list(dict.fromkeys(labels))
                hint = ("cl. " + ", ".join(seen[:6])) if seen and not seen[0].startswith("Art.") else \
                       (", ".join(seen[:6]) if seen else None)
                meta = ingest.build_metadata(f, i, len(chunks), {"source_id": src["id"], "ingested_at": stamp})
                records.append(provenance(src, "primary_text") | {
                    "chunk_id": f"{src['id']}#c{i + 1}", "page": page, "page_end": page_end, "clause_hint": hint,
                    "file": f.name, "file_sha256": None, "text": ch, "itu_metadata": meta})
            entry["parts"].append({"origin": "primary_text", "file": f.name, "sha256": sha256(f), "chunks": len(chunks)})
            for r in records:
                if r["source_id"] == src["id"] and r["text_origin"] == "primary_text":
                    r["file_sha256"] = entry["parts"][-1]["sha256"]
        if src["id"] in notes:
            note = " ".join(notes[src["id"]].split())
            chunks = ingest.chunk_text(note)
            for i, ch in enumerate(chunks):
                meta = ingest.build_metadata(KB / "notes.yaml", i, len(chunks), {"source_id": src["id"], "ingested_at": stamp})
                records.append(provenance(src, "analyst_note") | {
                    "chunk_id": f"{src['id']}#note{i + 1}", "page": None, "page_end": None, "clause_hint": None,
                    "file": "notes.yaml", "file_sha256": None, "text": ch, "itu_metadata": meta})
            entry["parts"].append({"origin": "analyst_note", "chunks": len(chunks)})
        mine = [c for c in curated if c["source_id"] == src["id"]]
        for i, c in enumerate(mine):
            meta = ingest.build_metadata(cur_path, i, len(mine), {"source_id": src["id"], "ingested_at": stamp})
            records.append(provenance(src, "primary_text") | {
                "chunk_id": c["chunk_id"], "page": c.get("page"), "page_end": c.get("page_end"),
                "clause_hint": c["clause_hint"], "file": "curated/clauses.yaml", "file_sha256": c["source_sha256"],
                "text": " ".join(c["text"].split()), "curated_status": c["status"], "itu_metadata": meta})
        if mine:
            entry["parts"].append({"origin": "curated_clause", "chunks": len(mine), "source_sha256": mine[0]["source_sha256"],
                                   "status": sorted({c["status"] for c in mine})})
        if not entry["parts"]:
            entry["status"] = "missing: run kb/fetch_sources.py or add a note"
        manifest["sources"].append(entry)

    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    manifest["total_chunks"] = len(records)
    manifest["by_origin"] = {o: sum(1 for r in records if r["text_origin"] == o) for o in ("primary_text", "analyst_note")}
    manifest["curated_clauses"] = sum(1 for r in records if r.get("file") == "curated/clauses.yaml")
    manifest["curated_cut_by"] = "kb/extract_clauses.py at article boundaries (not ITU chunk_text); metadata by ITU build_metadata"

    if args.chroma:
        from server.knowledge.kb import KnowledgeBase  # ITU code
        texts = [r["text"] for r in records]
        embeddings = ingest.embed_texts(texts)
        metas = []
        for r in records:
            m = dict(r["itu_metadata"])
            m.update({k: str(r.get(k) or "") for k in ("chunk_id", "title", "issuer", "jurisdiction", "version_date",
                                                     "verification", "text_origin", "clause_hint", "page", "url")})
            m["topics"] = ",".join(r["topics"])
            metas.append(m)
        kb = KnowledgeBase(str(out_dir / "chromadb"))
        try:
            kb.delete_collection("kb_main")
        except Exception:
            pass
        kb.add_documents(texts, embeddings, metas, collection_name="kb_main", ids=[r["chunk_id"] for r in records])
        manifest["chromadb"] = {"path": "kb/build/chromadb", "collection": "kb_main", "count": kb.count("kb_main")}

    (out_dir / "kb_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chroma", action="store_true", help="also write ITU-style ChromaDB (needs Ollama)")
    m = build(ap.parse_args())
    print(f"chunks: {m['total_chunks']}  ({m['by_origin']})")
    for s in m["sources"]:
        parts = ", ".join(f"{p['origin']}:{p['chunks']}" for p in s["parts"]) or s.get("status")
        print(f"  {s['id']:<38} {s['verification']:<17} {parts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
