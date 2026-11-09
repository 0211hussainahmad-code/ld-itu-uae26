"""Cut verbatim key clauses out of a primary legal text into kb/curated/clauses.yaml (T06, T11).

Each clause is located by a start anchor and an end anchor in the text that PyMuPDF
(the pinned extractor, requirements.txt) gives for the official file, with the running
header and page numbers removed and all whitespace collapsed to single spaces. Nothing
is retyped by hand, so the quote is exactly the file's words (typos included).

    python -I kb/extract_clauses.py --file uae-pdpl-2021=<PDPL PDF> \
        --file uae-ncsp-summary-legportal=<NCSP_official_summary_uaelegislation.md> \
        --file uae-ncsp-summary-uae=<NCSP_official_summary_u.ae.md>          # write the clauses
    python -I kb/extract_clauses.py --file ... --check                      # re-verify every quote

Markdown page copies are compared after removing markdown marks (**, *, #, link
targets) and collapsing whitespace; they have no page numbers.

The file itself is NOT committed (kb/docs/ is gitignored: no redistribution licence is
assumed). Its sha256 must equal the one in kb/build/fetch_manifest.json. A clause stays
`status: extracted_unverified` until both team members compare it with the PDF and sign
the T06 sheet (docs/T06_PDPL_CLAUSES.md); only then may a ledger entry name them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

KB = Path(__file__).resolve().parent
OUT = KB / "curated/clauses.yaml"
MANIFEST = KB / "build/fetch_manifest.json"

PDPL = {
    "source_id": "uae-pdpl-2021",
    "header": "Federal Decree by Law Concerning the Protection of Personal Data",
    # (chunk suffix, clause hint, start anchor, end anchor - exclusive; None = end of text)
    "clauses": [
        ("art1-state-office", "Art. 1 (definitions: State, Office)", "State : The United Arab Emirates", "Data : An organized"),
        ("art1-personal-data", "Art. 1 (definition: Personal Data)", "Personal Data : Any data related", "Sensitive Personal Data :"),
        ("art1-establishment", "Art. 1 (definitions: Establishment, Controller, Processor)", "Establishment : Any individual company", "Data Protection Officer :"),
        ("art1-processing", "Art. 1 (definitions: Processing, Automated Processing)", "Processing : Any operation", "Personal Data Security :"),
        ("art1-cross-border", "Art. 1 (definition: Cross-Border Processing)", "Cross-Border Processing : Dissemination", "Consent : The consent"),
        ("art2", "Art. 2 (scope and exclusions)", "Article (2) Scope of Application", "Article (3) Bureau's Power"),
        ("art4-1-5", "Art. 4(1)-(5) (processing without consent)", "Article (4) Cases of Processing", "6. If the processing is necessary for archival"),
        ("art4-6-11", "Art. 4(6)-(11) (processing without consent, continued)", "6. If the processing is necessary for archival", "Article (5) Personal Data Processing Controls"),
        ("art5", "Art. 5 (processing controls)", "Article (5) Personal Data Processing Controls", "Article (6) Terms of Consent"),
        ("art7-4", "Art. 7(4) (controller's record, incl. cross-border movement)", "4. Maintain a special record for Personal Data", "5. Appoint the Processor"),
        ("art9-1", "Art. 9(1) (breach notification)", "Article (9) Reporting Personal Data Breach", "2. In all cases, the Controller shall notify the Data Subject"),
        ("art18", "Art. 18 (automated processing)", "Article (18) Right to Processing and Automated Processing", "Article (19) Contacting the Controller"),
        ("art20", "Art. 20 (personal data security)", "Article (20) Personal Data Security", "Article 21 Assessment"),
        ("art21-1-2", "Art. 21(1)-(2) (impact assessment)", "Article 21 Assessment", "3. The assessment stipulated"),
        ("art22", "Art. 22 (cross-border transfer, proper protection level)", "Article (22) Cross-Border Transfer", "Article (23) Cross-Border Transfer"),
        ("art23", "Art. 23 (cross-border transfer, no proper protection level)", "Article (23) Cross-Border Transfer", "Article (24) Complaints"),
        ("art28-29", "Arts. 28-29 (executive regulations; regularisation)", "Article (28) The Executive Regulation", "Article (30) Repeals"),
        ("art31", "Art. 31 (entry into force)", "Article (31) Publication", "Khalifa Bin Zayed Al-Nahyan President"),
    ],
}
NCSP_LEGPORTAL = {
    "source_id": "uae-ncsp-summary-legportal",
    "clauses": [
        ("objectives-components", "policy page: objectives, key components, expected outcomes", "Policy Objectives", "Target Audience"),
        ("target-audience", "policy page: target audience", "Target Audience", None),
    ],
}
NCSP_UAE = {
    "source_id": "uae-ncsp-summary-uae",
    "clauses": [
        ("consumer-domains-1", "u.ae page: cloud consumer domains (part 1)", "Cloud Consumers The following section",
         "Interoperability and Portability Requirements to ensures that the cloud consumer"),
        ("consumer-domains-2", "u.ae page: cloud consumer domains (part 2)",
         "Interoperability and Portability Requirements to ensures that the cloud consumer", "Cloud Service Providers This section"),
        ("provider-domains-1", "u.ae page: cloud service provider domains (part 1)", "Cloud Service Providers This section",
         "Interoperability and Portability Requirements to maximize"),
        ("provider-domains-2", "u.ae page: cloud service provider domains (part 2)",
         "Interoperability and Portability Requirements to maximize", "Read more:"),
    ],
}
SPECS = {x["source_id"]: x for x in (PDPL, NCSP_LEGPORTAL, NCSP_UAE)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(s: str) -> str:
    return " ".join(s.split())


def pages_text(pdf: Path, header: str) -> list[str]:
    """Normalised text of each page with the running header and page number removed."""
    import pymupdf
    out = []
    for i, page in enumerate(pymupdf.open(str(pdf)), start=1):
        t = norm(page.get_text())
        t = re.sub(rf"^{re.escape(header)} {i}\b ?", "", t)       # header line, then the page number
        out.append(t)
    return out


def md_text(path: Path) -> list[str]:
    """A saved web page in markdown as one 'page' of plain words: link targets, emphasis,
    heading and bullet marks removed."""
    t = path.read_text(encoding="utf-8")
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)              # [text](url) -> text
    t = re.sub(r"(?m)^\s*(#+|\*|-)\s+", "", t)                   # heading / bullet marks
    t = t.replace("**", "").replace("\u00a0", " ")
    return [norm(t)]


def load_pages(path: Path, spec: dict) -> list[str]:
    return pages_text(path, spec["header"]) if path.suffix.lower() == ".pdf" else md_text(path)


def locate(pages: list[str]) -> tuple[str, list[int]]:
    """Whole text joined by single spaces, and the character offset where each page starts."""
    starts, pos = [], 0
    for p in pages:
        starts.append(pos)
        pos += len(p) + 1
    return " ".join(pages), starts


def page_of(offset: int, starts: list[int]) -> int:
    import bisect
    return bisect.bisect_right(starts, offset)


def cut(text: str, starts: list[int], start: str, end: str | None) -> tuple[str, int, int]:
    i = text.find(start)
    if i < 0 or text.find(start, i + 1) >= 0:
        raise ValueError(f"start anchor not found exactly once: {start!r}")
    j = text.find(end, i + len(start)) if end else len(text)
    if j < 0:
        raise ValueError(f"end anchor not found after the start: {end!r}")
    quote = text[i:j].strip()
    return quote, page_of(i, starts), page_of(i + len(quote) - 1, starts)


def extract(pdf: Path, spec: dict) -> list[dict]:
    text, starts = locate(load_pages(pdf, spec))
    digest = sha256(pdf)
    out = []
    for suffix, hint, a, b in spec["clauses"]:
        quote, p0, p1 = cut(text, starts, a, b)
        if len(quote) > 2000:
            raise ValueError(f"{suffix}: {len(quote)} characters; split it (prompts show chunks of at most 2,000)")
        paged = pdf.suffix.lower() == ".pdf"
        out.append({"chunk_id": f"{spec['source_id']}#{suffix}", "source_id": spec["source_id"], "clause_hint": hint,
                    "page": p0 if paged else None, "page_end": p1 if paged else None, "text": quote, "source_sha256": digest,
                    "status": "extracted_unverified"})
    return out


def check(pdf: Path, clauses: list[dict], spec: dict) -> list[str]:
    """Problems: a quote that is not a verbatim (whitespace-normalised) part of the file,
    a wrong page, or a file whose hash differs from the one the clause was cut from."""
    text, starts = locate(load_pages(pdf, spec))
    digest, probs = sha256(pdf), []
    for c in clauses:
        if c["source_id"] != spec["source_id"]:
            continue
        if c["source_sha256"] != digest:
            probs.append(f"{c['chunk_id']}: cut from a different file ({c['source_sha256'][:12]})")
        i = text.find(norm(c["text"]))
        if i < 0:
            probs.append(f"{c['chunk_id']}: quote is not verbatim in the file")
        elif c.get("page") is not None and page_of(i, starts) != c["page"]:
            probs.append(f"{c['chunk_id']}: starts on page {page_of(i, starts)}, not {c['page']}")
    return probs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", action="append", required=True, metavar="ID=PATH")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    doc = yaml.safe_load(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"version": "clauses-0.1", "clauses": []}
    bad = 0
    for item in a.file:
        sid, _, path = item.partition("=")
        if sid not in SPECS:
            print(f"REFUSED {item}: no clause spec for {sid}")
            return 1
        f, spec = Path(path), SPECS[sid]
        rec = (man.get(sid) or {}).get("sha256")
        if rec and rec != sha256(f):
            print(f"REFUSED: {f} does not match the fetch-manifest hash of {sid} ({rec[:12]})")
            return 1
        if a.check:
            probs = check(f, doc["clauses"], spec)
            n = sum(1 for c in doc["clauses"] if c["source_id"] == sid)
            print("\n".join(probs) if probs else f"all {n} {sid} quotes are verbatim, on the stated page, from this file")
            bad += bool(probs)
            continue
        new = extract(f, spec)
        old = {c["chunk_id"]: c for c in doc["clauses"]}
        for c in new:                       # never reset a status the humans already raised
            if old.get(c["chunk_id"], {}).get("text") == c["text"]:
                c["status"] = old[c["chunk_id"]].get("status", c["status"])
                c.update({k: v for k, v in old[c["chunk_id"]].items() if k.startswith("verified")})
        doc["clauses"] = [c for c in doc["clauses"] if c["source_id"] != sid] + new
        print(f"wrote {len(new)} {sid} clauses")
    if not a.check:
        order = list(SPECS)
        doc["clauses"].sort(key=lambda c: order.index(c["source_id"]) if c["source_id"] in order else len(order))
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(HEADER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8")
    return 1 if bad else 0


HEADER = """# Curated verbatim clauses (T06, T11). Each one is its own knowledge-base chunk
# (text_origin: primary_text), shown to models as SOURCE TEXT.
# PDPL clauses: cut by kb/extract_clauses.py from the team's download of the official
# English translation (uaelegislation.gov.ae, 24 Oct 2026); quotes are machine-cut,
# never retyped. NCSP lines: copied verbatim from the two official summary pages the
# team saved on 24 Oct 2026 (instrument_type official_summary: a government web page
# describing the policy, NOT the policy text; it holds no tier or key-custody clause).
# status: extracted_unverified until both team members sign docs/T06_PDPL_CLAUSES.md.
# Excerpts only (licence: link_and_excerpt); the full files are not redistributed.
"""

if __name__ == "__main__":
    sys.exit(main())
