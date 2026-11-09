# LinkDown knowledge base: submission package

This package is the knowledge-base deliverable ("Knowledge base containing policies, regulations, and strategies", built with ITU's reference code CrashingGuru/ITUAIReadiness). It holds **metadata, provenance and the build recipe, not the source documents**. The source texts are rebuilt locally from their official locations, because no redistribution licence was found for them (ITU texts are © ITU; for the UAE texts no licence was found).

| File | What it is |
|---|---|
| `README.md` | This guide: contents, install, query, limitations |
| `PROVENANCE_MANIFEST.md` | Per-source provenance: issuer, date, URL, sha256, licence basis, what the team read, what is indexed, limitations |
| `source_classification.csv` | Machine-generated table (one row per source) from the committed `kb/sources.yaml` and `kb/build/kb_manifest.json` |
| `make_classification.py` (private repository only) | Regenerates the CSV from a given commit |

## 1. What is in it (committed records, KB built 25 Oct 2026)

| Class | Sources | Chunks | Meaning |
|---|---|---|---|
| Primary text, full document | 2: ITU-T Y.3172 (06/2019), ITU AI Ready Report 2.0 | 50 + 85 | Whole text chunked with ITU's `chunk_text` (256 words, overlap 30) and `build_metadata` |
| Curated verbatim excerpts | 3: UAE PDPL 2021 (18 clauses), two official NCSP summary pages (2 + 4 passages) | 24 | Cut at article boundaries by `kb/extract_clauses.py`; each carries ITU metadata, page and file sha256 |
| Analyst note only | 10 | 11 notes in total (the PDPL also has one) | The team's own labelled summary. **Not source text.** It cannot change a gate decision or support a gap finding on its own |
| Registered, nothing indexed | 5 | 0 | Identified and not yet opened |
| **Total** | **20** | **170** (159 source text + 11 notes) | |

Verification classes (separate from what is indexed):

- **Legal verification ledger: 0 completed entries.** No legal rule is treated as verified law. Every legal rule escalates.
- PDPL excerpts: 6 of 18 `human_checked` (both team members checked headings, article numbers and pages; word match by machine check plus an independent GPT reviewer check). 12 are `extracted_unverified`.
- NCSP: only official **summary pages** are indexed. The policy text (v2.0 PDF) was never obtained.
- Register status `primary_verified` means the team opened the source and checked the passage it relies on. It is not a legal opinion.

## 2. Install and build (offline; no API key)

```bash
bash scripts/get_itu_reference.sh     # ITU reference code at commit 84010da -> vendor/ (not redistributed)
pip install -r requirements.txt       # Python 3.12 as in CI (3.13 also worked)
python kb/build_kb.py                 # writes kb/build/chunks.jsonl and kb/build/kb_manifest.json
python kb/eval_retrieval.py           # retrieval check over 30 draft questions
```

**Public-export variant A** (the default safe export) leaves out `kb/curated/clauses.yaml`, which holds the verbatim PDPL and NCSP-summary text. A build from variant A therefore has 146 chunks; its retrieval check gives **29/30** in the top 3 (validated from a fresh clone on 7 Nov). To add the PDPL clauses back, download the official English PDF yourself and cut the clauses from it:

```bash
# PDPL: https://uaelegislation.gov.ae/en/legislations/1972/download
# expected sha256 d5d5f9e93bd6c0dc2afe79776f3101bcd599e4400a67309bc0b378b2812bcf3a (kb/build/fetch_manifest.json)
python -I kb/extract_clauses.py --file uae-pdpl-2021=<PDF> --file uae-ncsp-summary-legportal=<page copy> --file uae-ncsp-summary-uae=<page copy>
python kb/build_kb.py
```

The two NCSP summary pages were copied by the team on 24 Oct 2026. A fresh copy will not match the recorded sha256 if the pages have changed since. **This rebuild path was not executed in this workspace**: the PDF is not here, and the government site is not reachable from it. On 24 Oct the team's own `--check` run passed against the recorded file.

Measured in this workspace (6 Nov 2026, Linux, Python 3.13, full private KB): the rebuild reproduced the committed manifest except its timestamp, and retrieval scored 27/30.

## 3. Query it

```python
from linkdown.retrieval import Retriever
r = Retriever.load("kb/build/chunks.jsonl")
for h in r.search("cross-border transfer of personal data outside the State", k=3):
    print(round(h.score, 1), h.cite_line())
# filters: jurisdiction=["UAE"], topics=[...], source_ids=[...], origins=["primary_text"] or ["analyst_note"]
```

With the full private KB, that query returns PDPL Art. 22, Art. 23 and the Art. 1 cross-border definition as its top three. Retrieval is **BM25** (lexical).

**Vector index: evaluated privately, not published.** In the private repository, a local index built with ITU's `KnowledgeBase` (ChromaDB) and the `sentence-transformers/all-MiniLM-L6-v2` model (Apache-2.0; Chroma's ONNX conversion, CPU only) answered **26/30** of the same questions on the 146-chunk build, against **29/30** for BM25. BM25 therefore stays the retriever. That code, the index and the model are not in this public copy: a ChromaDB index stores the chunk text, and reproduction from this copy has not been demonstrated. `python kb/build_kb.py --chroma` (ITU's default Ollama `nomic-embed-text` path) is in this copy but has not been run, and the committed manifest has no `chromadb` entry. Nothing here is distributed or hosted in the ITU AI for Good Lab.

## 4. Limitations

1. The key UAE cloud instrument (NCSP v2.0) is missing as primary text. Its tier and key-custody rules rest on a law-firm summary.
2. 10 of 20 sources, including every global policy example used for the gap findings, are represented only by the team's notes.
3. 5 registered UAE policies have not been opened.
4. The PDPL text is the official English translation. The Arabic text was not compared.
5. The retrieval questions are not blind: the author of the notes wrote them. No blind set exists.
6. No source was re-checked for amendments after 24 Oct 2026.
7. No Arabic sources.
8. No vector index is published; the private local one scored below BM25 (see §3).
