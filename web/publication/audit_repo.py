"""Read-only publication audit (plan rev 2.1 §7; acceptance test M1-T9).

Inventories what would become public if the repository (or a mirror) were made public, and
reports findings by location and severity. It NEVER deletes, rewrites, uploads or quotes
protected text: findings name the place (ref/path/blob/artifact/run) and the matched chunk id
or pattern kind only. Personal data is reported as counts by domain, never as values.

Runs in GitHub Actions (needs `gh`, GH_TOKEN with contents:read + actions:read, a full clone
with all refs, and the built KB as the third-party reference text).

    python -m web.publication.audit_repo --repo OWNER/NAME --out REPORT.md
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.redact import PATTERNS  # noqa: E402
from web.publication.scan_licence import CHUNKS, LicenceScanner  # noqa: E402

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
BENIGN_EMAIL_DOMAINS = {"users.noreply.github.com", "anthropic.com", "example.com", "example.invalid", "itu.int"}
BINARY_REVIEW = {".png", ".jpg", ".jpeg", ".pdf", ".gif", ".webp", ".heic", ".zip", ".docx", ".xlsx"}
MAX_BLOB = 3_000_000
MAX_ARTIFACT_BYTES = 80_000_000
MAX_ARTIFACTS = 60
MAX_LOG_RUNS = 400


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8", "replace")


def gh_json_lines(path: str, jq: str) -> list[dict]:
    out = subprocess.run(["gh", "api", "--paginate", path, "--jq", jq], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {out.stderr.strip()[:200]}")
    return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]


def gh_download(path: str, dest: Path) -> tuple[bool, str]:
    with dest.open("wb") as f:
        out = subprocess.run(["gh", "api", path], stdout=f, stderr=subprocess.PIPE)
    return out.returncode == 0, out.stderr.decode("utf-8", "replace").strip()[:160]


class Findings:
    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []      # severity, area, location, finding

    def add(self, sev: str, area: str, loc: str, what: str):
        self.rows.append((sev, area, loc, what))


# Severity of verbatim third-party text by the source's licence (kb/sources.yaml, read-only):
#   explicitly all-rights-reserved ITU texts -> High; no licence found / unconfirmed -> Medium
#   (the source register's own "link_and_excerpt" policy allows short excerpts: a team decision);
#   reuse expressly allowed -> Low.
def licence_severity(source_id: str) -> str:
    from web.publication.licences import load_sources
    lic = str(load_sources().get(source_id, {}).get("licence", ""))
    if "all rights reserved" in lic.lower() or "reproduce extracts" in lic.lower():
        return "High"
    if "reuse allowed" in lic.lower() or "public domain" in lic.lower():
        return "Low"
    return "Medium"


def licence_rows(F, area: str, loc: str, counts: dict[str, int]) -> None:
    by_sev: dict[str, list[str]] = collections.defaultdict(list)
    for sid, n in sorted(counts.items()):
        by_sev[licence_severity(sid)].append(f"{sid} (~{n} matching 12-word sequences)")
    for sev, items in by_sev.items():
        F.add(sev, area, loc, "verbatim third-party text: " + "; ".join(items))


def scan_text(text: str, scanner: LicenceScanner) -> dict:
    lic = scanner.count_by_source(text)
    sec = sorted({p.pattern[:18] for p in PATTERNS if p.search(text)})
    emails = collections.Counter(d.lower() for d in EMAIL.findall(text) if d.lower() not in BENIGN_EMAIL_DOMAINS)
    return {"licence_sources": lic, "secret_patterns": sec, "email_domains": dict(emails)}


# ---- git history ---------------------------------------------------------------------------------

def audit_git(scanner, F: Findings) -> dict:
    refs = [l.split() for l in git("for-each-ref", "--format=%(objectname) %(refname)").splitlines() if l.strip()]
    commits = int(git("rev-list", "--all", "--count").strip())
    objs = [l.split(" ", 1) for l in git("rev-list", "--objects", "--all").splitlines()]
    paths: dict[str, set[str]] = collections.defaultdict(set)
    for o in objs:
        if len(o) == 2:
            paths[o[0]].add(o[1])
    batch = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                           input="\n".join(paths) + "\n", capture_output=True, text=True, check=True).stdout
    blobs = [(s.split()[0], int(s.split()[2])) for s in batch.splitlines() if s.split()[1:2] == ["blob"]]
    scanned = skipped_big = binaries = 0
    turn_paths: set[str] = set()
    tips = {}
    for ref in ("refs/remotes/origin/main", "refs/remotes/origin/evidence"):
        try:
            tips[ref.rsplit("/", 1)[-1]] = {l.split()[2] for l in git("ls-tree", "-r", ref).splitlines() if l.strip()}
        except subprocess.CalledProcessError:
            pass
    for sha, size in blobs:
        names = sorted(paths[sha])
        where = [name for name, s in tips.items() if sha in s]
        if where:
            names = [f"{n} [in current {'+'.join(where)}]" for n in names]
        if any(Path(n.split(" [")[0]).suffix.lower() in BINARY_REVIEW for n in names):
            binaries += 1
            F.add("Low", "git", ", ".join(names[:3]), f"binary file ({size} bytes): needs a human look before publication")
            continue
        if size > MAX_BLOB:
            skipped_big += 1
            F.add("Medium", "git", ", ".join(names[:3]), f"text blob over {MAX_BLOB} bytes not scanned")
            continue
        data = git("cat-file", "-p", sha, binary=True)
        if b"\0" in data[:4096]:
            binaries += 1
            continue
        scanned += 1
        r = scan_text(data.decode("utf-8", "replace"), scanner)
        if any("/turns/" in n for n in names):
            turn_paths.update(n for n in names if "/turns/" in n)
        if r["licence_sources"]:
            licence_rows(F, "git", ", ".join(names[:3]) + f" (blob {sha[:10]})", r["licence_sources"])
        if r["secret_patterns"]:
            in_tests = all(n.startswith(("tests/", "web/tests/")) for n in names)
            F.add("Medium" if in_tests else "High", "git", ", ".join(names[:3]) + f" (blob {sha[:10]})",
                  "matches a key pattern (value not shown)" + ("; in test code, likely a fake fixture key: "
                                                               "a human confirms" if in_tests else ""))
        if r["email_domains"]:
            F.add("Low", "git", ", ".join(names[:3]), "email addresses by domain: " +
                  ", ".join(f"{d}×{n}" for d, n in sorted(r["email_domains"].items())))
    msgs = git("log", "--all", "--format=%H%x00%B%x1e")
    msg_secret = sum(1 for m in msgs.split("\x1e") if any(p.search(m) for p in PATTERNS))
    if msg_secret:
        F.add("High", "git", "commit messages", f"{msg_secret} commit message(s) match a key pattern")
    if turn_paths:
        F.add("Medium", "git", f"{len(turn_paths)} turn file paths (e.g. {sorted(turn_paths)[0]})",
              "run turn files in history: they hold prompts; see High rows for any third-party text")
    return {"refs": len(refs), "branches": sorted(r[1] for r in refs if r[1].startswith("refs/remotes/")),
            "tags": sorted(r[1] for r in refs if r[1].startswith("refs/tags/")), "commits": commits,
            "blobs": len(blobs), "blobs_scanned": scanned, "binaries": binaries, "big_skipped": skipped_big,
            "turn_files": len(turn_paths), "commit_messages_scanned": msgs.count("\x1e")}


# ---- Actions artifacts and logs -------------------------------------------------------------------

def scan_zip(path: Path, scanner, F: Findings, area: str, loc: str) -> dict:
    stats = {"entries": 0, "turn_files": 0, "text_scanned": 0}
    lic, sec, mail = collections.Counter(), set(), collections.Counter()
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            stats["entries"] += 1
            if "/turns/" in "/" + info.filename or info.filename.startswith("turns/"):
                stats["turn_files"] += 1
            if info.file_size > MAX_BLOB:
                continue
            data = z.read(info)
            if b"\0" in data[:4096]:
                continue
            stats["text_scanned"] += 1
            r = scan_text(data.decode("utf-8", "replace"), scanner)
            lic.update(r["licence_sources"])
            sec.update(r["secret_patterns"])
            mail.update(r["email_domains"])
    if lic:
        licence_rows(F, area, loc, dict(lic))
    if sec:
        F.add("High", area, loc, "matches a key pattern (value not shown)")
    if stats["turn_files"]:
        F.add("Medium", area, loc, f"{stats['turn_files']} turn files (prompts)")
    if mail:
        F.add("Low", area, loc, "email addresses by domain: " + ", ".join(f"{d}×{n}" for d, n in sorted(mail.items())))
    return stats


def audit_actions(repo: str, scanner, F: Findings, work: Path) -> dict:
    arts = gh_json_lines(f"/repos/{repo}/actions/artifacts?per_page=100",
                         ".artifacts[] | {id, name, size_in_bytes, expired, created_at, expires_at, "
                         "run: .workflow_run.id, branch: .workflow_run.head_branch}")
    live = [a for a in arts if not a["expired"]]
    families = collections.Counter(re.sub(r"[-_][0-9a-f]{7,}$|-\d+$", "-*", a["name"]) for a in arts)
    downloaded = 0
    for a in sorted(live, key=lambda a: a["created_at"], reverse=True):
        if downloaded >= MAX_ARTIFACTS or a["size_in_bytes"] > MAX_ARTIFACT_BYTES:
            continue
        dest = work / f"art-{a['id']}.zip"
        ok, err = gh_download(f"/repos/{repo}/actions/artifacts/{a['id']}/zip", dest)
        loc = f"artifact {a['name']} (id {a['id']}, run {a['run']}, branch {a['branch']}, expires {a['expires_at']})"
        if not ok:
            F.add("Medium", "artifacts", loc, f"could not be downloaded for scanning: {err}")
            continue
        downloaded += 1
        scan_zip(dest, scanner, F, "artifacts", loc)
        dest.unlink()
    not_scanned = len(live) - downloaded
    if not_scanned:
        F.add("Medium", "artifacts", f"{not_scanned} unexpired artifact(s)", "not downloaded (limit or size); treat as unscanned")
    runs = gh_json_lines(f"/repos/{repo}/actions/runs?per_page=100",
                         ".workflow_runs[] | {id, name, head_branch, event, created_at, conclusion}")
    logs_ok = logs_gone = 0
    for r in runs[:MAX_LOG_RUNS]:
        dest = work / f"log-{r['id']}.zip"
        ok, _ = gh_download(f"/repos/{repo}/actions/runs/{r['id']}/logs", dest)
        if not ok or not zipfile.is_zipfile(dest):
            logs_gone += 1
            dest.unlink(missing_ok=True)
            continue
        logs_ok += 1
        scan_zip(dest, scanner, F, "logs", f"run {r['id']} ({r['name']}, {r['head_branch']}, {r['created_at'][:10]})")
        dest.unlink()
    rels = gh_json_lines(f"/repos/{repo}/releases?per_page=100", ".[] | {id, tag_name, draft, assets: (.assets|length)}")
    pages = subprocess.run(["gh", "api", f"/repos/{repo}/pages"], capture_output=True, text=True)
    return {"artifacts_total": len(arts), "artifacts_unexpired": len(live), "artifacts_scanned": downloaded,
            "artifact_families": dict(families), "runs_total": len(runs), "logs_scanned": logs_ok,
            "logs_unavailable": logs_gone, "releases": len(rels),
            "pages": "enabled" if pages.returncode == 0 else "not enabled (or not visible)"}


def render(repo: str, g: dict, a: dict, F: Findings, scanner) -> str:
    order = {"High": 0, "Medium": 1, "Low": 2}
    rows = sorted(F.rows, key=lambda r: (order[r[0]], r[1], r[2]))
    counts = collections.Counter(r[0] for r in rows)
    out = [f"# Publication audit — {repo}", "",
           f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} by `web/publication/audit_repo.py` "
           "(read-only; nothing was deleted or changed). Findings name locations only; no protected text, "
           "secret value or personal data is reproduced.", "",
           "## Coverage", "",
           f"- Git: {g['refs']} refs ({len(g['branches'])} remote branches, {len(g['tags'])} tags), "
           f"{g['commits']} commits, {g['blobs']} blobs; {g['blobs_scanned']} text blobs scanned, "
           f"{g['binaries']} binaries listed for human review, {g['big_skipped']} large blobs not scanned; "
           f"{g['commit_messages_scanned']} commit messages scanned.",
           f"- Branches: {', '.join(b.replace('refs/remotes/origin/', '') for b in g['branches'])}",
           f"- Tags: {', '.join(t.replace('refs/tags/', '') for t in g['tags'])}",
           f"- Actions artifacts: {a['artifacts_total']} total, {a['artifacts_unexpired']} unexpired, "
           f"{a['artifacts_scanned']} downloaded and scanned. Families: "
           + ", ".join(f"`{k}`×{v}" for k, v in sorted(a["artifact_families"].items())),
           f"- Actions logs: {a['runs_total']} runs listed; {a['logs_scanned']} logs scanned; "
           f"{a['logs_unavailable']} unavailable (expired or not retained).",
           f"- Releases: {a['releases']}. GitHub Pages: {a['pages']}.",
           f"- Third-party reference text: {scanner.chunk_count} KB chunks (12-word shingles).", "",
           "## Summary", "",
           f"High: {counts['High']} · Medium: {counts['Medium']} · Low: {counts['Low']}", "",
           "A clean scan is not permission to publish; it is defence in depth. Remedies are proposals for the "
           "team's decision (approvals A13/A14); this tool performs none of them.", "",
           "## Findings", "", "| Severity | Area | Location | Finding |", "|---|---|---|---|"]
    out += [f"| {s} | {ar} | {loc.replace('|', '/')} | {w.replace('|', '/')} |" for s, ar, loc, w in rows]
    if not rows:
        out.append("| — | — | — | no findings |")
    out += ["", "## Proposed remedies (not performed)", "",
            "- High findings in git history or tags: choose the clean public submission repository route (A14), "
            "or an approved history remedy; tags must not be moved.",
            "- Artifacts with turn files or third-party text: delete before any visibility change, after team "
            "approval (A13), or let them expire and confirm.",
            "- Logs with findings: delete those runs' logs before any visibility change (A13).",
            "- Binaries: a human checks each listed file for account or personal data."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    scanner = LicenceScanner.from_chunks(CHUNKS)
    F = Findings()
    g = audit_git(scanner, F)
    with tempfile.TemporaryDirectory() as td:
        act = audit_actions(a.repo, scanner, F, Path(td))
    report = render(a.repo, g, act, F, scanner)
    a.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
